"""Unified project action registry for chat and future agent tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException
from jsonschema import ValidationError, validate

from backend.agent.security import agent_mode

Handler = Callable[[dict, object], dict]


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    input_schema: dict
    risk_level: str
    requires_confirmation: bool
    allowed_modes: tuple[str, ...]
    handler: Handler
    schema_version: int = 1


def _object_schema(
    required: list[str],
    properties: dict,
    *,
    additional_properties: bool = False,
) -> dict:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": additional_properties,
    }


RUNTIME_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "paper_trading_profile": {"type": "string", "enum": ["auto", "test1_legacy_qlib", "new_framework"]},
        "signal_profile": {"type": "string", "enum": ["auto", "test1_legacy_qlib", "new_framework"]},
        "new_framework_entry_threshold": {"type": "number"},
        "test1_entry_threshold": {"type": "number"},
        "weight_quant": {"type": "number", "minimum": 0, "maximum": 1},
        "weight_technical": {"type": "number", "minimum": 0, "maximum": 1},
        "weight_sentiment": {"type": "number", "minimum": 0, "maximum": 1},
        "adx_filter_enabled": {"type": "boolean"},
        "regime_filter_enabled": {"type": "boolean"},
        "multi_agent_enabled": {"type": "boolean"},
        "risk_manager_enabled": {"type": "boolean"},
        "director_min_confidence": {"type": "number"},
        "long_term_team_enabled": {"type": "boolean"},
        "trailing_stop_enabled": {"type": "boolean"},
        "take_profit_exit_enabled": {"type": "boolean"},
        "max_position_per_stock": {"type": "number", "minimum": 0, "maximum": 1},
        "max_position_per_sector": {"type": "number", "minimum": 0, "maximum": 1},
        "max_total_equity_pct": {"type": "number", "minimum": 0, "maximum": 1},
        "financial_backfill_years": {"type": "integer", "minimum": 1},
        "tavily_supplement_threshold": {"type": "integer", "minimum": 0},
        "anspire_news_days": {"type": "integer", "minimum": 1},
        "anspire_news_max_results": {"type": "integer", "minimum": 1},
        "anspire_news_max_add": {"type": "integer", "minimum": 0},
        "anspire_news_min_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "schedule_daily_review_time": {"type": "string"},
        "schedule_longterm_monday_dow": {"type": "string"},
        "schedule_longterm_monday_time": {"type": "string"},
        "schedule_longterm_friday_dow": {"type": "string"},
        "schedule_longterm_friday_time": {"type": "string"},
    },
    "additionalProperties": False,
    "minProperties": 1,
}


def _watchlist_add(payload: dict, db) -> dict:
    from backend.data.database import Stock

    symbol = payload["symbol"]
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock:
        stock.active = True
        stock.name = payload.get("name") or stock.name
        stock.market = payload.get("market") or stock.market
    else:
        db.add(Stock(
            symbol=symbol,
            name=payload.get("name") or symbol,
            market=payload.get("market") or "CN",
            active=True,
        ))
    db.commit()
    return {"symbol": symbol, "active": True}


def _watchlist_remove(payload: dict, db) -> dict:
    from backend.data.database import Stock

    symbol = payload["symbol"]
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock:
        stock.active = False
        db.commit()
    return {"symbol": symbol, "active": False}


def _position_add(payload: dict, db) -> dict:
    from backend.api.routes.positions import create_position
    from backend.api.schemas import PositionCreate

    if not payload.get("quantity") or not payload.get("avg_cost"):
        raise HTTPException(400, "添加持仓需要数量和成本价")
    created = create_position(PositionCreate(**payload), db=db)
    return created.model_dump()


def _config_update(payload: dict, db) -> dict:
    from backend.api.routes.system import update_runtime_config

    updated = update_runtime_config(payload)
    return {"updated": payload, "active_profile": updated.get("active_profile")}


def _review_daily_ensure(payload: dict, db) -> dict:
    from backend.api.routes.reviews import ensure_daily_review

    return ensure_daily_review(db=db)


def _review_long_term_ensure(payload: dict, db) -> dict:
    from backend.api.routes.reviews import ensure_long_term_review

    return ensure_long_term_review(db=db)


def _memory_write(payload: dict, db) -> dict:
    from backend.memory.ai_memory import remember

    persisted = remember(
        db,
        payload["key"],
        payload["value"],
        category=payload.get("category"),
        scope=payload.get("scope", "global"),
        ttl_days=payload.get("ttl_days"),
        force=True,
    )
    stock_memory_id = None
    if persisted and payload.get("category") in {"preference", "rule", "risk"}:
        from backend.memory.stock_memory import create_stock_memory
        memory_type = "user_preference" if payload.get("category") in {"preference", "rule"} else "risk"
        stock_memory = create_stock_memory(
            db,
            symbol=payload.get("symbol"),
            memory_type=memory_type,
            summary=payload["value"],
            evidence={"ai_memory_key": payload["key"], "category": payload.get("category")},
            source_type="chat_confirmed",
            source_ref=payload["key"],
            importance=4,
            confidence=0.8,
        )
        stock_memory_id = stock_memory["id"]
    return {
        "persisted": persisted,
        "key": payload["key"],
        "scope": payload.get("scope", "global"),
        "stock_memory_id": stock_memory_id,
    }


_ACTIONS: dict[str, ActionDefinition] = {
    "watchlist.add": ActionDefinition(
        name="watchlist.add",
        input_schema=_object_schema(["symbol"], {
            "symbol": {"type": "string"},
            "name": {"type": "string"},
            "market": {"type": "string", "enum": ["CN", "US"]},
        }),
        risk_level="medium",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_watchlist_add,
    ),
    "watchlist.remove": ActionDefinition(
        name="watchlist.remove",
        input_schema=_object_schema(["symbol"], {"symbol": {"type": "string"}}),
        risk_level="medium",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_watchlist_remove,
    ),
    "position.add": ActionDefinition(
        name="position.add",
        input_schema=_object_schema(["symbol", "quantity", "avg_cost"], {
            "symbol": {"type": "string", "minLength": 1},
            "name": {"type": "string"},
            "market": {"type": "string", "enum": ["CN", "US"]},
            "quantity": {"type": "number", "exclusiveMinimum": 0},
            "avg_cost": {"type": "number", "exclusiveMinimum": 0},
            "opened_at": {"type": "string", "format": "date"},
            "stop_loss": {"type": "number", "exclusiveMinimum": 0},
            "take_profit": {"type": "number", "exclusiveMinimum": 0},
            "note": {"type": "string"},
        }),
        risk_level="high",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_position_add,
    ),
    "config.update": ActionDefinition(
        name="config.update",
        input_schema=RUNTIME_CONFIG_SCHEMA,
        risk_level="high",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_config_update,
    ),
    "review.daily.ensure": ActionDefinition(
        name="review.daily.ensure",
        input_schema=_object_schema([], {}),
        risk_level="low",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_review_daily_ensure,
    ),
    "review.long_term.ensure": ActionDefinition(
        name="review.long_term.ensure",
        input_schema=_object_schema([], {}),
        risk_level="low",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_review_long_term_ensure,
    ),
    "memory.write": ActionDefinition(
        name="memory.write",
        input_schema=_object_schema(["key", "value"], {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "category": {"type": ["string", "null"]},
            "scope": {"type": "string"},
            "symbol": {"type": ["string", "null"]},
            "ttl_days": {"type": ["integer", "null"]},
        }),
        risk_level="high",
        requires_confirmation=True,
        allowed_modes=("local", "remote"),
        handler=_memory_write,
    ),
}


def get_action_definition(name: str) -> ActionDefinition:
    try:
        return _ACTIONS[name]
    except KeyError as exc:
        raise HTTPException(400, f"unsupported action: {name}") from exc


def action_metadata(name: str) -> dict:
    definition = get_action_definition(name)
    return {
        "risk_level": definition.risk_level,
        "requires_confirmation": definition.requires_confirmation,
        "schema_version": definition.schema_version,
    }


def execute_registered_action(name: str, payload: dict, db) -> dict:
    definition = get_action_definition(name)
    mode = agent_mode()
    if mode not in definition.allowed_modes:
        raise HTTPException(403, f"action {name} is not allowed in {mode} mode")
    try:
        validate(instance=payload, schema=definition.input_schema)
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.path)
        detail = f"invalid payload for {name}: {path + ': ' if path else ''}{exc.message}"
        raise HTTPException(400, detail) from exc
    return definition.handler(payload, db)
