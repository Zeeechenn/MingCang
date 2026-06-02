"""Command-line bridge for local StockSage agent shells."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from backend.agent.context import (
    stock_sage_context,
    stock_sage_memory_context,
    stock_sage_memory_snapshot,
    stock_sage_stock_context,
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


def _command_health(args: argparse.Namespace) -> dict:
    _read_guard(args)

    def _health(db):
        context = stock_sage_context(db)
        return {
            "ok": True,
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
        lambda: _with_db(lambda db: stock_sage_context(db, symbol=args.symbol))
    )


def _command_memory_snapshot(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(lambda: _with_db(stock_sage_memory_snapshot))


def _command_memory_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_read_only_memory_usage(
        lambda: _with_db(lambda db: stock_sage_memory_context(
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
        lambda: _with_db(lambda db: stock_sage_stock_context(db, args.symbol))
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


def _workflow_payload(args: argparse.Namespace, phase: str) -> dict:
    _read_guard(args)
    workflows = {
        "premarket": {
            "label": "盘前自检",
            "one_sentence": "盘前同步行情、个股新闻和沪深300指数，确认数据覆盖后再进入盘中观察。",
            "reused_entrypoints": [
                "backend.scheduler.job_premarket",
                "GET /api/system/data-coverage",
                "GET /api/system/health",
            ],
            "side_effects_if_executed": ["writes prices/news/index_prices", "may call market/news providers"],
            "operator_command": "python3 -m backend.agent.cli premarket --pretty",
        },
        "intraday": {
            "label": "盘中快速个股",
            "one_sentence": "盘中只读本地缓存和SQLite，不触发远端网络，快速读取单股上下文或止损观察。",
            "reused_entrypoints": [
                "python3 -m backend.agent.cli stock-context <symbol>",
                "backend.scheduler.job_stoploss_check",
                "GET /api/system/health",
            ],
            "side_effects_if_executed": ["none in default CLI context read", "Bark alert only in scheduler stoploss job"],
            "operator_command": "python3 -m backend.agent.cli intraday --symbol 300308 --pretty",
        },
        "postmarket": {
            "label": "盘后复盘",
            "one_sentence": "盘后跑全市场信号入库后，导出带证据与声明的复盘报告。",
            "reused_entrypoints": [
                "backend.scheduler.job_postmarket",
                "GET /api/export/postmarket-review.html",
                "GET /api/export/postmarket-review.html?format=word",
            ],
            "side_effects_if_executed": ["writes signals/reviews/memory", "may call news/LLM providers", "may send Bark alerts"],
            "operator_command": "python3 -m backend.agent.cli postmarket --pretty",
        },
    }
    payload = workflows[phase]
    side_effects_if_executed = payload["side_effects_if_executed"]
    return {
        "ok": True,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockSage local agent CLI bridge")
    parser.add_argument("--api-key", help="StockSage remote agent API key")
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

    premarket = subparsers.add_parser(
        "premarket",
        aliases=["盘前"],
        help="盘前一句话工作流：同步前检查与入口说明",
    )
    premarket.add_argument("--symbol", help="optional focus symbol")
    premarket.set_defaults(handler=_command_premarket)

    intraday = subparsers.add_parser(
        "intraday",
        aliases=["盘中"],
        help="盘中一句话工作流：只读本地缓存的快速个股入口",
    )
    intraday.add_argument("--symbol", help="optional focus symbol")
    intraday.set_defaults(handler=_command_intraday)

    postmarket = subparsers.add_parser(
        "postmarket",
        aliases=["盘后"],
        help="盘后一句话工作流：全市场信号与复盘报告入口",
    )
    postmarket.add_argument("--symbol", help="optional focus symbol")
    postmarket.set_defaults(handler=_command_postmarket)

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
