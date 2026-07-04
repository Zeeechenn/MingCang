"""Blind adjudication harness for judgment-gate A/B outputs.

沉淀自 2026-07-04 M61 P4 代理盲裁(owner 授权),方法:
1. 把 judgment-gate JSON 里每个案例的两臂回答盲化为 甲/乙(顺序由
   sha256(symbol+as_of) 决定,确定性可复现;answer_key 独立落盘,裁判不可见);
2. 从 DB 取 as_of 之后的真实价格/新闻/公司事件作结局包;
3. 每案例 N 个独立裁判(claude 或 codex CLI,单层调用),rubric =
   事前推理质量(明令不得因数据丰富度加分)+ 事后真实结局对照(反结果论提示)
   + 泄漏检查;输出结构化 JSON 票;
4. 多数票汇总 → 案例胜负 + 总分,按 answer_key 翻译回 starved/full。

用法(仓库根目录):
  PYTHONPATH=. python3 -m backend.tools.blind_adjudication \
      --gate-json paper_trading/m61_out/judgment_gate_XXXX.json \
      --judges 3 --judge-provider claude --judge-model sonnet

⚠️ 本工具会直接调用 claude/codex CLI。不要在 codex exec 会话内再运行
codex 裁判(codex 套 codex 会空返/超时,2026-07-03 实证)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "paper_trading" / "m61_out"

JUDGE_PROMPT = """你是 A 股投研判断质量的独立裁判。下面是一份盲裁案例包。

背景:同一个问题在 as_of 时点分别交给两套数据系统支持的分析(回答甲、回答乙),各自基于自己拿到的数据上下文作答。你不知道哪套是新系统哪套是旧系统,也不要猜。案例包末尾附有 as_of 之后真实发生的结局,仅用于事后评估;若标注"无后续数据",事后维度记 NA。

评估规则:
1. 事前质量(不看结局):证据纪律(是否只用自己上下文内+as_of 前的事实,引用是否准确)、推理是否稳健、给出的操作决断是否明确可执行。不要因为某方拿到的数据更丰富就加分——评的是判断质量,不是数据量;数据多但误用/结论错,应扣分。
2. 泄漏检查:任一回答若引用了其上下文中不存在、且属于 as_of 之后才可知的事实,标记 leakage,并说明具体语句。
3. 事后对照(看结局):假设一个真实持仓者分别执行甲/乙的决断,结合之后的实际价格路径和事件,谁的决断让持仓者结果更好(收益+风险)?避免纯结果论:推理健全但运气差 ≠ 判断差;错过大涨也是真实代价,要计入。
4. 分别给出事前赢家、事后赢家,再给总裁决。

最后只输出一个 JSON(不要其他文字):
{{"case":"{case_id}","ex_ante_winner":"甲|乙|平","ex_post_winner":"甲|乙|平|NA","overall":"甲大胜|甲小胜|平|乙小胜|乙大胜","leakage":{{"甲":null,"乙":null}},"reason":"3-5句中文裁决理由"}}

===== 盲裁案例包 =====
{packet}
"""


def _blind_order(symbol: str, as_of: str) -> list[tuple[str, str]]:
    h = int(hashlib.sha256(f"{symbol}{as_of}blind".encode()).hexdigest(), 16) % 2
    return [("starved", "甲"), ("full", "乙")] if h == 0 else [("full", "甲"), ("starved", "乙")]


def _ground_truth(symbol: str, as_of: str, db) -> dict[str, Any]:
    base = db.execute(
        "SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
        (symbol, as_of),
    ).fetchone()
    post = db.execute(
        "SELECT date, close FROM prices WHERE symbol=? AND date>? ORDER BY date", (symbol, as_of)
    ).fetchall()
    # outcome-side 读取:此处故意取 as_of 之后的真实结局,仅用于事后裁决对照(answer_key
    # 与两臂输入隔离)。禁止把该查询路径复用到任何 as_of 输入侧上下文,否则即时间穿越。
    news = db.execute(
        "SELECT published_at, title FROM news WHERE symbol=? AND published_at>? ORDER BY published_at LIMIT 40",
        (symbol, as_of + "T99"),
    ).fetchall()
    events = db.execute(
        "SELECT event_date, event_type, title FROM corporate_events WHERE symbol=? AND event_date>? ORDER BY event_date LIMIT 15",
        (symbol, as_of + "T99"),
    ).fetchall()
    return {"base": base, "post": post, "news": news, "events": events}


def _gt_lines(gt: dict[str, Any]) -> list[str]:
    lines = ["## 真实后续结局(as_of 之后实际发生,仅用于事后评估)", ""]
    base, post = gt["base"], gt["post"]
    if base and post:
        last = post[-1]
        chg = (last[1] - base[1]) / base[1] * 100
        mn = min(post, key=lambda p: p[1])
        mx = max(post, key=lambda p: p[1])
        # 日线太长时按周抽样,保留首尾
        series = post if len(post) <= 40 else post[::5] + [post[-1]]
        lines += [
            f"- 基准收盘 {base[0]}: {base[1]}",
            "- 之后收盘序列(长窗口按周抽样): " + ", ".join(f"{p[0]}={p[1]}" for p in series),
            f"- 区间涨跌 {chg:+.1f}%;最低收盘 {mn[1]}({mn[0]});最高收盘 {mx[1]}({mx[0]})",
            "",
        ]
    else:
        lines += ["- as_of 即数据末日,无后续价格。只评事前质量,事后维度记 NA。", ""]
    if gt["news"]:
        lines += ["- 之后新闻标题:"] + [f"  - {n[0][:10]} {n[1]}" for n in gt["news"][:18]] + [""]
    if gt["events"]:
        lines += ["- 之后公司事件:"] + [f"  - {e[0][:10]} {e[1]} {e[2]}" for e in gt["events"][:10]] + [""]
    return lines


def build_packet(case: dict[str, Any], db) -> tuple[str, dict[str, str]]:
    symbol, as_of = case["symbol"], case["as_of"]
    order = _blind_order(symbol, as_of)
    lines = [f"# 盲裁案例包:{case.get('id', symbol)} {symbol} (as_of {as_of})", "",
             "## 问题(提给两套系统的原题)", "", case.get("question", ""), ""]
    for arm, label in order:
        payload = case["arms"][arm]
        lines += [f"## 回答{label}", "", f"### 回答{label}当时拿到的数据上下文", "```",
                  payload.get("context", "(缺)"), "```", "",
                  f"### 回答{label}的判断全文", "```", payload.get("response", "(缺)"), "```", ""]
    lines += _gt_lines(_ground_truth(symbol, as_of, db))
    key = {label: arm for arm, label in order}
    return "\n".join(lines), key


def _run_judge(provider: str, model: str, prompt: str, timeout: int) -> str:
    if provider == "claude":
        cmd = ["claude", "-p", "--model", model]
    elif provider == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
               "-c", "model_reasoning_effort=\"medium\"", "-"]
    else:
        raise ValueError(f"unknown judge provider: {provider}")
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    return result.stdout


def _parse_verdict(raw: str) -> dict[str, Any] | None:
    matches = re.findall(r"\{[^{}]*\"overall\"[\s\S]*?\}\s*\}|\{[^{}]*\"overall\"[^{}]*\}", raw)
    for chunk in reversed(matches):
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    # 宽松兜底:抓最后一个大括号块
    start, end = raw.rfind("{\"case\""), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _translate(overall: str, key: dict[str, str]) -> str:
    if not overall or overall == "平":
        return "平"
    label = overall[0]
    arm = key.get(label, "?")
    magnitude = "大胜" if "大胜" in overall else "小胜"
    side = "B(full)" if arm == "full" else "A(starved)"
    return f"{side}{magnitude}"


def _majority(translated: list[str]) -> str:
    def side(v: str) -> str:
        return "B" if v.startswith("B") else ("A" if v.startswith("A") else "平")

    counts: dict[str, int] = {}
    for v in translated:
        counts[side(v)] = counts.get(side(v), 0) + 1
    best = max(counts, key=lambda k: counts[k])
    if list(counts.values()).count(counts[best]) > 1:
        return f"无多数({counts})"
    return f"{best} {counts[best]}-{sum(counts.values()) - counts[best]}"


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate-json", action="append", required=True, type=Path,
                        help="judgment_gate 输出 JSON,可多次传入")
    parser.add_argument("--judges", type=int, default=3)
    parser.add_argument("--judge-provider", choices=["claude", "codex"], default="claude")
    parser.add_argument("--judge-model", default="sonnet", help="claude CLI 的 --model 值(codex 忽略)")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--packets-only", action="store_true", help="只生成盲裁包与 answer_key,不跑裁判")
    args = parser.parse_args(argv)

    import sqlite3

    db = sqlite3.connect(REPO_ROOT / "mingcang.db")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = args.out_dir / f"adjudication_{ts}_{args.judge_provider}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases, packets, keys = [], {}, {}
    for path in args.gate_json:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        for case in report["cases"]:
            if case.get("status") != "ok":
                continue
            cid = case.get("id") or case["symbol"]
            cases.append((cid, case))
            packet, key = build_packet(case, db)
            packets[cid] = packet
            keys[cid] = key
            (out_dir / f"packet_{cid}.md").write_text(packet, encoding="utf-8")
    (out_dir / "answer_key.json").write_text(
        json.dumps(keys, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"packets: {len(cases)} -> {out_dir}")
    if args.packets_only:
        return 0

    jobs = [(cid, i) for cid, _ in cases for i in range(args.judges)]

    def work(job: tuple[str, int]) -> tuple[str, int, dict[str, Any] | None, str]:
        cid, idx = job
        prompt = JUDGE_PROMPT.format(case_id=cid, packet=packets[cid])
        try:
            raw = _run_judge(args.judge_provider, args.judge_model, prompt, args.timeout)
            return cid, idx, _parse_verdict(raw), raw[-2000:]
        except Exception as exc:  # noqa: BLE001 - 单票失败不拖垮全场
            return cid, idx, None, f"ERROR: {exc}"

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        results = list(pool.map(work, jobs))

    by_case: dict[str, list[dict[str, Any]]] = {}
    raw_log = []
    for cid, idx, verdict, raw in results:
        raw_log.append({"case": cid, "judge": idx, "verdict": verdict, "raw_tail": raw})
        if verdict:
            verdict["_translated"] = _translate(verdict.get("overall", ""), keys[cid])
            by_case.setdefault(cid, []).append(verdict)

    summary = {
        "run": f"blind_adjudication_{ts}",
        "judge_provider": args.judge_provider,
        "judge_model": args.judge_model if args.judge_provider == "claude" else "codex-default",
        "judges_per_case": args.judges,
        "cases": {},
    }
    for cid, verdicts in by_case.items():
        translated = [v["_translated"] for v in verdicts]
        summary["cases"][cid] = {
            "votes": translated,
            "majority": _majority(translated),
            "leakage_flags": sum(1 for v in verdicts
                                 for side, msg in (v.get("leakage") or {}).items() if msg),
            "reasons": [v.get("reason", "") for v in verdicts],
        }
    (out_dir / "verdicts_raw.json").write_text(
        json.dumps(raw_log, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({cid: c["majority"] for cid, c in summary["cases"].items()},
                     ensure_ascii=False, indent=1))
    print(f"summary: {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
