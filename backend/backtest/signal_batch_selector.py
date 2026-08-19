"""Canonical signal-batch selectors for replay consumers."""
from __future__ import annotations

import sqlite3
from typing import Any


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def select_complete_signal_batches(
    con: sqlite3.Connection,
    *,
    universe_symbols: set[str],
    start: str,
    end: str,
) -> dict[str, Any]:
    """Select one latest complete signal batch per data day.

    A complete batch must contain every symbol in the supplied universe for the
    same close-confirmed data day and the same batch key.  Partial, repair, or
    rerun batches are visible in health counters but are never merged.
    """
    symbols = sorted(universe_symbols)
    if not symbols:
        return {
            "schema_version": "signal_batch_selector.v1",
            "selected_batches": [],
            "raw_rows": 0,
            "raw_observation_days": 0,
            "selected_complete_batch_days": 0,
            "days_without_complete_batch": 0,
            "non_selected_batch_rows_removed": 0,
            "required_symbols_per_batch": 0,
        }
    placeholders = _placeholders(len(symbols))
    params = (*symbols, start, end)
    raw_count = int(con.execute(
        f"""
        SELECT COUNT(*) FROM signals
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({placeholders})
          AND substr(COALESCE(data_timestamp, date), 1, 10) BETWEEN ? AND ?
        """,
        params,
    ).fetchone()[0])
    raw_days = int(con.execute(
        f"""
        SELECT COUNT(DISTINCT substr(COALESCE(data_timestamp, date), 1, 10))
        FROM signals
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({placeholders})
          AND substr(COALESCE(data_timestamp, date), 1, 10) BETWEEN ? AND ?
        """,
        params,
    ).fetchone()[0])
    rows = con.execute(
        f"""
        WITH scoped AS (
            SELECT id, symbol, date AS batch_key,
                   substr(COALESCE(data_timestamp, date), 1, 10) AS signal_date
            FROM signals
            WHERE COALESCE(market, 'CN') = 'CN'
              AND symbol IN ({placeholders})
              AND substr(COALESCE(data_timestamp, date), 1, 10) BETWEEN ? AND ?
        ),
        complete_batches AS (
            SELECT signal_date, batch_key, MAX(id) AS batch_max_id,
                   COUNT(DISTINCT symbol) AS symbols
            FROM scoped
            GROUP BY signal_date, batch_key
            HAVING COUNT(DISTINCT symbol) = ?
        ),
        selected_batches AS (
            SELECT signal_date, batch_key, batch_max_id, symbols,
                   ROW_NUMBER() OVER (
                       PARTITION BY signal_date ORDER BY batch_max_id DESC, batch_key DESC
                   ) AS batch_rank
            FROM complete_batches
        )
        SELECT signal_date, batch_key, batch_max_id, symbols
        FROM selected_batches
        WHERE batch_rank = 1
        ORDER BY signal_date
        """,
        (*params, len(symbols)),
    ).fetchall()
    selected = [
        {
            "signal_date": str(row["signal_date"] if isinstance(row, sqlite3.Row) else row[0]),
            "batch_key": str(row["batch_key"] if isinstance(row, sqlite3.Row) else row[1]),
            "batch_max_id": int(row["batch_max_id"] if isinstance(row, sqlite3.Row) else row[2]),
            "symbols": int(row["symbols"] if isinstance(row, sqlite3.Row) else row[3]),
        }
        for row in rows
    ]
    selected_days = len(selected)
    return {
        "schema_version": "signal_batch_selector.v1",
        "selected_batches": selected,
        "raw_rows": raw_count,
        "raw_observation_days": raw_days,
        "selected_complete_batch_days": selected_days,
        "days_without_complete_batch": raw_days - selected_days,
        "non_selected_batch_rows_removed": raw_count - selected_days * len(symbols),
        "required_symbols_per_batch": len(symbols),
    }
