"""M61 Phase 4 judgment-gate harness.

This harness compares a pre-M61 starved evidence slice against the full M61
context pack. It deliberately does not self-grade; leader/owner grading is blind
and filled into the report after review.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.database import NewsItem, SessionLocal


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "paper_trading" / "m61_out"

CASES: list[dict[str, str]] = [
    {
        "id": "tianfu_drawdown",
        "symbol": "300394",
        "name": "天孚通信",
        "as_of": "2026-06-05",
        "question": "你持有天孚通信,请给出持仓决断(继续持有/减仓/清仓)并说明理由与关键风险。",
        "outcome_note": "已知结局:6月中下旬深跌约-30%(截至07-04未收复)。好判断=识别风险并减仓/警示。",
    },
    {
        "id": "corning_glassbridge",
        "symbol": "601869",
        "name": "长飞光纤",
        "as_of": "2026-06-28",
        "question": "康宁'玻璃桥'技术传言引发光通信板块大跌,你持有长飞光纤,请判断这是逻辑破坏还是情绪错杀,并给出持仓决断。",
        "outcome_note": "参考结局:产业研究者定性'错杀,加速CPO商业化而非利空';截至07-04股价未收复但产业逻辑未见恶化。好判断=区分传言与实证、引用产业证据而非只看价格。",
    },
    {
        "id": "gigadevice_divergence",
        "symbol": "603986",
        "name": "兆易创新",
        "as_of": "2026-07-03",
        "question": "公式信号给出'规避'(技术分-33.7),但产业研究者认为存储原厂逻辑未变可继续持有。你怎么裁量?给出持仓决断与依据。",
        "outcome_note": "结局未定(07-04)。好判断=同时引用双方证据、给出可验证的观察点,而非单边跟随。",
    },
    {
        "id": "innovative_drug",
        "symbol": "603259",
        "name": "药明康德",
        "as_of": "2026-06-10",
        "question": "深度研究提示创新药/CXO板块方向向好。请评估药明康德是否值得纳入观察/建仓候选,并说明依据。",
        "outcome_note": "已知结局:该股随后上涨。好判断=从数据中识别出方向性证据并给出积极候选结论。",
    },
]

ARM_LABELS = {"starved": "ARM A starved(改造前视角)", "full": "ARM B full(改造后)"}
RESPONSE_TOOL = {
    "name": "m61_judgment_response",
    "description": "Return the judgment answer as a raw text field.",
    "input_schema": {
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "完整中文回答。每个判断性主张必须说明所引用的提供证据。字符串内容禁止使用英文双引号字符,如需引用术语请使用中文书名号或中文引号。",
            }
        },
        "required": ["response"],
        "additionalProperties": True,
    },
}


def _as_of_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value + "T23:59:59")


def _section_markers(context: str) -> list[str]:
    markers: list[str] = []
    for line in context.splitlines():
        if line.startswith("【") and "】" in line:
            markers.append(line[1:line.index("】")])
        elif line.startswith("(") and ":" in line:
            markers.append(line[1:line.index(":")])
    return markers


def _news_title_lines(symbol: str, as_of: datetime, db) -> list[str]:
    rows = (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at <= as_of)
        .order_by(NewsItem.published_at.desc())
        .limit(8)
        .all()
    )
    if not rows:
        return ["(新闻标题: 无数据)"]
    lines = ["【新闻标题】"]
    for row in rows:
        lines.append(f" - title={row.title} | published_at={row.published_at.isoformat()} | provider={row.provider or row.source}")
    return lines


def _starved_context(case: dict[str, str], db) -> str:
    as_of = _as_of_datetime(case["as_of"])
    price_pack = build_stock_context_pack(case["symbol"], as_of=as_of, sections=["price"], db=db)
    price_text = render_context_text(price_pack, max_chars=3500)
    return price_text + "\n" + "\n".join(_news_title_lines(case["symbol"], as_of, db))


def _full_context(case: dict[str, str], db) -> str:
    as_of = _as_of_datetime(case["as_of"])
    return render_context_text(build_stock_context_pack(case["symbol"], as_of=as_of, db=db), 3500)


def _build_prompt(case: dict[str, str], context: str) -> str:
    return (
        f"严格基于以下截至{case['as_of']}的信息作答,不得使用此日期之后的任何知识。\n"
        "你必须为每个判断性主张标明它引用了哪条已提供证据；若证据不足,请明确写出不足。\n\n"
        "输出会被 JSON 解析: response 字段内禁止使用英文双引号字符,如需引用术语请使用中文引号「」或书名号《》。\n\n"
        "【上下文】\n"
        f"{context}\n\n"
        "【问题】\n"
        f"{case['question']}"
    )


def _arm_payload(case: dict[str, str], arm: str, db) -> dict[str, Any]:
    context = _starved_context(case, db) if arm == "starved" else _full_context(case, db)
    return {
        "label": ARM_LABELS[arm],
        "context": context,
        "prompt": _build_prompt(case, context),
        "stats": {
            "chars": len(context),
            "sections_present": _section_markers(context),
        },
        "response": "",
        "raw_result": None,
        "status": "dry_run",
        "error": None,
    }


def _default_provider_factory():
    # Required for this gate: force Claude first and disable Codex fallback before
    # LocalCLIProvider reads settings/env during initialization and call time.
    # LOCAL_CLI_NO_CODEX_FALLBACK is read directly from os.environ during calls;
    # local_cli_prefer_codex is a settings field, so set both the env and the
    # in-process settings value before provider init to avoid a cached default.
    os.environ["LOCAL_CLI_PREFER_CODEX"] = "false"
    os.environ["LOCAL_CLI_NO_CODEX_FALLBACK"] = "true"
    from backend.config import settings
    from backend.llm.local_cli_provider import LocalCLIProvider

    settings.local_cli_prefer_codex = False
    return LocalCLIProvider(timeout=300)


def _call_llm(provider, prompt: str) -> tuple[str, dict[str, Any], str | None]:
    for attempt in range(2):
        try:
            complete_once = getattr(provider.complete_structured, "__wrapped__", None)
            kwargs = {
                "prompt": prompt,
                "tool": RESPONSE_TOOL,
                "system": (
                    "你是明仓M61判断门回放评估助手。只基于提供材料作答,不得补充日期后的事实。"
                    "你的 JSON response 字段内禁止使用英文双引号字符,引用术语请用中文引号「」。"
                ),
                "max_tokens": 1200,
                "model_tier": "capable",
            }
            if complete_once is None:
                result = provider.complete_structured(**kwargs)
            else:
                result = complete_once(provider, **kwargs)
        except Exception as exc:  # noqa: BLE001 - keep case-level resilience
            fatal_result = getattr(exc, "result", None)
            result = fatal_result if isinstance(fatal_result, dict) else {}
        if result and str(result.get("response", "")).strip():
            return str(result["response"]), result, None
        if attempt == 0:
            continue
    return "", result if "result" in locals() else {}, "LLM_FAILED_EMPTY_RESPONSE"


def _selected_cases(case_ids: list[str] | None) -> list[dict[str, str]]:
    if not case_ids:
        return CASES
    known = {case["id"]: case for case in CASES}
    unknown = [case_id for case_id in case_ids if case_id not in known]
    if unknown:
        raise ValueError(f"unknown case id(s): {', '.join(unknown)}")
    return [known[case_id] for case_id in case_ids]


def run_gate(
    *,
    case_ids: list[str] | None = None,
    dry_run: bool = False,
    db=None,
    out_dir: Path = DEFAULT_OUT_DIR,
    timestamp: str | None = None,
    provider_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    own_session = db is None
    session = db or SessionLocal()
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M")
    provider_factory = provider_factory or _default_provider_factory
    report: dict[str, Any] = {
        "meta": {
            "timestamp": ts,
            "dry_run": dry_run,
            "llm_provider": "LocalCLIProvider",
            "model_tier": "capable",
            "timeout_seconds": 300,
            "env_forced": {
                "LOCAL_CLI_PREFER_CODEX": "false",
                "LOCAL_CLI_NO_CODEX_FALLBACK": "true",
            },
            "limitation": "Prompts forbid post-as_of knowledge and require evidence citations, but model leakage cannot be fully eliminated; review should flag any leaked post-date facts.",
        },
        "cases": [],
    }
    try:
        provider = None if dry_run else provider_factory()
        for case in _selected_cases(case_ids):
            case_result = {
                **case,
                "status": "dry_run" if dry_run else "ok",
                "arms": {
                    "starved": _arm_payload(case, "starved", session),
                    "full": _arm_payload(case, "full", session),
                },
            }
            if not dry_run:
                for arm in ("starved", "full"):
                    payload = case_result["arms"][arm]
                    response, raw_result, error = _call_llm(provider, payload["prompt"])
                    payload["response"] = response
                    payload["raw_result"] = raw_result
                    payload["status"] = "failed" if error else "ok"
                    payload["error"] = error
                    if error:
                        case_result["status"] = "failed"
            report["cases"].append(case_result)

        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"judgment_gate_{ts}.json"
        md_path = out_dir / f"judgment_gate_{ts}.md"
        report["json_path"] = str(json_path)
        report["markdown_path"] = str(md_path)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        return report
    finally:
        if own_session:
            session.close()


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M61 Phase 4 判断门 Harness",
        "",
        f"- timestamp: {report['meta']['timestamp']}",
        f"- dry_run: {report['meta']['dry_run']}",
        "- LLM: LocalCLIProvider, model_tier=capable, timeout=300s",
        "- env: LOCAL_CLI_PREFER_CODEX=false; LOCAL_CLI_NO_CODEX_FALLBACK=true",
        f"- limitation: {report['meta']['limitation']}",
        "",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"## {case['id']} - {case['name']}({case['symbol']})",
                "",
                f"- as_of: {case['as_of']}",
                f"- status: {case['status']}",
                f"- question: {case['question']}",
                f"- outcome_note: {case['outcome_note']}",
                "",
            ]
        )
        for arm in ("starved", "full"):
            payload = case["arms"][arm]
            stats = payload["stats"]
            lines.extend(
                [
                    f"### {payload['label']}",
                    "",
                    f"- context_chars: {stats['chars']}",
                    f"- sections_present: {', '.join(stats['sections_present']) or '无'}",
                    f"- status: {payload['status']}",
                    f"- error: {payload['error'] or ''}",
                    "",
                    "#### Prompt Context",
                    "",
                    "```text",
                    payload["context"],
                    "```",
                    "",
                    "#### Response",
                    "",
                    "```text",
                    payload["response"] or ("LLM_FAILED: " + str(payload["error"]) if payload["error"] else ""),
                    "```",
                    "",
                ]
            )
        lines.extend(["## 裁决(leader/owner填写)", "", "", ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the M61 Phase 4 judgment-gate harness.")
    parser.add_argument("--cases", help="Comma-separated case ids. Defaults to all four cases.")
    parser.add_argument("--dry-run", action="store_true", help="Build and print prompts without LLM calls.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()] if args.cases else None
    report = run_gate(case_ids=case_ids, dry_run=args.dry_run, out_dir=args.out_dir)
    if args.dry_run:
        for case in report["cases"]:
            for arm in ("starved", "full"):
                payload = case["arms"][arm]
                print(f"===== {case['id']} {payload['label']} =====")
                print(payload["prompt"])
                print()
    print(json.dumps({"markdown": report["markdown_path"], "json": report["json_path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
