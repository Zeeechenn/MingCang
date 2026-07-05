"""M60 thesis-condition compiler and deterministic evaluators.

Phase 1 is deliberately rule-only: compile the data-shaped parts of Chinese
validation/invalidation prose into JSON specs, and mark the rest as
``manual_review`` instead of pretending they are machine-observable.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path

CONDITION_TYPES = {"validation", "invalidation"}


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def ensure_specs_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS thesis_condition_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forward_thesis_id INTEGER NOT NULL,
            condition_type TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            compiled_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_thesis_condition_specs_thesis
        ON thesis_condition_specs(forward_thesis_id, condition_type)
        """
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _pct(raw: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", raw)
    return float(match.group(1)) if match else None


def _days(raw: str, default: int = 3) -> int:
    match = re.search(r"持续\s*([0-9]+)\s*[日天]", raw)
    return int(match.group(1)) if match else default


def _direction(raw: str) -> str:
    if any(word in raw for word in ("流出", "回调", "下跌", "跌", "走弱", "转弱")):
        return "down"
    return "up"


def _keyword_tail(raw: str) -> list[str]:
    quoted = re.findall(r"[“\"']([^”\"']+)[”\"']", raw)
    if quoted:
        return [item.strip() for item in quoted if item.strip()]
    marker = re.search(r"关键词[:：]?\s*([^，。；;]+)", raw)
    if marker:
        return [item.strip() for item in re.split(r"[,，/、\s]+", marker.group(1)) if item.strip()]
    candidates = [
        word
        for word in ("公告", "研报", "解禁", "订单", "合同", "中标", "减持", "监管", "评级", "业绩")
        if word in raw
    ]
    return candidates


def compile_condition(raw_text: str, *, condition_type: str) -> dict[str, Any]:
    if condition_type not in CONDITION_TYPES:
        raise ValueError(f"invalid condition_type: {condition_type}")
    raw = str(raw_text or "").strip()
    pct = _pct(raw)

    if "海外" in raw and pct is not None:
        return {
            "kind": "overseas_pct_move",
            "params": {"threshold_pct": pct, "direction": _direction(raw), "field": "chg_pct_1d"},
            "raw_text": raw,
        }

    if pct is not None and any(word in raw for word in ("回调", "涨跌", "上涨", "下跌", "涨", "跌")):
        return {
            "kind": "price_pct_move",
            "params": {"threshold_pct": pct, "direction": _direction(raw), "window": "1d"},
            "raw_text": raw,
        }

    if "主力净" in raw and any(word in raw for word in ("流入", "流出")):
        return {
            "kind": "fund_flow_streak",
            "params": {"days": _days(raw), "direction": _direction(raw), "field": "main_net"},
            "raw_text": raw,
        }

    if any(word in raw for word in ("公告", "研报", "解禁")) and ("关键词" in raw or _keyword_tail(raw)):
        tables = []
        if "公告" in raw:
            tables.append("announcements")
        if "研报" in raw:
            tables.append("research_reports")
        if "解禁" in raw:
            tables.append("corporate_events")
        return {
            "kind": "event_keyword",
            "params": {"tables": tables or ["announcements", "research_reports", "corporate_events"], "keywords": _keyword_tail(raw), "lookback_days": 5},
            "raw_text": raw,
        }

    return {
        "kind": "manual_review",
        "params": {"reason": "unmatched_rule_template"},
        "raw_text": raw,
    }


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    return parsed if isinstance(parsed, list) else [parsed]


def compile_forward_thesis_conditions(
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    with _connect(resolved_db) as con:
        ensure_specs_table(con)
        if not _table_exists(con, "forward_theses"):
            return {"forward_theses": 0, "total_conditions": 0, "compiled_conditions": 0, "manual_review_conditions": 0}
        rows = con.execute(
            """
            SELECT id, invalidation_conditions_json, follow_up_metrics_json
            FROM forward_theses
            WHERE symbol IS NULL
              AND statement LIKE '[theme:%'
              AND status IN ('active', 'watch', 'draft')
            ORDER BY id
            """
        ).fetchall()
        con.execute("DELETE FROM thesis_condition_specs")
        now = _utc_now_iso()
        total = compiled = manual = 0
        for row in rows:
            for condition_type, values in (
                ("validation", _json_list(row["follow_up_metrics_json"])),
                ("invalidation", _json_list(row["invalidation_conditions_json"])),
            ):
                for raw in values:
                    total += 1
                    spec = compile_condition(str(raw), condition_type=condition_type)
                    compiled_by = "manual" if spec["kind"] == "manual_review" else "rule"
                    if compiled_by == "manual":
                        manual += 1
                    else:
                        compiled += 1
                    con.execute(
                        """
                        INSERT INTO thesis_condition_specs(
                            forward_thesis_id, condition_type, spec_json, compiled_by, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row["id"], condition_type, json.dumps(spec, ensure_ascii=False), compiled_by, now),
                    )
        con.commit()
    return {
        "forward_theses": len(rows),
        "total_conditions": total,
        "compiled_conditions": compiled,
        "manual_review_conditions": manual,
        "coverage_pct": round((compiled / total * 100.0), 2) if total else 0.0,
    }


def evaluate_condition_spec(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    kind = spec.get("kind")
    params = spec.get("params") or {}
    if kind == "price_pct_move":
        return _eval_price_pct_move(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "fund_flow_streak":
        return _eval_fund_flow_streak(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "event_keyword":
        return _eval_event_keyword(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "overseas_pct_move":
        return _eval_overseas_pct_move(con, symbol=symbol, as_of=as_of, params=params)
    return {"triggered": False, "coverage": "manual_review"}


def _threshold_hit(value: float, threshold: float, direction: str) -> bool:
    return value <= -abs(threshold) if direction == "down" else value >= abs(threshold)


def _eval_price_pct_move(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return {"triggered": False, "coverage": "missing:prices"}
    rows = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date(date) <= date(?) AND close IS NOT NULL
        ORDER BY date(date) DESC
        LIMIT 2
        """,
        (symbol, as_of),
    ).fetchall()
    if len(rows) < 2 or str(rows[0]["date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:as_of_price"}
    cur = float(rows[0]["close"])
    prev = float(rows[1]["close"])
    if prev == 0:
        return {"triggered": False, "coverage": "invalid:prev_close_zero"}
    pct = (cur / prev - 1.0) * 100.0
    threshold = float(params.get("threshold_pct") or 0)
    direction = str(params.get("direction") or "up")
    return {"triggered": _threshold_hit(pct, threshold, direction), "coverage": "ok", "value": pct, "threshold_pct": threshold}


def _eval_fund_flow_streak(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "fund_flows") or not {"symbol", "trade_date", "main_net"} <= _columns(con, "fund_flows"):
        return {"triggered": False, "coverage": "missing:fund_flows"}
    days = int(params.get("days") or 3)
    rows = con.execute(
        """
        SELECT trade_date, main_net
        FROM fund_flows
        WHERE symbol = ? AND date(trade_date) <= date(?) AND main_net IS NOT NULL
        ORDER BY date(trade_date) DESC
        LIMIT ?
        """,
        (symbol, as_of, days),
    ).fetchall()
    if len(rows) < days or str(rows[0]["trade_date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:flow_streak"}
    values = [float(row["main_net"]) for row in rows]
    direction = str(params.get("direction") or "up")
    triggered = all(value < 0 for value in values) if direction == "down" else all(value > 0 for value in values)
    return {"triggered": triggered, "coverage": "ok", "values": values, "days": days}


def _eval_event_keyword(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    tables = [str(table) for table in params.get("tables") or []]
    keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
    if not keywords:
        return {"triggered": False, "coverage": "missing:keywords"}
    table_meta = {
        "announcements": ("published_at", "title"),
        "research_reports": ("publish_date", "title"),
        "corporate_events": ("event_date", "title"),
    }
    matches: list[dict[str, Any]] = []
    missing: list[str] = []
    for table in tables:
        date_col, title_col = table_meta.get(table, ("", ""))
        if not date_col or not _table_exists(con, table) or not {"symbol", date_col, title_col} <= _columns(con, table):
            missing.append(table)
            continue
        rows = con.execute(
            f"""
            SELECT symbol, {date_col} AS item_date, {title_col} AS title
            FROM {table}
            WHERE symbol = ? AND date({date_col}) <= date(?)
            ORDER BY date({date_col}) DESC
            LIMIT 50
            """,
            (symbol, as_of),
        ).fetchall()
        for row in rows:
            title = str(row["title"] or "")
            hit = [keyword for keyword in keywords if keyword in title]
            if hit:
                matches.append({"table": table, "date": str(row["item_date"])[:10], "title": title, "keywords": hit})
    return {"triggered": bool(matches), "coverage": "ok" if matches or len(missing) < len(tables) else "missing:event_tables", "matches": matches, "missing_tables": missing}


def _eval_overseas_pct_move(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "overseas_snapshots"):
        return {"triggered": False, "coverage": "missing:overseas_snapshots"}
    field = str(params.get("field") or "chg_pct_1d")
    if not {"symbol", "snap_date", field} <= _columns(con, "overseas_snapshots"):
        return {"triggered": False, "coverage": "missing:overseas_columns"}
    rows = con.execute(
        f"""
        SELECT snap_date, {field} AS chg
        FROM overseas_snapshots
        WHERE symbol = ? AND date(snap_date) <= date(?) AND {field} IS NOT NULL
        ORDER BY date(snap_date) DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchall()
    if not rows or str(rows[0]["snap_date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:as_of_overseas"}
    value = float(rows[0]["chg"])
    threshold = float(params.get("threshold_pct") or 0)
    direction = str(params.get("direction") or "up")
    return {"triggered": _threshold_hit(value, threshold, direction), "coverage": "ok", "value": value, "threshold_pct": threshold}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compile ForwardThesis condition prose into M60 monitor specs.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args(argv)
    summary = compile_forward_thesis_conditions(db_path=args.db)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"thesis conditions: {summary['compiled_conditions']}/{summary['total_conditions']} "
            f"compiled ({summary['coverage_pct']}%), manual_review={summary['manual_review_conditions']}"
        )


if __name__ == "__main__":
    main()
