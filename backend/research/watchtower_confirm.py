"""M60 Watchtower Phase 2 — LLM confirmation layer.

Takes today's Phase 1 (zero-LLM) watchtower triggers
(``backend.tools.m60_watchtower``) and asks an LLM for one discretionary
confirmation card per *unique triggered symbol*: does the research thesis
still hold, what is the anomaly's main cause (M54 四路归因: 公司事件/政策/
行业/情绪), what is the single next question worth validating. This layer
never buys/sells and never predicts a price — the card always carries a
fixed "跟进关注≠买入建议" disclaimer and the tool schema has no target-price
field and no "买入" stance option.

LLM budget is bounded by construction: exactly one call per unique
triggered symbol, never per trigger row — a symbol that fired three trigger
types today (e.g. price z-anomaly + volume anomaly + sector resonance)
still gets exactly one card built from all three combined. The ceiling is
therefore ``len(triggered_symbols) <= len(watchlist symbols)``.

Degrades to ``stance="信息不足"`` with an explicit flag — never raises, never
silently invents an opinion, never leaves a symbol without a card — when:
  - no runtime LLM provider is configured (``has_runtime_llm_provider`` is
    False; e.g. AI_PROVIDER unset or the local CLI is missing);
  - the triggered symbol has no matching watchlist entry (should not happen
    since Phase 1 only scans watchlist symbols, but defended anyway);
  - the LLM call returns an empty dict (provider-level failure, already
    logged by the provider itself).

Context assembly (all read-only, no new writes):
  - the watchlist entry's thesis / validation_conditions / invalidation_conditions
    (``backend.research.watchlist``);
  - the symbol's research reference — long_term_label + research_pointer,
    same helper M59 uses (``backend.tools.m59_panel._build_research_reference``);
  - today's trigger detail (type/value/detail) for this symbol, deduplicated;
  - L0 memory recall when ``settings.research_l0_recall_enabled`` is True,
    via the same ``build_memory_context`` channel used by stock-context /
    project-context (``backend.memory.stock_memory``).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path, settings
from backend.llm import get_provider, has_runtime_llm_provider
from backend.research.watchlist import load_watchlists
from backend.tools.m59_panel import _build_research_reference
from backend.tools.m60_watchtower import DEFAULT_OUTPUT_DIR as WATCHTOWER_OUTPUT_DIR

SCHEMA_VERSION = "m60_watchtower_confirm.v1"
CONFIRM_FILENAME_PREFIX = "m60_confirm_"
DISCLAIMER = "跟进关注≠买入建议"

STANCE_FOLLOW = "跟进关注"
STANCE_HOLD_OFF = "暂不跟进"
STANCE_INSUFFICIENT = "信息不足"
VALID_STANCES = (STANCE_FOLLOW, STANCE_HOLD_OFF, STANCE_INSUFFICIENT)

THESIS_INTACT = "论点仍成立"
THESIS_CHALLENGED = "受挑战"
THESIS_UNKNOWN = "无法判断"
VALID_THESIS_STATUSES = (THESIS_INTACT, THESIS_CHALLENGED, THESIS_UNKNOWN)

FLAG_NO_PROVIDER = "degraded:no_llm_provider"
FLAG_EMPTY_LLM_RESPONSE = "degraded:empty_llm_response"
FLAG_NO_WATCHLIST_ENTRY = "missing:watchlist_entry_for_symbol"

_MAX_RISKS = 2
_REDLINE_REPLACEMENTS = {"买入": "关注", "目标价": "参考位"}

_SYSTEM_PROMPT = (
    "你是 MingCang 观察哨确认层的研究助理，只对观察清单内今日已触发的标的做第二时间研究裁量。"
    "你绝不能给出买入/卖出指令、目标价或仓位建议；stance='跟进关注' 只表示值得继续第二时间盯盘，"
    "不是买入建议，系统会在卡片上固定标注'跟进关注≠买入建议'。"
    "reasoning 必须点名本次异动最可能的主因，四选一：公司事件/政策/行业/情绪。"
    "thesis_status 需基于清单里的验证条件(validation_conditions)与失效条件(invalidation_conditions)裁量，"
    "而不是凭直觉。"
)

_CONFIRM_TOOL = {
    "name": "watchtower_confirmation_card",
    "description": "观察哨触发标的的LLM确认卡：论点是否仍成立、异动归因、风险与下一步验证问题。",
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {
                "type": "string",
                "enum": list(VALID_STANCES),
                "description": "跟进关注/暂不跟进/信息不足之一；不得输出买入或卖出指令",
            },
            "reasoning": {
                "type": "string",
                "description": "一句话理由，须点名本次异动主因：公司事件/政策/行业/情绪之一",
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "至多2条风险",
            },
            "validation_question": {
                "type": "string",
                "description": "基于清单验证/失效条件提炼的一条待验证问题",
            },
            "thesis_status": {
                "type": "string",
                "enum": list(VALID_THESIS_STATUSES),
                "description": "论点仍成立/受挑战/无法判断，基于清单验证/失效条件裁量",
            },
        },
        "required": ["stance", "reasoning", "risks", "validation_question", "thesis_status"],
    },
}


class WatchtowerConfirmInputError(RuntimeError):
    """Raised when the caller passes a malformed watchtower report."""


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _triggers_by_symbol(triggers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trigger in triggers:
        symbol = trigger.get("symbol")
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(trigger)
    return grouped


def _watchlist_entries_by_symbol(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapping: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for symbol in entry["symbols"]:
            mapping.setdefault(symbol, []).append(entry)
    return mapping


def _memory_recall_text(db: Any, symbol: str) -> dict[str, Any]:
    """L0/stock-memory recall for this symbol, reference-only, never raises."""
    if db is None:
        return {"text": "", "status": "missing:no_db_session"}
    try:
        from backend.memory.stock_memory import build_memory_context

        context = build_memory_context(
            db,
            symbol=symbol,
            task_type="watchtower_confirm",
            include_l0=settings.research_l0_recall_enabled,
        )
        return {"text": context.get("text", ""), "status": "ok"}
    except Exception as exc:  # noqa: BLE001 — memory recall must never break the confirm layer
        return {"text": "", "status": f"error:{exc}"}


def _build_symbol_context(
    *,
    symbol: str,
    themes: list[str],
    symbol_triggers: list[dict[str, Any]],
    watchlist_entries: list[dict[str, Any]],
    research_reference: dict[str, Any],
    memory_recall: dict[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "themes": themes,
        "thesis": [entry["thesis"] for entry in watchlist_entries],
        "validation_conditions": sorted(
            {condition for entry in watchlist_entries for condition in entry["validation_conditions"]}
        ),
        "invalidation_conditions": sorted(
            {condition for entry in watchlist_entries for condition in entry["invalidation_conditions"]}
        ),
        "triggers_today": [
            {
                "trigger_type": trigger.get("trigger_type"),
                "value": trigger.get("value"),
                "detail": trigger.get("detail"),
                "price": trigger.get("price"),
            }
            for trigger in symbol_triggers
        ],
        "research_reference": research_reference,
        "memory_recall": memory_recall.get("text", ""),
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return (
        "请基于以下观察清单研究上下文与今日触发明细，对该标的做本轮确认层裁量。"
        "stance 只能三选一，不得输出买入/卖出指令或目标价；risks 最多2条；"
        "validation_question 只给一条，且要基于 validation_conditions/invalidation_conditions 提炼。\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    )


def _apply_wording_redline(text_value: str) -> str:
    """Defensive post-filter: never let a literal '买入'/'目标价' survive into the card."""
    for banned, replacement in _REDLINE_REPLACEMENTS.items():
        text_value = text_value.replace(banned, replacement)
    return text_value


def _base_card(symbol: str, themes: list[str], symbol_triggers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "theme": ",".join(themes),
        "themes": themes,
        "as_of": None,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "triggers_today": [
            {
                "trigger_type": trigger.get("trigger_type"),
                "value": trigger.get("value"),
            }
            for trigger in symbol_triggers
        ],
        "disclaimer": DISCLAIMER,
    }


def _degrade(card: dict[str, Any], *, reasoning: str, flag: str) -> dict[str, Any]:
    card.update(
        {
            "stance": STANCE_INSUFFICIENT,
            "reasoning": reasoning,
            "risks": [],
            "validation_question": "",
            "thesis_status": THESIS_UNKNOWN,
            "used_llm": False,
            "flags": [flag],
        }
    )
    return card


def confirm_symbol(
    *,
    symbol: str,
    themes: list[str],
    symbol_triggers: list[dict[str, Any]],
    watchlist_entries: list[dict[str, Any]],
    research_reference: dict[str, Any],
    memory_recall: dict[str, Any],
    provider_available: bool,
) -> dict[str, Any]:
    """Build one confirmation card for one already-triggered symbol.

    Exactly zero or one LLM call happens inside this function — callers must
    not call this more than once per symbol per run (see
    ``build_confirmation_report``'s dedup-by-symbol grouping), which is what
    bounds the whole layer's LLM call count to the triggered-symbol count.
    """
    card = _base_card(symbol, themes, symbol_triggers)

    if not provider_available:
        return _degrade(card, reasoning="LLM 运行时不可用，确认层已降级，未做裁量。", flag=FLAG_NO_PROVIDER)

    if not watchlist_entries:
        return _degrade(
            card,
            reasoning="该标的今日触发但未在观察清单中找到对应条目，无法裁量。",
            flag=FLAG_NO_WATCHLIST_ENTRY,
        )

    context = _build_symbol_context(
        symbol=symbol,
        themes=themes,
        symbol_triggers=symbol_triggers,
        watchlist_entries=watchlist_entries,
        research_reference=research_reference,
        memory_recall=memory_recall,
    )
    prompt = _build_prompt(context)
    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_CONFIRM_TOOL,
        system=_SYSTEM_PROMPT,
        max_tokens=500,
        model_tier="fast",
    )
    try:
        from backend.ops.llm_usage import log_llm_usage

        log_llm_usage("watchtower_confirm", _SYSTEM_PROMPT + prompt, json.dumps(data or {}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — usage logging must never break the confirm layer
        pass

    if not data:
        return _degrade(card, reasoning="LLM 返回为空，确认层已降级，未做裁量。", flag=FLAG_EMPTY_LLM_RESPONSE)

    stance = data.get("stance")
    if stance not in VALID_STANCES:
        stance = STANCE_INSUFFICIENT
    thesis_status = data.get("thesis_status")
    if thesis_status not in VALID_THESIS_STATUSES:
        thesis_status = THESIS_UNKNOWN
    risks = [_apply_wording_redline(str(x))[:120] for x in (data.get("risks") or [])][:_MAX_RISKS]
    reasoning = _apply_wording_redline(str(data.get("reasoning", "")))[:200]
    validation_question = _apply_wording_redline(str(data.get("validation_question", "")))[:200]

    card.update(
        {
            "stance": stance,
            "reasoning": reasoning,
            "risks": risks,
            "validation_question": validation_question,
            "thesis_status": thesis_status,
            "used_llm": True,
            "flags": [],
        }
    )
    return card


def build_confirmation_report(
    *,
    watchtower_report: dict[str, Any],
    db_path: str | Path | None = None,
    watchlist_dir: str | Path | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Return an m60_watchtower_confirm.v1 payload without writing the database.

    ``watchtower_report`` is the already-built Phase 1 payload (in-memory
    dict, or loaded from a ``m60_watchtower_<date>.json`` file) — this
    function never re-runs detection itself. ``db`` is an optional SQLAlchemy
    session used only for L0/stock-memory recall; when omitted, memory recall
    degrades to an explicit ``missing:no_db_session`` status per symbol
    rather than raising.
    """
    if not isinstance(watchtower_report, dict):
        raise WatchtowerConfirmInputError("watchtower_report must be a dict")

    resolved_db_path = Path(db_path) if db_path is not None else default_sqlite_path()
    entries, watchlist_errors = (
        load_watchlists(watchlist_dir) if watchlist_dir is not None else load_watchlists()
    )
    entries_by_symbol = _watchlist_entries_by_symbol(entries)

    triggers = watchtower_report.get("triggers") or []
    grouped = _triggers_by_symbol(triggers)
    triggered_symbols = sorted(grouped)
    as_of = watchtower_report.get("as_of")

    provider_available = has_runtime_llm_provider(settings)

    cards: list[dict[str, Any]] = []
    n_llm_calls = 0
    with _connect_readonly(resolved_db_path) as con:
        for symbol in triggered_symbols:
            symbol_triggers = grouped[symbol]
            themes = sorted({theme for trigger in symbol_triggers for theme in (trigger.get("themes") or [])})
            watchlist_entries = entries_by_symbol.get(symbol, [])
            research_reference = _build_research_reference(con, symbol, as_of or "")
            memory_recall = _memory_recall_text(db, symbol)
            card = confirm_symbol(
                symbol=symbol,
                themes=themes,
                symbol_triggers=symbol_triggers,
                watchlist_entries=watchlist_entries,
                research_reference=research_reference,
                memory_recall=memory_recall,
                provider_available=provider_available,
            )
            card["as_of"] = as_of
            if card.get("used_llm"):
                n_llm_calls += 1
            cards.append(card)

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "watchlist_errors": watchlist_errors,
        "provider_available": provider_available,
        "n_triggered_symbols": len(triggered_symbols),
        "n_llm_calls": n_llm_calls,
        "cards": cards,
        "disclaimer": DISCLAIMER,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# M60 观察哨确认层 ({report.get('as_of')})",
        "",
        report["disclaimer"],
        f"provider_available={report['provider_available']} | 触发去重symbol数={report['n_triggered_symbols']} "
        f"| LLM调用数={report['n_llm_calls']}",
        "",
    ]
    if report["watchlist_errors"]:
        lines.append("清单加载错误(未静默丢弃):")
        for error in report["watchlist_errors"]:
            lines.append(f"- {error}")
        lines.append("")
    if not report["cards"]:
        lines.append("今日无触发标的，无需确认。")
    else:
        lines.append("| symbol | theme | stance | thesis_status | reasoning | risks | validation_question |")
        lines.append("|---|---|---|---|---|---|---|")
        for card in report["cards"]:
            lines.append(
                f"| {card['symbol']} | {card['theme']} | {card['stance']} | {card['thesis_status']} | "
                f"{card['reasoning']} | {'; '.join(card['risks'])} | {card['validation_question']} |"
            )
    return "\n".join(lines)


def _default_output_paths(as_of: str, output_dir: Path) -> tuple[Path, Path]:
    stem = f"{CONFIRM_FILENAME_PREFIX}{as_of}"
    return output_dir / f"{stem}.json", output_dir / f"{stem}.md"


def _find_latest_watchtower_file(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(output_dir.glob("m60_watchtower_*.json"))
    return candidates[-1] if candidates else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the M60 Phase 2 LLM confirmation layer over an existing watchtower scan."
    )
    parser.add_argument(
        "--watchtower-json",
        type=Path,
        default=None,
        help="Path to an existing m60_watchtower_<date>.json; defaults to the latest one under --output-dir",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--watchlist-dir", type=Path, default=None, help="Watchlist JSON directory")
    parser.add_argument("--output-dir", type=Path, default=WATCHTOWER_OUTPUT_DIR, help="Where to read/write JSON+Markdown output")
    parser.add_argument("--no-write", action="store_true", help="Print only; skip writing output files")
    args = parser.parse_args(argv)

    watchtower_json = args.watchtower_json or _find_latest_watchtower_file(args.output_dir)
    if watchtower_json is None:
        raise SystemExit(
            f"no m60_watchtower_*.json found under {args.output_dir}; run `python -m backend.tools.m60_watchtower` first"
        )
    watchtower_report = json.loads(Path(watchtower_json).read_text(encoding="utf-8"))

    db = None
    close_db = False
    try:
        from backend.data.database import SessionLocal

        db = SessionLocal()
        close_db = True
    except Exception:
        db = None

    try:
        report = build_confirmation_report(
            watchtower_report=watchtower_report,
            db_path=args.db,
            watchlist_dir=args.watchlist_dir,
            db=db,
        )
    finally:
        if close_db and db is not None:
            db.close()

    markdown = render_markdown(report)

    if not args.no_write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        json_path, md_path = _default_output_paths(report["as_of"] or "unknown", args.output_dir)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")

    print(markdown)


if __name__ == "__main__":
    main()
