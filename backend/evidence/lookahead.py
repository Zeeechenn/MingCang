"""Productized read-only lookahead checks for evidence trust."""
from __future__ import annotations

from contextlib import closing
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.config import settings, sqlite_path_from_url
from backend.tools.m46_5_lookahead_one_time_audit import build_audit

LOOKAHEAD_CHECK_SCHEMA = "m47_lookahead_standing_check.v1"


def _readonly_sqlite_url(database_url: str) -> str:
    if "mode=ro" in database_url or "uri=true" in database_url:
        return database_url
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is None:
        return database_url
    return f"sqlite:///file:{sqlite_path}?mode=ro&immutable=1&uri=true"


def run_lookahead_check(
    db,
    *,
    as_of: str | None = None,
    demo_mode: bool = False,
) -> dict[str, Any]:
    """Run the M46.5 audit as a stable, non-promoting evidence gate."""
    audit = build_audit(db, as_of=as_of)
    status = audit.get("status", "blocked")
    recommended_next_actions = []
    if status == "blocked":
        recommended_next_actions.append(
            "Freeze the related promotion path and review blocked checks before continuing."
        )
    elif status == "warning":
        recommended_next_actions.append(
            "Disclose warnings in UI/export surfaces; do not change official signals automatically."
        )
    else:
        recommended_next_actions.append("No lookahead blockers or warnings were detected.")

    return {
        **audit,
        "schema_version": LOOKAHEAD_CHECK_SCHEMA,
        "source_audit_schema_version": audit.get("schema_version"),
        "milestone": "M47",
        "purpose": "standing read-only lookahead and evidence trust check",
        "run_mode": "standing_read_only_check",
        "productized_cli": True,
        "standing_check": True,
        "demo_mode": bool(demo_mode),
        "ok": status != "blocked",
        "promotion_impact": "none",
        "read_contract": {
            "writes_db": False,
            "calls_llm_or_api": False,
            "warning_signal_impact": "none",
            "blocked_auto_promotion": False,
        },
        "recommended_next_actions": recommended_next_actions,
    }


def run_lookahead_check_for_database_url(
    *,
    database_url: str | None = None,
    as_of: str | None = None,
    demo_mode: bool = False,
) -> dict[str, Any]:
    """Open the configured database read-only and run the standing check."""
    engine = create_engine(_readonly_sqlite_url(database_url or settings.database_url))
    session_factory = sessionmaker(bind=engine)
    with closing(session_factory()) as db:
        db.execute(text("SELECT 1"))
        return run_lookahead_check(db, as_of=as_of, demo_mode=demo_mode)
