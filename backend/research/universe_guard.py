"""
M38 Dynamic Universe / Survivorship Guard — pure storage layer.

BACKTEST / FORWARD-VALIDATION ONLY.
This module is NOT imported by backend/scheduler.py, backend/decision/aggregator.py,
or any production signal/daily-batch path.  All write paths are guarded by
settings.universe_guard_enabled (mirrors the stress_test_enabled pattern).

Exposes:
  compute_universe_hash  — pure function, no Session needed
  snapshot_universe      — idempotent insert into universe_snapshots
  get_snapshot           — return single row dict by id
  get_snapshot_for_cutoff — nearest snapshot with cutoff_date <= requested_date
  list_snapshots         — ordered by cutoff_date DESC
  provenance_completeness_report — queries real Price / FinancialMetric columns
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from backend.config import settings
from backend.memory.audit_log import audit_write

# ── helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _row_to_dict(row) -> dict:
    """Convert a UniverseSnapshot ORM row to a plain dict."""
    symbols: list[str] = json.loads(row.symbols_json) if row.symbols_json else []
    prov = json.loads(row.provenance_completeness_json) if row.provenance_completeness_json else None
    return {
        "id": row.id,
        "universe_hash": row.universe_hash,
        "cutoff_date": row.cutoff_date,
        "market_filter": row.market_filter,
        "symbols": symbols,
        "n_symbols": row.n_symbols,
        "provenance_completeness": prov,
        "context": row.context,
        "created_at": _iso(row.created_at),
    }


# ── core hash function ────────────────────────────────────────────────────────

def compute_universe_hash(symbols: list[str] | set[str]) -> str:
    """Return a deterministic SHA-256 hex digest of the sorted symbol membership.

    The algorithm is identical to _universe_hash() in
    backend/tools/m27_top_decile_forward_shadow.py — reimplemented here as a
    standalone function to avoid circular imports from a tools module.

    Same inputs always produce the same 64-char lowercase hex string.
    """
    canonical = json.dumps(
        sorted(list(symbols)),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── write path ────────────────────────────────────────────────────────────────

def snapshot_universe(
    db,
    *,
    symbols: list[str],
    cutoff_date: str,
    market_filter: str = "ALL",
    context: str | None = None,
) -> dict:
    """Idempotent insert of a universe snapshot into universe_snapshots.

    Returns the row dict (existing or newly created).
    Returns an empty dict when universe_guard_enabled is False.

    The (cutoff_date, market_filter, universe_hash) triple is unique —
    a second call with the same membership on the same date is a no-op
    returning the existing row.
    """
    if not settings.universe_guard_enabled:
        return {}

    from backend.data.database import (
        UniverseSnapshot,  # local import — avoids circular at module load
    )

    universe_hash = compute_universe_hash(symbols)
    sorted_symbols = sorted(list(symbols))

    # Check for existing row (idempotency)
    existing = (
        db.query(UniverseSnapshot)
        .filter(
            UniverseSnapshot.cutoff_date == cutoff_date,
            UniverseSnapshot.market_filter == market_filter,
            UniverseSnapshot.universe_hash == universe_hash,
        )
        .first()
    )
    if existing is not None:
        return _row_to_dict(existing)

    # Compute provenance completeness at snapshot time
    prov = provenance_completeness_report(db, symbols=sorted_symbols)

    row = UniverseSnapshot(
        universe_hash=universe_hash,
        cutoff_date=cutoff_date,
        market_filter=market_filter,
        symbols_json=json.dumps(sorted_symbols, ensure_ascii=True, separators=(",", ":")),
        n_symbols=len(sorted_symbols),
        provenance_completeness_json=json.dumps(prov),
        context=context,
        created_at=_utc_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    audit_write(
        db,
        "universe_snapshot_created",
        json.dumps({
            "universe_hash": universe_hash,
            "cutoff_date": cutoff_date,
            "market_filter": market_filter,
            "n_symbols": len(sorted_symbols),
            "context": context,
        }),
        related_symbol=None,
        related_scope="universe_guard",
    )

    return _row_to_dict(row)


# ── read paths ────────────────────────────────────────────────────────────────

def get_snapshot(db, snapshot_id: int) -> dict | None:
    """Return a single UniverseSnapshot row dict, or None if not found."""
    from backend.data.database import UniverseSnapshot

    row = db.query(UniverseSnapshot).filter(UniverseSnapshot.id == snapshot_id).first()
    return _row_to_dict(row) if row is not None else None


def get_snapshot_for_cutoff(
    db,
    cutoff_date: str,
    market_filter: str = "ALL",
) -> dict | None:
    """Return the most-recent snapshot with cutoff_date <= requested_date for the given market_filter.

    This is the survivorship-bias-safe lookup: a backtest at 2023-06-01
    retrieves the snapshot taken on or before that date, not today's active list.
    Returns None when no suitable snapshot exists.
    """
    from backend.data.database import UniverseSnapshot

    row = (
        db.query(UniverseSnapshot)
        .filter(
            UniverseSnapshot.market_filter == market_filter,
            UniverseSnapshot.cutoff_date <= cutoff_date,
        )
        .order_by(UniverseSnapshot.cutoff_date.desc(), UniverseSnapshot.id.desc())
        .first()
    )
    return _row_to_dict(row) if row is not None else None


def list_snapshots(
    db,
    *,
    market_filter: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return snapshots ordered by cutoff_date DESC (newest first).

    Optionally filter by market_filter.
    """
    from backend.data.database import UniverseSnapshot

    q = db.query(UniverseSnapshot)
    if market_filter is not None:
        q = q.filter(UniverseSnapshot.market_filter == market_filter)
    rows = q.order_by(UniverseSnapshot.cutoff_date.desc(), UniverseSnapshot.id.desc()).limit(limit).all()
    return [_row_to_dict(r) for r in rows]


# ── provenance completeness report ───────────────────────────────────────────

def provenance_completeness_report(
    db,
    *,
    symbols: list[str] | None = None,
) -> dict:
    """Measure provenance completeness from real DB columns.

    Queries Price.source, Price.fetched_at, Price.adjustment, and
    FinancialMetric.fetched_at — the only provenance columns that exist in
    the current schema.  FinancialMetric has no 'source' or 'adjustment'
    columns; the report makes this gap explicit via financial_source_available=False.

    Returns a dict with keys:
      price_source_pct          float [0, 1]
      price_fetched_at_pct      float [0, 1]
      price_adjustment_pct      float [0, 1]
      financial_fetched_at_pct  float [0, 1]
      financial_source_available  bool (always False — column does not exist)
      price_rows_total          int
      financial_rows_total      int
      checked_at                ISO-8601 str (UTC)
    """
    from backend.data.database import FinancialMetric, Price

    # ── Price provenance ──────────────────────────────────────────────────────
    price_q = db.query(Price)
    if symbols:
        price_q = price_q.filter(Price.symbol.in_(symbols))

    price_total: int = price_q.count()

    if price_total > 0:
        # Count non-NULL values for each provenance column
        source_count: int = price_q.filter(Price.source.isnot(None)).count()
        fetched_at_count: int = price_q.filter(Price.fetched_at.isnot(None)).count()
        adjustment_count: int = price_q.filter(Price.adjustment.isnot(None)).count()

        price_source_pct = source_count / price_total
        price_fetched_at_pct = fetched_at_count / price_total
        price_adjustment_pct = adjustment_count / price_total
    else:
        price_source_pct = 0.0
        price_fetched_at_pct = 0.0
        price_adjustment_pct = 0.0

    # ── FinancialMetric provenance ────────────────────────────────────────────
    fm_q = db.query(FinancialMetric)
    if symbols:
        fm_q = fm_q.filter(FinancialMetric.symbol.in_(symbols))

    fm_total: int = fm_q.count()

    if fm_total > 0:
        fm_fetched_at_count: int = fm_q.filter(FinancialMetric.fetched_at.isnot(None)).count()
        financial_fetched_at_pct = fm_fetched_at_count / fm_total
    else:
        financial_fetched_at_pct = 0.0

    return {
        "price_source_pct": round(price_source_pct, 6),
        "price_fetched_at_pct": round(price_fetched_at_pct, 6),
        "price_adjustment_pct": round(price_adjustment_pct, 6),
        "financial_fetched_at_pct": round(financial_fetched_at_pct, 6),
        "financial_source_available": False,   # FinancialMetric has no 'source' column
        "price_rows_total": price_total,
        "financial_rows_total": fm_total,
        "checked_at": _utc_now().isoformat(timespec="seconds"),
    }
