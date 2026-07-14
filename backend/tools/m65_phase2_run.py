"""Run the M65 Base/Memory/Serenity/Both shadow adjudication.

The runner is manual-only and artifact-only. It reads MingCang SQLite through
``mode=ro``, freezes evidence and memory cutoffs, calls isolated Codex CLI
sessions, and writes resumable experiment artifacts under a caller-selected
directory. It never writes signals, positions, trusted memory, scheduler state,
or test2 artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.tools.m57_phase2_eval import ARM_KEYS, evaluate_scores, validate_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = Path("/private/tmp/mingcang_m65_phase2_20260715")
DEFAULT_MEMORY_CUTOFF = "2026-07-14 18:06:42"
MODEL = "gpt-5.5"
MODEL_REASONING_EFFORT = "low"
OUTPUT_TEMPLATE_VERSION = "m65_research_answer.v1"
SERENITY_CONTRACT_VERSION = "serenity_method_lens.v0_frozen"
MAX_WORKERS = 4

INDUSTRY_BY_SYMBOL = {
    "000858": "消费",
    "002050": "工业自动化与热管理",
    "002371": "半导体设备",
    "002475": "电子制造",
    "300109": "工业自动化与机器人",
    "300124": "工业自动化与机器人",
    "300274": "新能源电力电子",
    "300308": "光通信",
    "300750": "动力电池与储能",
    "600036": "银行",
    "600183": "电子材料与PCB",
    "600406": "电网设备",
    "600547": "黄金矿业",
    "601088": "煤炭与综合能源",
    "601318": "保险",
    "601689": "汽车零部件与机器人",
    "601899": "铜金矿业",
    "603259": "医药研发服务",
    "603993": "铜钴矿业",
    "688111": "软件与SaaS",
}

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"response": {"type": "string"}},
    "required": ["response"],
    "additionalProperties": False,
}

_METRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "source_fidelity": {"type": "number", "minimum": 0, "maximum": 1},
        "key_fact_coverage": {"type": "number", "minimum": 0, "maximum": 1},
        "contradiction_handling": {"type": "number", "minimum": 0, "maximum": 1},
        "falsifiability": {"type": "number", "minimum": 0, "maximum": 1},
        "hallucination_error_rate": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": [
        "source_fidelity",
        "key_fact_coverage",
        "contradiction_handling",
        "falsifiability",
        "hallucination_error_rate",
        "rationale",
    ],
    "additionalProperties": False,
}

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {label: _METRIC_SCHEMA for label in ("A", "B", "C", "D")},
            "required": ["A", "B", "C", "D"],
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
    },
    "required": ["scores", "summary"],
    "additionalProperties": False,
}

SERENITY_METHOD_LENS = """\
这是冻结的 Serenity 供应链瓶颈方法镜头，不是人格、分数或交易模型：
1. 先判断本问题是否适用供应链瓶颈分析；不适用时明确 no-op，不强行套框架。
2. 若适用，从需求、系统集成、器件、设备、材料、封测、基础设施逐层定位物理约束与稀缺层。
3. 检查扩产慢、供应商少、认证严、替代难，但缺证据时必须写 unknown，不能把通用阈值当事实。
4. 每个关键论断绑定提供材料中的来源；媒体或传闻只能作线索，数量结论必须有直接证据。
5. 必须先写反方：替代路径、产能并不稀缺、需求证伪、客户集中、治理与执行风险。
6. 至少给出三条可证伪问题、改变观点的条件、下一步需要补的直接来源。
硬边界：observe-only；不输出买卖、目标价、仓位、涨跌幅或可聚合分数。
"""


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_report_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _readable_deep_research_runs(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""
            SELECT id, symbol, as_of, input_snapshot_json, created_at
            FROM decision_runs
            WHERE run_type = 'deep_research'
            ORDER BY id
        """).fetchall()
    finally:
        con.close()

    latest_by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            snapshot = json.loads(row["input_snapshot_json"] or "{}")
        except json.JSONDecodeError:
            continue
        raw_path = str(snapshot.get("report_path") or "")
        if not raw_path:
            continue
        path = _resolve_report_path(raw_path)
        if not path.is_file():
            continue
        latest_by_path[str(path)] = {
            "decision_run_id": int(row["id"]),
            "symbol": str(row["symbol"] or ""),
            "as_of": str(row["as_of"] or ""),
            "created_at": str(row["created_at"] or ""),
            "report_path": str(path),
            "snapshot": snapshot,
        }
    return sorted(latest_by_path.values(), key=lambda item: (item["symbol"], item["report_path"]))


def _extract_sections(markdown: str) -> str:
    parts = re.split(r"(?m)^## ", markdown)
    header = parts[0].strip()[:800]
    budgets = {
        "行业/主题观察": 1200,
        "个股快照": 1200,
        "基本面快照": 1400,
        "M61 统一上下文": 6000,
        "风险复核": 1200,
        "来源审计": 8000,
        "检索闭环（evaluator + planner）": 1200,
    }
    selected = [header]
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        title = title.strip()
        budget = budgets.get(title)
        if budget is not None:
            selected.append(f"## {title}\n{body.strip()[:budget]}")
    return "\n\n".join(item for item in selected if item).strip()


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _memory_context(
    con: sqlite3.Connection,
    *,
    symbol: str,
    topic: str,
    report_path: str,
    cutoff: str,
) -> tuple[str, list[str]]:
    lines: list[str] = []
    refs: list[str] = []

    if _table_exists(con, "stock_memory_items"):
        rows = con.execute("""
            SELECT id, memory_type, summary, source_ref, confidence, created_at
            FROM stock_memory_items
            WHERE symbol = ? AND status != 'archived' AND created_at < ?
            ORDER BY importance DESC, created_at DESC, id DESC
            LIMIT 12
        """, (symbol, cutoff)).fetchall()
        for row in rows:
            source_ref = str(row["source_ref"] or "")
            if report_path in source_ref or Path(report_path).name in source_ref:
                continue
            ref = f"stock_memory_items:{row['id']}"
            refs.append(ref)
            lines.append(
                f"[{ref}] type={row['memory_type']} created_at={row['created_at']} "
                f"confidence={row['confidence']} summary={row['summary']}"
            )

    if _table_exists(con, "memory_atoms"):
        rows = con.execute("""
            SELECT id, memory_type, summary, source_ref, trust_state, created_at
            FROM memory_atoms
            WHERE scope_type = 'stock' AND scope_key = ?
              AND trust_state != 'archived' AND created_at < ?
            ORDER BY created_at DESC, id DESC
            LIMIT 8
        """, (symbol, cutoff)).fetchall()
        for row in rows:
            source_ref = str(row["source_ref"] or "")
            if report_path in source_ref or Path(report_path).name in source_ref:
                continue
            ref = f"memory_atoms:{row['id']}"
            refs.append(ref)
            lines.append(
                f"[{ref}] type={row['memory_type']} trust={row['trust_state']} "
                f"created_at={row['created_at']} summary={row['summary']}"
            )

    if _table_exists(con, "decision_memory_layered"):
        rows = con.execute("""
            SELECT id, layer, content, updated_at
            FROM decision_memory_layered
            WHERE symbol = ? AND updated_at < ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 6
        """, (symbol, cutoff)).fetchall()
        for row in rows:
            ref = f"decision_memory_layered:{row['id']}"
            refs.append(ref)
            lines.append(
                f"[{ref}] layer={row['layer']} updated_at={row['updated_at']} content={row['content']}"
            )

    if _table_exists(con, "ai_memory"):
        like_symbol = f"%{symbol}%"
        rows = con.execute("""
            SELECT id, key, value, category, scope, created_at
            FROM ai_memory
            WHERE created_at < ? AND (key LIKE ? OR value LIKE ?)
            ORDER BY created_at DESC, id DESC
            LIMIT 8
        """, (cutoff, like_symbol, like_symbol)).fetchall()
        for row in rows:
            key = str(row["key"] or "")
            if key.startswith("deep_research:") and (topic in key or symbol in str(row["value"] or "")):
                continue
            ref = f"ai_memory:{row['id']}"
            refs.append(ref)
            lines.append(
                f"[{ref}] key={key} category={row['category']} scope={row['scope']} "
                f"created_at={row['created_at']} value={row['value']}"
            )

    bounded = "\n".join(lines)[:3500]
    return bounded if bounded else "（截止点前没有可用的相关记忆）", refs


def _boundary_snapshot(con: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for table in ("signals", "positions"):
        rows = [dict(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]  # noqa: S608
        canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        result[table] = {"rows": len(rows), "sha256": _sha(canonical)}
    return result


def _research_prompt(case: dict[str, Any], arm: str) -> str:
    additions: list[str] = []
    if arm in {"memory", "both"}:
        additions.append(
            "【历史记忆上下文】\n"
            "这些记忆只用于提出复核问题，可能陈旧或有偏差；未经当前证据印证不得当作事实。\n"
            + str(case["memory_context"])
        )
    if arm in {"serenity", "both"}:
        additions.append("【方法镜头】\n" + SERENITY_METHOD_LENS)
    extra = "\n\n".join(additions) if additions else "（无额外上下文）"
    return f"""\
你正在参加 MingCang M65 研究质量盲测。只使用下方冻结证据，不得使用外部知识、联网、工具、文件或日期晚于 as_of 的信息。

问题：{case['question']}
as_of：{case['as_of']}
标的：{case['symbol']}

【冻结证据】
{case['evidence_snapshot']['text']}

【本臂额外上下文】
{extra}

请输出不超过 1400 个中文字符的结构化研究答复，统一包含：
1. 结论摘要；2. 证据支持的关键判断（逐条引用冻结证据中的标题、日期或表格定位）；
3. 矛盾与反证；4. 未知项；5. 至少三条可证伪问题；6. 下一步补证请求；7. 方法适用性。
证据不足时应主动收缩结论。禁止买卖建议、目标价、仓位、涨跌幅预测和任何聚合分数。
"""


def _blind_labels(case: dict[str, Any]) -> dict[str, str]:
    ranked = sorted(
        ARM_KEYS,
        key=lambda arm: _sha(f"{case['id']}|{case['as_of']}|{arm}"),
    )
    return dict(zip(("A", "B", "C", "D"), ranked, strict=True))


def _judge_prompt(case: dict[str, Any]) -> tuple[str, dict[str, str]]:
    labels = _blind_labels(case)
    responses = "\n\n".join(
        f"【方案{label}】\n{case['arms'][arm]['response']}"
        for label, arm in labels.items()
    )
    return f"""\
你是 MingCang M65 的单盲研究质量评审。四个方案的来源已匿名化；不得猜测或奖励某种方法名称，只按冻结证据评分。

问题：{case['question']}
as_of：{case['as_of']}

【冻结证据】
{case['evidence_snapshot']['text']}

{responses}

对 A/B/C/D 分别给出 0 到 1 的分数：
- source_fidelity：判断是否忠实来自冻结证据，引用是否可定位；
- key_fact_coverage：关键事实覆盖是否充分且不过度堆砌；
- contradiction_handling：是否主动呈现矛盾、弱来源与替代解释；
- falsifiability：是否给出具体、可检查、能改变结论的证伪条件；
- hallucination_error_rate：实质性判断中无证据、错引或虚构所占比例，越低越好。
低证据案例中，明确 abstain/unknown 应获得忠实度奖励；编造完整故事必须提高错误率。
""", labels


def _codex_command(schema_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-m",
        MODEL,
        "-c",
        f'model_reasoning_effort="{MODEL_REASONING_EFFORT}"',
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--disable",
        "browser_use",
        "--disable",
        "computer_use",
        "--disable",
        "memories",
        "--disable",
        "multi_agent",
        "--json",
        "--output-schema",
        str(schema_path),
        "-",
    ]


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(stripped[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _call_codex(prompt: str, schema_path: Path, *, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        _codex_command(schema_path),
        input=prompt,
        capture_output=True,
        text=True,
        cwd="/private/tmp",
        timeout=timeout,
    )
    response_text = ""
    usage: dict[str, int] = {}
    errors: list[str] = []
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                response_text = str(item.get("text") or "")
        elif event.get("type") == "turn.completed":
            usage = {key: int(value or 0) for key, value in (event.get("usage") or {}).items()}
        elif event.get("type") in {"error", "turn.failed"}:
            errors.append(str(event.get("message") or event.get("error") or event))
    parsed = _parse_json_object(response_text)
    return {
        "ok": proc.returncode == 0 and bool(parsed),
        "payload": parsed,
        "usage": usage,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "returncode": proc.returncode,
        "errors": errors,
        "stderr_tail": proc.stderr[-1200:],
    }


def prepare_experiment(db_path: Path, out_dir: Path, memory_cutoff: str) -> dict[str, Any]:
    runs = _readable_deep_research_runs(db_path)
    if len(runs) != 20:
        raise ValueError(f"expected exactly 20 readable cases, found {len(runs)}")

    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        boundary = _boundary_snapshot(con)
        cases: list[dict[str, Any]] = []
        for run in runs:
            symbol = run["symbol"]
            snapshot = run["snapshot"]
            topic = str(snapshot.get("topic") or Path(run["report_path"]).stem)
            evidence_text = _extract_sections(
                Path(run["report_path"]).read_text(encoding="utf-8")
            )
            memory_context, memory_refs = _memory_context(
                con,
                symbol=symbol,
                topic=topic,
                report_path=run["report_path"],
                cutoff=memory_cutoff,
            )
            case = {
                "id": f"{symbol}-{run['as_of']}",
                "symbol": symbol,
                "industry": INDUSTRY_BY_SYMBOL[symbol],
                "as_of": run["as_of"],
                "question": f"截至 {run['as_of']}，{topic} 的证据支持什么结论，主要反证、未知项和证伪条件是什么？",
                "evidence_snapshot": {
                    "digest": _sha(evidence_text),
                    "text": evidence_text,
                    "source_count": snapshot.get("source_count"),
                    "gate_status": snapshot.get("gate_status"),
                    "report_path_digest": _sha(run["report_path"]),
                    "decision_run_id": run["decision_run_id"],
                },
                "memory_cutoff": memory_cutoff,
                "memory_context": memory_context,
                "memory_refs": memory_refs,
                "output_template_version": OUTPUT_TEMPLATE_VERSION,
                "arms": {
                    arm: {"response": "", "cost_units": 0, "latency_ms": None}
                    for arm in ARM_KEYS
                },
            }
            cases.append(case)
    finally:
        con.close()

    fixture = {"cases": cases}
    validate_fixture(fixture)
    serenity_skill_path = REPO_ROOT / ".pi/skills/serenity-chokepoint/SKILL.md"
    manifest = {
        "status": "PREPARED",
        "model": MODEL,
        "model_reasoning_effort": MODEL_REASONING_EFFORT,
        "cases": len(cases),
        "industries": len({case["industry"] for case in cases}),
        "memory_cutoff": memory_cutoff,
        "output_template_version": OUTPUT_TEMPLATE_VERSION,
        "serenity_contract_version": SERENITY_CONTRACT_VERSION,
        "serenity_skill_digest": _sha(serenity_skill_path.read_text(encoding="utf-8")),
        "serenity_prompt_digest": _sha(SERENITY_METHOD_LENS),
        "boundary_before": boundary,
        "signal_effect": "none",
        "database_mode": "sqlite_mode_ro",
        "default_daily_llm_calls": 0,
    }
    _write_json(out_dir / "fixture.json", fixture)
    _write_json(out_dir / "manifest.json", manifest)
    _write_json(out_dir / "report_schema.json", REPORT_SCHEMA)
    _write_json(out_dir / "judge_schema.json", JUDGE_SCHEMA)
    return manifest


def generate_arms(out_dir: Path, workers: int = MAX_WORKERS) -> dict[str, Any]:
    fixture_path = out_dir / "fixture.json"
    fixture = _read_json(fixture_path)
    validate_fixture(fixture)
    schema_path = out_dir / "report_schema.json"
    tasks: list[tuple[int, str, dict[str, Any], Path]] = []
    for index, case in enumerate(fixture["cases"]):
        for arm in ARM_KEYS:
            result_path = out_dir / "arms" / case["id"] / f"{arm}.json"
            if result_path.is_file() and _read_json(result_path).get("ok"):
                continue
            tasks.append((index, arm, case, result_path))

    def run_one(task: tuple[int, str, dict[str, Any], Path]) -> tuple[int, str, Path, dict[str, Any]]:
        index, arm, case, result_path = task
        result = _call_codex(_research_prompt(case, arm), schema_path)
        result.update({"case_id": case["id"], "arm": arm})
        _write_json(result_path, result)
        return index, arm, result_path, result

    completed = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_WORKERS))) as pool:
        futures = {pool.submit(run_one, task): task for task in tasks}
        for future in as_completed(futures):
            index, arm, _path, result = future.result()
            completed += 1
            if result["ok"]:
                response = str(result["payload"].get("response") or "").strip()
                usage = result.get("usage") or {}
                fixture["cases"][index]["arms"][arm].update({
                    "response": response,
                    "cost_units": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
                    "latency_ms": result["latency_ms"],
                    "usage": usage,
                })
            else:
                failures.append(f"{fixture['cases'][index]['id']}:{arm}")
            _write_json(fixture_path, fixture)
            print(
                f"ARM {completed}/{len(tasks)} {fixture['cases'][index]['id']}:{arm} "
                f"{'ok' if result['ok'] else 'failed'}",
                flush=True,
            )

    for index, case in enumerate(fixture["cases"]):
        for arm in ARM_KEYS:
            result_path = out_dir / "arms" / case["id"] / f"{arm}.json"
            if not result_path.is_file():
                continue
            result = _read_json(result_path)
            if not result.get("ok"):
                continue
            response = str((result.get("payload") or {}).get("response") or "").strip()
            usage = result.get("usage") or {}
            fixture["cases"][index]["arms"][arm].update({
                "response": response,
                "cost_units": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
                "latency_ms": result.get("latency_ms"),
                "usage": usage,
            })
    _write_json(fixture_path, fixture)
    return {"attempted": len(tasks), "completed": completed, "failures": sorted(failures)}


def judge_cases(out_dir: Path, workers: int = MAX_WORKERS) -> dict[str, Any]:
    fixture = _read_json(out_dir / "fixture.json")
    validate_fixture(fixture)
    empty = [
        f"{case['id']}:{arm}"
        for case in fixture["cases"]
        for arm in ARM_KEYS
        if not case["arms"][arm]["response"].strip()
    ]
    if empty:
        raise ValueError(f"cannot judge empty arms: {empty}")
    schema_path = out_dir / "judge_schema.json"
    tasks: list[tuple[int, dict[str, Any], Path]] = []
    for index, case in enumerate(fixture["cases"]):
        result_path = out_dir / "judges" / f"{case['id']}.json"
        if result_path.is_file() and _read_json(result_path).get("ok"):
            continue
        tasks.append((index, case, result_path))

    def run_one(task: tuple[int, dict[str, Any], Path]) -> tuple[int, Path, dict[str, Any]]:
        index, case, result_path = task
        prompt, labels = _judge_prompt(case)
        result = _call_codex(prompt, schema_path)
        result.update({"case_id": case["id"], "blind_labels": labels})
        _write_json(result_path, result)
        return index, result_path, result

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_WORKERS))) as pool:
        futures = {pool.submit(run_one, task): task for task in tasks}
        completed = 0
        for future in as_completed(futures):
            _index, _path, result = future.result()
            completed += 1
            if not result["ok"]:
                failures.append(str(result["case_id"]))
            print(
                f"JUDGE {completed}/{len(tasks)} {result['case_id']} "
                f"{'ok' if result['ok'] else 'failed'}",
                flush=True,
            )
    return {"attempted": len(tasks), "failures": sorted(failures)}


def _factorial_effects(fixture: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(item["case_id"]): item for item in scores["cases"]}
    metrics = (
        "source_fidelity",
        "key_fact_coverage",
        "contradiction_handling",
        "falsifiability",
        "hallucination_error_rate",
    )
    per_case: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        values = by_id[case["id"]]["arms"]
        effects: dict[str, dict[str, float]] = {}
        for metric in metrics:
            base = float(values["base"][metric])
            memory = float(values["memory"][metric])
            serenity = float(values["serenity"][metric])
            both = float(values["both"][metric])
            effects[metric] = {
                "serenity_main": ((serenity - base) + (both - memory)) / 2,
                "memory_main": ((memory - base) + (both - serenity)) / 2,
                "interaction": both - memory - serenity + base,
            }
        per_case.append({"case_id": case["id"], "industry": case["industry"], "effects": effects})
    averages: dict[str, dict[str, float]] = {}
    for metric in metrics:
        averages[metric] = {
            effect: sum(item["effects"][metric][effect] for item in per_case) / len(per_case)
            for effect in ("serenity_main", "memory_main", "interaction")
        }
    key_metrics = ("contradiction_handling", "falsifiability")
    positive_cases = sum(
        all(item["effects"][metric]["serenity_main"] > 0 for metric in key_metrics)
        for item in per_case
    )
    industries: dict[str, list[dict[str, Any]]] = {}
    for item in per_case:
        industries.setdefault(item["industry"], []).append(item)
    positive_industries = sum(
        all(
            sum(item["effects"][metric]["serenity_main"] for item in items) / len(items) > 0
            for metric in key_metrics
        )
        for items in industries.values()
    )
    return {
        "averages": averages,
        "positive_case_rate": positive_cases / len(per_case),
        "positive_industries": positive_industries,
        "industry_count": len(industries),
        "per_case": per_case,
    }


def finalize_experiment(db_path: Path, out_dir: Path) -> dict[str, Any]:
    fixture = _read_json(out_dir / "fixture.json")
    validate_fixture(fixture)
    score_cases: list[dict[str, Any]] = []
    judge_usage: dict[str, Any] = {}
    for case in fixture["cases"]:
        result = _read_json(out_dir / "judges" / f"{case['id']}.json")
        if not result.get("ok"):
            raise ValueError(f"judge failed: {case['id']}")
        payload = result["payload"]
        labels = result["blind_labels"]
        arm_scores = {labels[label]: payload["scores"][label] for label in ("A", "B", "C", "D")}
        score_cases.append({"case_id": case["id"], "arms": arm_scores, "blind_summary": payload["summary"]})
        judge_usage[case["id"]] = {"usage": result.get("usage"), "latency_ms": result.get("latency_ms")}

    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        boundary_after = _boundary_snapshot(con)
    finally:
        con.close()
    manifest = _read_json(out_dir / "manifest.json")
    boundary_diff = 0 if boundary_after == manifest["boundary_before"] else 1
    scores = {
        "default_daily_llm_calls": 0,
        "signal_boundary_diff": boundary_diff,
        "cases": score_cases,
    }
    evaluation = evaluate_scores(fixture, scores)
    evaluation["factorial_effects"] = _factorial_effects(fixture, scores)
    evaluation["boundary_before"] = manifest["boundary_before"]
    evaluation["boundary_after"] = boundary_after
    evaluation["judge_usage"] = judge_usage
    evaluation["limitation"] = "single blind judge; generator and judge use separate gpt-5.5 sessions"
    _write_json(out_dir / "scores.json", scores)
    _write_json(out_dir / "evaluation.json", evaluation)
    manifest.update({
        "status": "COMPLETE",
        "decision": evaluation["decision"],
        "boundary_after": boundary_after,
        "signal_boundary_diff": boundary_diff,
    })
    _write_json(out_dir / "manifest.json", manifest)
    return evaluation


def run_all(db_path: Path, out_dir: Path, memory_cutoff: str, workers: int) -> dict[str, Any]:
    if not (out_dir / "fixture.json").is_file():
        prepare_experiment(db_path, out_dir, memory_cutoff)
    generated = generate_arms(out_dir, workers)
    if generated["failures"]:
        return {"status": "ARM_GENERATION_INCOMPLETE", "generation": generated}
    judged = judge_cases(out_dir, workers)
    if judged["failures"]:
        return {"status": "JUDGING_INCOMPLETE", "generation": generated, "judging": judged}
    return {"status": "COMPLETE", "evaluation": finalize_experiment(db_path, out_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="M65 live four-arm shadow adjudication")
    parser.add_argument("command", choices=("prepare", "generate", "judge", "finalize", "run"))
    parser.add_argument("--db", type=Path, default=default_sqlite_path())
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--memory-cutoff", default=DEFAULT_MEMORY_CUTOFF)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare_experiment(args.db, args.out_dir, args.memory_cutoff)
    elif args.command == "generate":
        result = generate_arms(args.out_dir, args.workers)
    elif args.command == "judge":
        result = judge_cases(args.out_dir, args.workers)
    elif args.command == "finalize":
        result = finalize_experiment(args.db, args.out_dir)
    else:
        result = run_all(args.db, args.out_dir, args.memory_cutoff, args.workers)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
