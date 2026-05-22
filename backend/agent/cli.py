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
from backend.data.database import SessionLocal, init_db


def _json_default(value: Any) -> str:
    return str(value)


def _emit(payload: dict, *, pretty: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, default=_json_default))


def _with_db(fn: Callable[[Any], dict], *, ensure_schema: bool = False) -> dict:
    if ensure_schema:
        init_db()
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


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

    return _with_db(_health)


def _command_project_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_db(lambda db: stock_sage_context(db, symbol=args.symbol))


def _command_memory_snapshot(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_db(stock_sage_memory_snapshot)


def _command_memory_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_db(lambda db: stock_sage_memory_context(
        db,
        symbol=args.symbol,
        query=args.query,
        task_type=args.task_type,
        limit=args.limit,
    ))


def _command_stock_context(args: argparse.Namespace) -> dict:
    _read_guard(args)
    return _with_db(lambda db: stock_sage_stock_context(db, args.symbol))


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
