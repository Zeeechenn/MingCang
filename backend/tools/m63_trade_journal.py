"""D8 trade-level review journal for M63 postmarket."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def ensure_trade_journal(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            entry_price REAL,
            entry_snapshot_json TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            exit_reason TEXT,
            outcome_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, opened_at)
        )
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_trade_journal_closed_at ON trade_journal(closed_at)"
    )


def _latest_signal(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "signals"):
        return None
    cols = _columns(con, "signals")
    if not {"symbol", "date"} <= cols:
        return None
    select_cols = [column for column in ("date", "recommendation", "confidence", "composite_score", "stop_loss", "take_profit") if column in cols]
    row = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM signals
        WHERE symbol = ? AND date(date) <= date(?)
        ORDER BY date(date) DESC, id DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return dict(row) if row else None


def _latest_long_term_label(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "long_term_labels"):
        return None
    cols = _columns(con, "long_term_labels")
    if not {"symbol", "label"} <= cols:
        return None
    order_col = "date" if "date" in cols else ("created_at" if "created_at" in cols else None)
    if order_col is None:
        return None
    select_cols = [column for column in ("label", "quality", "score", "expires_at", order_col) if column in cols]
    row = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM long_term_labels
        WHERE symbol = ?
          AND date({order_col}) <= date(?)
          AND (expires_at IS NULL OR date(expires_at) >= date(?))
        ORDER BY date({order_col}) DESC, id DESC
        LIMIT 1
        """,
        (symbol, as_of, as_of),
    ).fetchone()
    return dict(row) if row else None


def _entry_card(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    try:
        module = importlib.import_module("backend.tools.m59_entry_card")
        return module.build_entry_card(symbol, as_of, con)
    except Exception:
        return None


def _entry_readiness(con: sqlite3.Connection, symbol: str, as_of: str, entry_card: dict[str, Any] | None) -> dict[str, Any] | None:
    try:
        module = importlib.import_module("backend.tools.m59_readiness")
    except Exception:
        return None
    try:
        return module.build_readiness(con, symbol=symbol, as_of=as_of, entry_card=entry_card or {})
    except Exception:
        return None


def _basis_summary(snapshot: dict[str, Any]) -> str:
    signal = snapshot.get("trigger_state", {}).get("signal") or {}
    label = snapshot.get("long_term_label") or {}
    readiness = snapshot.get("entry_readiness") or {}
    parts = []
    if signal.get("recommendation"):
        parts.append(f"信号={signal['recommendation']}")
    if label.get("label"):
        parts.append(f"长期标签={label['label']}")
    if readiness.get("score") is not None:
        band = readiness.get("band") or {}
        parts.append(f"准备度={readiness.get('score')}/{band.get('label') or band.get('range') or '-'}")
    return "; ".join(parts) or "入场快照:无可用摘要"


def _entry_snapshot(con: sqlite3.Connection, pos: sqlite3.Row, as_of: str) -> dict[str, Any]:
    symbol = str(pos["symbol"])
    entry_card = _entry_card(con, symbol, as_of)
    snapshot = {
        "symbol": symbol,
        "opened_at": str(pos["opened_at"])[:10],
        "entry_price": pos["avg_cost"],
        "trigger_state": {"signal": _latest_signal(con, symbol, as_of)},
        "entry_card": entry_card,
        "long_term_label": _latest_long_term_label(con, symbol, as_of),
    }
    readiness = _entry_readiness(con, symbol, as_of, entry_card)
    if readiness is not None:
        snapshot["entry_readiness"] = readiness
    snapshot["entry_basis_summary"] = _basis_summary(snapshot)
    return snapshot


def _position_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    if not _table_exists(con, "positions"):
        return []
    cols = _columns(con, "positions")
    if not {"symbol", "opened_at"} <= cols:
        return []
    select_cols = [
        column
        for column in (
            "symbol",
            "opened_at",
            "avg_cost",
            "status",
            "closed_at",
            "close_price",
            "realized_pnl_pct",
            "note",
            "stop_loss",
        )
        if column in cols
    ]
    return con.execute(f"SELECT {', '.join(select_cols)} FROM positions ORDER BY opened_at, symbol").fetchall()


def _price_touched_stop(con: sqlite3.Connection, symbol: str, opened_at: str, closed_at: str, stop_loss: Any) -> bool:
    if stop_loss is None or not _table_exists(con, "prices"):
        return False
    cols = _columns(con, "prices")
    if not {"symbol", "date"} <= cols or not ({"low"} & cols or {"close"} & cols):
        return False
    price_col = "low" if "low" in cols else "close"
    row = con.execute(
        f"""
        SELECT 1
        FROM prices
        WHERE symbol = ?
          AND date(date) >= date(?)
          AND date(date) <= date(?)
          AND {price_col} IS NOT NULL
          AND {price_col} <= ?
        LIMIT 1
        """,
        (symbol, opened_at, closed_at, float(stop_loss)),
    ).fetchone()
    return row is not None


def _holding_days(opened_at: str, closed_at: str) -> int | None:
    try:
        return (date.fromisoformat(closed_at[:10]) - date.fromisoformat(opened_at[:10])).days
    except ValueError:
        return None


def _outcome(con: sqlite3.Connection, pos: sqlite3.Row, entry_price: float | None, exit_price: float | None) -> dict[str, Any]:
    opened_at = str(pos["opened_at"])[:10]
    closed_at = str(pos["closed_at"])[:10]
    return_pct = None
    if entry_price is not None and entry_price != 0 and exit_price is not None:
        return_pct = round((float(exit_price) / float(entry_price) - 1) * 100, 2)
    return {
        "return_pct": return_pct,
        "holding_days": _holding_days(opened_at, closed_at),
        "win": None if return_pct is None else return_pct > 0,
        "touched_stop_loss": _price_touched_stop(con, str(pos["symbol"]), opened_at, closed_at, pos["stop_loss"] if "stop_loss" in pos.keys() else None),
        "realized_pnl_pct": pos["realized_pnl_pct"] if "realized_pnl_pct" in pos.keys() else None,
    }


def sync_trade_journal(*, db_path: str | Path | None = None, as_of: str | None = None) -> dict[str, Any]:
    day = as_of or date.today().isoformat()
    opened = 0
    closed = 0
    with _connect(db_path) as con:
        ensure_trade_journal(con)
        for pos in _position_rows(con):
            symbol = str(pos["symbol"])
            opened_at = str(pos["opened_at"])[:10]
            if not opened_at:
                continue
            exists = con.execute(
                "SELECT 1 FROM trade_journal WHERE symbol = ? AND opened_at = ?",
                (symbol, opened_at),
            ).fetchone()
            if exists is None:
                snapshot = _entry_snapshot(con, pos, day)
                con.execute(
                    """
                    INSERT OR IGNORE INTO trade_journal(symbol, opened_at, entry_price, entry_snapshot_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        opened_at,
                        pos["avg_cost"] if "avg_cost" in pos.keys() else None,
                        json.dumps(snapshot, ensure_ascii=False, default=str),
                    ),
                )
                if con.execute("SELECT changes()").fetchone()[0]:
                    opened += 1

            status = str(pos["status"] if "status" in pos.keys() and pos["status"] is not None else "open")
            closed_at = str(pos["closed_at"])[:10] if "closed_at" in pos.keys() and pos["closed_at"] else None
            if status != "closed" or not closed_at or closed_at > day:
                continue
            journal = con.execute(
                "SELECT entry_price, closed_at FROM trade_journal WHERE symbol = ? AND opened_at = ?",
                (symbol, opened_at),
            ).fetchone()
            if journal is None or journal["closed_at"]:
                continue
            exit_price = pos["close_price"] if "close_price" in pos.keys() else None
            outcome = _outcome(con, pos, journal["entry_price"], exit_price)
            cur = con.execute(
                """
                UPDATE trade_journal
                SET closed_at = ?, exit_price = ?, exit_reason = ?, outcome_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE symbol = ? AND opened_at = ? AND closed_at IS NULL
                """,
                (
                    closed_at,
                    exit_price,
                    (pos["note"] if "note" in pos.keys() and pos["note"] else "closed_position"),
                    json.dumps(outcome, ensure_ascii=False, default=str),
                    symbol,
                    opened_at,
                ),
            )
            closed += cur.rowcount
        con.commit()
    return {"ok": True, "date": day, "opened": opened, "closed": closed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync M63 trade journal")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    print(json.dumps(sync_trade_journal(db_path=args.db, as_of=args.as_of), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
