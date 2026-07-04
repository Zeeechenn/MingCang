"""Command-line bridge for local MingCang agent shells."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from backend.agent.context import (
    mingcang_context,
    mingcang_memory_context,
    mingcang_memory_snapshot,
    mingcang_stock_context,
)
from backend.agent.security import AgentSecurityError, require_agent_access
from backend.data.cache_policy import workflow_cache_policy
from backend.data.database import SessionLocal, init_db

# M21.4：init_db 幂等但每次调用仍需遍历 PRAGMA，进程内只需运行一次
_init_db_done: bool = False


def _json_default(value: Any) -> str:
    return str(value)


def _emit(payload: dict, *, pretty: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, default=_json_default))


def _with_db(fn: Callable[[Any], dict], *, ensure_schema: bool = False) -> dict:
    global _init_db_done
    if ensure_schema and not _init_db_done:
        init_db()
        _init_db_done = True
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


def _with_read_only_memory_usage(fn: Callable[[], dict]) -> dict:
    from backend.memory.stock_memory import suppress_memory_usage_recording

    with suppress_memory_usage_recording():
        return fn()


def _read_guard(args: argparse.Namespace) -> None:
    require_agent_access("read", api_key=args.api_key)


def _write_guard(args: argparse.Namespace, action: str) -> None:
    require_agent_access("write", api_key=args.api_key, action=action)


def _parse_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid --payload-json: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--payload-json must decode to a JSON object")
    return payload


def _normalize_global_options(argv: list[str]) -> list[str]:
    """Allow global CLI flags before or after the subcommand."""
    globals_: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--pretty":
            globals_.append(item)
            index += 1
        elif item == "--api-key":
            if index + 1 >= len(argv):
                rest.append(item)
                index += 1
            else:
                globals_.extend([item, argv[index + 1]])
                index += 2
        elif item.startswith("--api-key="):
            globals_.append(item)
            index += 1
        else:
            rest.append(item)
            index += 1
    return [*globals_, *rest]


def _latest_price_date(db) -> str | None:
    from sqlalchemy import func
    from sqlalchemy.exc import OperationalError

    from backend.data.database import Price

    try:
        return db.query(func.max(Price.date)).scalar()
    except OperationalError:
        return None


def _command_health(args: argparse.Namespace) -> dict:
    _read_guard(args)

    def _health(db):
        context = mingcang_context(db)
        watchlist_count = context["watchlist"]["active_count"]
        memory_count = context["memory"]["ai_memory_count"]
        price_date = _latest_price_date(db) or "缺"
        summary = f"数据库正常,追踪{watchlist_count}支,记忆{memory_count}条,最新价格{price_date}"
        return {
            "ok": True,
            "summary": summary,
            "agent_mode": context["agent_mode"],
            "project_root": context["project_root"],
            "memory": context["memory"],
            "positions": context["positions"],
            "watchlist": context["watchlist"],
        }

    return _with_read_only_memory_usage(lambda: _with_db(_health))


def _command_project_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(
        lambda: _with_db(lambda db: mingcang_context(db, symbol=args.symbol))
    )


def _command_memory_snapshot(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(lambda: _with_db(mingcang_memory_snapshot))


def _command_memory_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(
        lambda: _with_db(lambda db: mingcang_memory_context(
            db,
            symbol=args.symbol,
            query=args.query,
            task_type=args.task_type,
            limit=args.limit,
        ))
    )


def _command_stock_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(
        lambda: _with_db(lambda db: mingcang_stock_context(db, args.symbol))
    )


def _command_global_data(args: argparse.Namespace) -> dict:
    _read_guard(args)
    from backend.data.global_data import build_global_data_context

    return _with_read_only_memory_usage(
        lambda: _with_db(lambda db: build_global_data_context(
            db,
            market=args.market,
            symbol=args.symbol,
            intent=args.intent,
        ))
    )


def _command_evidence_lookahead_check(args: argparse.Namespace) -> dict:
    _read_guard(args)
    from backend.evidence.lookahead import run_lookahead_check_for_database_url

    return _with_read_only_memory_usage(
        lambda: run_lookahead_check_for_database_url(
            as_of=args.as_of,
            demo_mode=args.demo,
        )
    )


def _command_action(args: argparse.Namespace) -> dict:
    from backend.agent.action_registry import get_action_definition

    payload = _parse_payload(args.payload_json)
    definition = get_action_definition(args.name)
    base = {
        "action": definition.name,
        "risk_level": definition.risk_level,
        "requires_confirmation": definition.requires_confirmation,
        "schema_version": definition.schema_version,
        "input_schema": definition.input_schema,
    }
    if not args.confirm:
        return {**base, "dry_run": True, "payload": payload}

    _write_guard(args, definition.name)

    def _execute(db):
        from backend.agent.action_registry import execute_registered_action

        return execute_registered_action(definition.name, payload, db)

    return {**base, "dry_run": False, "executed": True, "result": _with_db(_execute, ensure_schema=True)}


def _command_actions(args: argparse.Namespace) -> dict:
    _read_guard(args)
    from backend.agent.action_registry import list_action_definitions

    return {"actions": list_action_definitions()}


def _command_tools(args: argparse.Namespace) -> dict:
    _read_guard(args)
    from backend.tools.registry import missing_retained_tools, tools_registry_payload

    payload = tools_registry_payload(args.category)
    payload["coverage"] = {
        "missing_retained_tools": sorted(missing_retained_tools()),
    }
    return payload


def _workflow_payload(args: argparse.Namespace, phase: str) -> dict:
    _read_guard(args)
    workflows = {
        "premarket": {
            "label": "盘前看",
            "one_sentence": "盘前只看隔夜海外、今日事件、公告新闻和持仓风险线，把事项列入盘后决断。",
            "reused_entrypoints": [
                "python3 -m backend.tools.m63_daily --mode premarket",
                "GET /api/system/data-coverage",
                "GET /api/system/health",
            ],
            "side_effects_if_executed": ["writes paper_trading/m63_out/premarket_<date>.md"],
            "operator_command": "python3 -m backend.tools.m63_daily --mode premarket",
        },
        "intraday": {
            "label": "盘中记",
            "one_sentence": "盘中只记录观察哨触发、止损线接近和价格异动，明确决断留到盘后。",
            "reused_entrypoints": [
                "python3 -m backend.tools.m63_daily --mode intraday",
                "backend.tools.m60_watchtower.build_watchtower_report",
                "GET /api/system/health",
            ],
            "side_effects_if_executed": ["writes paper_trading/m63_out/intraday_<date>.md"],
            "operator_command": "python3 -m backend.tools.m63_daily --mode intraday",
        },
        "postmarket": {
            "label": "盘后决",
            "one_sentence": "盘后串起补数、观察哨、accrual、出场影子、面板和触发路由，输出人话决断报告。",
            "reused_entrypoints": [
                "python3 -m backend.tools.m63_daily --mode postmarket",
                "python3 -m backend.tools.m63_daily --mode postmarket --no-llm",
                "backend.tools.m63_daily.run_trigger_router",
            ],
            "side_effects_if_executed": [
                "writes paper_trading/m63_out/postmarket_<date>.md",
                "updates ~/.mingcang/m63_research_queue.json",
                "may call data/LLM providers unless --no-llm is used",
            ],
            "operator_command": "python3 -m backend.tools.m63_daily --mode postmarket --no-llm",
        },
        "weekend": {
            "label": "周末复盘",
            "one_sentence": "周末刷新长期标签与周度反思、导出本周复盘报告；市场休市，不在盘中触发。",
            "reused_entrypoints": [
                "backend.scheduler.job_weekly_longterm",
                "backend.scheduler.job_weekly_long_term_reflect",
                "GET /api/export/postmarket-review.html",
                "GET /api/export/reviews.csv",
            ],
            "side_effects_if_executed": ["writes long_term_labels/reviews/memory", "may call LLM/data providers"],
            "operator_command": "python3 -m backend.agent.cli weekend --pretty",
        },
    }
    payload = workflows[phase]
    side_effects_if_executed = payload["side_effects_if_executed"]
    return {
        "ok": True,
        "note": (
            "本命令返回工作流说明(dry-run),不执行、不返回真实信号。"
            "看今日面板:python3 -m backend.tools.m59_panel;"
            "查个股:stock-context <代码>"
        ),
        "phase": phase,
        "workflow": phase,
        "label": payload["label"],
        "one_sentence": payload["one_sentence"],
        "dry_run": True,
        "heavy_tasks_executed": False,
        "executes_heavy_job": False,
        "confirmation_required": True,
        "confirmation_required_for_side_effects": True,
        "symbol": args.symbol,
        "cache_policy": workflow_cache_policy(phase),
        "reused_entrypoints": payload["reused_entrypoints"],
        "side_effects": {
            "default": [],
            "if_confirmed": side_effects_if_executed,
        },
        "side_effects_if_executed": side_effects_if_executed,
        "operator_command": payload["operator_command"],
        "disclaimer": "研究复盘，非投资建议、非价格预测。",
    }


def _command_premarket(args: argparse.Namespace) -> dict:
    return _workflow_payload(args, "premarket")


def _command_intraday(args: argparse.Namespace) -> dict:
    return _workflow_payload(args, "intraday")


def _command_postmarket(args: argparse.Namespace) -> dict:
    return _workflow_payload(args, "postmarket")


def _command_weekend(args: argparse.Namespace) -> dict:
    return _workflow_payload(args, "weekend")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MingCang local agent CLI bridge")
    parser.add_argument("--api-key", help="MingCang remote agent API key")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="read agent health")
    health.set_defaults(handler=_command_health)

    project = subparsers.add_parser(
        "project-context",
        help="read project startup context",
    )
    project.add_argument("--symbol", help="optional symbol context to include")
    project.set_defaults(handler=_command_project_context)

    memory = subparsers.add_parser(
        "memory-snapshot",
        help="read project-owned memory summary",
    )
    memory.set_defaults(handler=_command_memory_snapshot)

    memory_context = subparsers.add_parser(
        "memory-context",
        help="read prompt-ready stock memory context",
    )
    memory_context.add_argument("--symbol")
    memory_context.add_argument("--query")
    memory_context.add_argument("--task-type", default="research")
    memory_context.add_argument("--limit", type=int, default=8)
    memory_context.set_defaults(handler=_command_memory_context)

    stock = subparsers.add_parser(
        "stock-context",
        help="read one stock's agent context",
    )
    stock.add_argument("symbol")
    stock.set_defaults(handler=_command_stock_context)

    global_data = subparsers.add_parser(
        "global-data",
        aliases=["全球数据"],
        help="read M41 global data envelope by market, symbol, and intent"
        "（global-data 与 全球数据 等价，双别名同一命令）",
    )
    global_data.add_argument("symbol")
    global_data.add_argument("--market", choices=["CN", "HK", "US"], default="CN")
    global_data.add_argument(
        "--intent",
        default="daily_ohlcv",
        help="quote/kline/fundamentals/filings/options/capital_flow/tools_fallback",
    )
    global_data.set_defaults(handler=_command_global_data)

    evidence = subparsers.add_parser(
        "evidence",
        help="read evidence trust checks",
    )
    evidence_subparsers = evidence.add_subparsers(dest="evidence_command", required=True)
    lookahead = evidence_subparsers.add_parser(
        "lookahead-check",
        help="run the standing read-only lookahead trust check",
    )
    lookahead.add_argument("--as-of", help="optional YYYY-MM-DD evidence date")
    lookahead.add_argument("--demo", action="store_true", help="mark this check as running against demo/sample data")
    lookahead.set_defaults(handler=_command_evidence_lookahead_check)

    action = subparsers.add_parser(
        "action",
        help="inspect or execute a registered action",
    )
    action.add_argument("name")
    action.add_argument("--payload-json", required=True)
    action.add_argument("--confirm", action="store_true", help="execute the action")
    action.set_defaults(handler=_command_action)

    actions = subparsers.add_parser(
        "actions",
        help="list registered local agent actions",
    )
    actions.set_defaults(handler=_command_actions)


    tools = subparsers.add_parser(
        "tools",
        help="list retained backend tool classifications and boundaries",
    )
    tools.add_argument(
        "--category",
        choices=["stable", "maintenance", "evidence", "attic"],
        help="optional M49 tool category filter",
    )
    tools.set_defaults(handler=_command_tools)

    premarket = subparsers.add_parser(
        "premarket",
        aliases=["盘前"],
        help="盘前一句话工作流：同步前检查与入口说明（premarket 与 盘前 等价，双别名同一命令）",
    )
    premarket.add_argument("--symbol", help="optional focus symbol")
    premarket.set_defaults(handler=_command_premarket)

    intraday = subparsers.add_parser(
        "intraday",
        aliases=["盘中"],
        help="盘中一句话工作流：只读本地缓存的快速个股入口（intraday 与 盘中 等价，双别名同一命令）",
    )
    intraday.add_argument("--symbol", help="optional focus symbol")
    intraday.set_defaults(handler=_command_intraday)

    postmarket = subparsers.add_parser(
        "postmarket",
        aliases=["盘后"],
        help="盘后一句话工作流：全市场信号与复盘报告入口（postmarket 与 盘后 等价，双别名同一命令）",
    )
    postmarket.add_argument("--symbol", help="optional focus symbol")
    postmarket.set_defaults(handler=_command_postmarket)

    weekend = subparsers.add_parser(
        "weekend",
        aliases=["周末"],
        help="周末一句话工作流：长期标签刷新、周度反思与复盘报告入口（weekend 与 周末 等价，双别名同一命令）",
    )
    weekend.add_argument("--symbol", help="optional focus symbol")
    weekend.set_defaults(handler=_command_weekend)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    normalized_argv = _normalize_global_options(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(normalized_argv)
    try:
        _emit(args.handler(args), pretty=args.pretty)
    except AgentSecurityError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
