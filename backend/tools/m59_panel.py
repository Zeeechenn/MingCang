"""Build the read-only M59 postmarket operation panel."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import default_sqlite_path
from backend.data.context_builder import corporate_event_visible_as_of
from backend.data.degradation import recent_degradations
from backend.data.fundamentals import compute_piotroski_factors
from backend.data.market_features import FAKE_FEATURE_FLAGS
from backend.tools import m52_flow_floor as flow_floor
from backend.tools.m58_grid_backtest import regime_from_pool_equal_weight

DEFAULT_UNIVERSE_PATH = Path("paper_trading/test2_universe.json")
# M60 Watchtower Phase 1 writes m60_watchtower_*.json/.md here; the panel only
# reads the latest one, it never triggers a scan itself.
DEFAULT_WATCHTOWER_OUTPUT_DIR = Path("/private/tmp")
BUY_RECOMMENDATIONS = {"买", "买入", "强买", "考虑买入", "watch/考虑买入"}

# 2026-07-03 网格证伪:动量末档(bottom20%)在下行市反向(弱股反弹),不能当避雷器用,
# 仅上行/震荡市参考。regime 判定复用 m58 的池等权均线趋势函数,短窗5日 vs 长窗20日。
MOMENTUM_TAIL_REGIME_NOTE = (
    "动量末档在下行市反向(弱股反弹),经2026-07-03网格证伪:仅作上行/震荡市参考,"
    "下行市失效,不能当避雷器用"
)
REGIME_SHORT_WINDOW = 5
REGIME_LONG_WINDOW = 20
REGIME_FLAT_BAND = 0.02

# 贴近止损阈值:距止损缓冲空间(distance_to_stop_loss_pct) <= 此值(%)时计入"贴近止损"人话摘要计数。
STOP_LOSS_PROXIMITY_PCT = 5.0
MAX_POSITION_WEIGHT_PCT = 15.0


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _open_readonly_orm_session(db_path: Path):
    engine = create_engine(
        f"sqlite:///file:{db_path.resolve()}?mode=ro&uri=true",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    return engine, Session()


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _max_value(con: sqlite3.Connection, table: str, columns: list[str]) -> dict[str, Any]:
    if not _table_exists(con, table):
        return {"value": None, "status": f"missing:table:{table}"}
    available = _columns(con, table)
    usable = [column for column in columns if column in available]
    if not usable:
        return {"value": None, "status": f"missing:columns:{','.join(columns)}"}
    expressions = [f"MAX({column})" for column in usable]
    row = con.execute("SELECT " + ", ".join(expressions) + f" FROM {table}").fetchone()
    values = [row[index] for index in range(len(usable)) if row[index] is not None]
    if not values:
        return {"value": None, "status": "missing:data"}
    return {"value": max(str(value) for value in values), "status": "ok"}


def _latest_as_of(con: sqlite3.Connection, explicit_as_of: str | None) -> str:
    if explicit_as_of:
        return explicit_as_of
    for table, column in (("signals", "date"), ("prices", "date")):
        if _table_exists(con, table) and column in _columns(con, table):
            row = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
            if row and row[0]:
                return str(row[0])
    return date.today().isoformat()


def _stock_names(con: sqlite3.Connection) -> dict[str, str]:
    if not _table_exists(con, "stocks"):
        return {}
    cols = _columns(con, "stocks")
    if not {"symbol", "name"} <= cols:
        return {}
    rows = con.execute("SELECT symbol, name FROM stocks").fetchall()
    return {str(row["symbol"]): str(row["name"]) for row in rows if row["name"] is not None}


def _open_position_symbols(con: sqlite3.Connection) -> set[str]:
    if not _table_exists(con, "positions"):
        return set()
    cols = _columns(con, "positions")
    if "symbol" not in cols:
        return set()
    where = "WHERE COALESCE(status, 'open') = 'open'" if "status" in cols else ""
    rows = con.execute(f"SELECT symbol FROM positions {where}").fetchall()
    return {str(row["symbol"]) for row in rows}


def _latest_price(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "prices"):
        return None
    cols = _columns(con, "prices")
    if not {"symbol", "date", "close"} <= cols:
        return None
    row = con.execute(
        """
        SELECT symbol, date, close
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return dict(row) if row else None


def _latest_open_position_stop(con: sqlite3.Connection, symbol: str) -> float | None:
    if not _table_exists(con, "positions"):
        return None
    cols = _columns(con, "positions")
    if not {"symbol", "stop_loss"} <= cols:
        return None
    status_clause = "AND COALESCE(status, 'open') = 'open'" if "status" in cols else ""
    row = con.execute(
        f"""
        SELECT stop_loss
        FROM positions
        WHERE symbol = ? {status_clause}
        ORDER BY id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    return _safe_float(row["stop_loss"]) if row else None


def _atr14(con: sqlite3.Connection, symbol: str, as_of: str) -> float | None:
    if not _table_exists(con, "prices"):
        return None
    cols = _columns(con, "prices")
    if not {"symbol", "date", "high", "low", "close"} <= cols:
        return None
    rows = con.execute(
        """
        SELECT date, high, low, close
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 15
        """,
        (symbol, as_of),
    ).fetchall()
    if len(rows) < 15:
        return None
    ordered = [dict(row) for row in reversed(rows)]
    true_ranges: list[float] = []
    for idx in range(1, len(ordered)):
        high = _safe_float(ordered[idx].get("high"))
        low = _safe_float(ordered[idx].get("low"))
        prev_close = _safe_float(ordered[idx - 1].get("close"))
        if high is None or low is None or prev_close is None:
            return None
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return round(sum(true_ranges) / len(true_ranges), 4) if true_ranges else None


def _event_protective_action(con: sqlite3.Connection, symbol: str, as_of: str) -> str:
    price = _latest_price(con, symbol, as_of)
    current = _safe_float(price["close"]) if price else None
    atr = _atr14(con, symbol, as_of)
    missing = []
    if current is None:
        missing.append("price")
    if atr is None:
        missing.append("atr14")
    if missing:
        return f"数据不足,无法给出动作(缺:{','.join(missing)})"
    current_stop = _latest_open_position_stop(con, symbol)
    atr_stop = current - 1.5 * atr
    raised_stop = max(current_stop, atr_stop) if current_stop is not None else atr_stop
    return f"事件日前评估减仓;若持仓,止损上移至 {round(raised_stop, 2)}(=现价-1.5×ATR14)"


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_only(value: Any) -> str:
    text = str(value)
    return text[:10]


def _latest_long_term_label(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any]:
    """Return the latest still-valid long_term_labels row for symbol, reference-only."""
    if not _table_exists(con, "long_term_labels"):
        return {"label": None, "quality": None, "expires_at": None, "status": "missing:table:long_term_labels"}
    cols = _columns(con, "long_term_labels")
    if "symbol" not in cols:
        return {"label": None, "quality": None, "expires_at": None, "status": "missing:columns:symbol"}
    order_col = "date" if "date" in cols else ("created_at" if "created_at" in cols else None)
    if order_col is None:
        return {"label": None, "quality": None, "expires_at": None, "status": "missing:columns:date,created_at"}
    where_expiry = ""
    params: list[Any] = [symbol]
    if "expires_at" in cols:
        where_expiry = "AND (expires_at IS NULL OR expires_at >= ?)"
        params.append(as_of)
    select_cols = [column for column in ("label", "quality", "expires_at", order_col) if column in cols]
    row = con.execute(
        f"SELECT {', '.join(select_cols)} FROM long_term_labels WHERE symbol = ? {where_expiry} "
        f"ORDER BY {order_col} DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        return {"label": None, "quality": None, "expires_at": None, "status": "missing:no_valid_label"}
    data = dict(row)
    return {
        "label": data.get("label"),
        "quality": data.get("quality"),
        "expires_at": data.get("expires_at"),
        "status": "ok",
    }


def _latest_research_pointer(con: sqlite3.Connection, symbol: str) -> dict[str, Any]:
    """Return the most recent stock_memory_items research_pointer summary, reference-only."""
    if not _table_exists(con, "stock_memory_items"):
        return {"summary": None, "created_at": None, "status": "missing:table:stock_memory_items"}
    cols = _columns(con, "stock_memory_items")
    required = {"symbol", "memory_type", "summary", "created_at"}
    missing = sorted(required - cols)
    if missing:
        return {"summary": None, "created_at": None, "status": f"missing:columns:{','.join(missing)}"}
    row = con.execute(
        """
        SELECT summary, created_at
        FROM stock_memory_items
        WHERE symbol = ? AND memory_type = 'research_pointer'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return {"summary": None, "created_at": None, "status": "missing:no_research_pointer"}
    return {"summary": row["summary"], "created_at": row["created_at"], "status": "ok"}


def _build_research_reference(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any]:
    """Deep/long-term research pointers for LLM discretion only; never scored (owner 2026-07-03 软联动裁决)."""
    return {
        "long_term_label": _latest_long_term_label(con, symbol, as_of),
        "research_pointer": _latest_research_pointer(con, symbol),
    }


def _latest_market_reference(con: sqlite3.Connection) -> dict[str, Any]:
    """Latest theme/market-level research pointer for the header line, reference-only."""
    if _table_exists(con, "reports"):
        cols = _columns(con, "reports")
        title_col = "title" if "title" in cols else None
        date_col = "created_at" if "created_at" in cols else ("date" if "date" in cols else None)
        if title_col and date_col:
            row = con.execute(
                f"SELECT {title_col}, {date_col} FROM reports ORDER BY {date_col} DESC LIMIT 1"
            ).fetchone()
            if row:
                return {"title": row[0], "date": str(row[1]), "source_table": "reports", "status": "ok"}
    if _table_exists(con, "stock_memory_items"):
        cols = _columns(con, "stock_memory_items")
        if {"symbol", "summary", "created_at"} <= cols:
            row = con.execute(
                """
                SELECT summary, created_at
                FROM stock_memory_items
                WHERE symbol IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                return {
                    "title": row["summary"],
                    "date": str(row["created_at"]),
                    "source_table": "stock_memory_items",
                    "status": "ok",
                }
    return {"title": None, "date": None, "source_table": None, "status": "missing:no_theme_level_record"}


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{round(value, 2)}%"


def _build_overseas_reference(con: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(con, "overseas_snapshots"):
        return {"items": [], "flags": ["missing:table:overseas_snapshots"]}
    cols = _columns(con, "overseas_snapshots")
    required = {"symbol", "name", "snap_date", "close"}
    missing = sorted(required - cols)
    if missing:
        return {"items": [], "flags": [f"missing:columns:{','.join(missing)}"]}
    value_cols = [
        "symbol",
        "name",
        "snap_date",
        "close",
        "chg_pct_1d" if "chg_pct_1d" in cols else "NULL AS chg_pct_1d",
        "chg_pct_20d" if "chg_pct_20d" in cols else "NULL AS chg_pct_20d",
    ]
    rows = con.execute(
        f"""
        SELECT {', '.join(value_cols)}
        FROM overseas_snapshots
        WHERE (symbol, snap_date) IN (
            SELECT symbol, MAX(snap_date)
            FROM overseas_snapshots
            GROUP BY symbol
        )
        ORDER BY symbol ASC
        """
    ).fetchall()
    items = []
    for row in rows:
        data = dict(row)
        symbol = str(data["symbol"])
        name = str(data["name"])
        close = _safe_float(data.get("close"))
        chg_1d = _safe_float(data.get("chg_pct_1d"))
        chg_20d = _safe_float(data.get("chg_pct_20d"))
        line = f"{symbol}({name}) 收 {close} (1日 {_signed_pct(chg_1d)} / 20日 {_signed_pct(chg_20d)})"
        items.append(
            {
                "symbol": symbol,
                "name": name,
                "snap_date": _date_only(data.get("snap_date")),
                "close": close,
                "chg_pct_1d": chg_1d,
                "chg_pct_20d": chg_20d,
                "line": line,
                "note": "reference_only_not_scored",
            }
        )
    return {"items": items, "flags": []}


def _build_header(con: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    freshness = {
        "prices": _max_value(con, "prices", ["date", "fetched_at"]),
        "news": _max_value(con, "news", ["created_at", "fetched_at", "published_at"]),
        "long_term_labels": _max_value(con, "long_term_labels", ["date", "created_at"]),
    }
    degradation_flags = [
        "llm_layer:not_implemented",
        "quant_model:placeholder_v0",
        "market_regime:missing_index_ohlc",
    ]
    return {
        "as_of": as_of,
        "freshness": freshness,
        "degradation_flags": degradation_flags,
        "market_regime": {
            "value": None,
            "flag": "missing_index_ohlc",
            "note": "backend.analysis.timing.regime requires index OHLC; index_prices has close-only rows",
        },
        "market_reference": _latest_market_reference(con),
    }


def _build_buy_candidates(con: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    flags: list[str] = ["llm_layer:not_implemented"]
    if not _table_exists(con, "signals"):
        return {"items": [], "flags": ["missing:table:signals", *flags]}
    required = {"symbol", "date", "recommendation", "composite_score", "stop_loss", "take_profit"}
    cols = _columns(con, "signals")
    missing = sorted(required - cols)
    if missing:
        return {"items": [], "flags": [f"missing:columns:{','.join(missing)}", *flags]}

    names = _stock_names(con)
    rows = con.execute(
        """
        SELECT symbol, date, recommendation, composite_score, stop_loss, take_profit
        FROM signals
        WHERE date = ?
        ORDER BY composite_score DESC
        """,
        (as_of,),
    ).fetchall()
    items = []
    for row in rows:
        recommendation = str(row["recommendation"] or "")
        if recommendation not in BUY_RECOMMENDATIONS and "买" not in recommendation:
            continue
        symbol = str(row["symbol"])
        item_missing = []
        for key in ("composite_score", "stop_loss", "take_profit"):
            if row[key] is None:
                item_missing.append(f"missing:{key}")
        items.append(
            {
                "symbol": symbol,
                "name": names.get(symbol),
                "recommendation": recommendation,
                "composite_score": _safe_float(row["composite_score"]),
                "stop_loss": _safe_float(row["stop_loss"]),
                "take_profit": _safe_float(row["take_profit"]),
                "llm_discretion": None,
                "llm_layer": "not_implemented",
                "missing": item_missing,
                "quality_flags": _quality_flags(con, symbol),
                "research_reference": _build_research_reference(con, symbol, as_of),
            }
        )
    return {"items": items, "flags": flags}


def _quality_flags(con: sqlite3.Connection, symbol: str) -> list[str]:
    if not _table_exists(con, "financial_metrics"):
        return []
    cols = _columns(con, "financial_metrics")
    required = {"symbol", "report_date"}
    if not required <= cols:
        return []
    select_cols = [
        "net_profit" if "net_profit" in cols else "NULL AS net_profit",
        "operating_cf" if "operating_cf" in cols else "NULL AS operating_cf",
        "current_ratio" if "current_ratio" in cols else "NULL AS current_ratio",
        "gross_margin" if "gross_margin" in cols else "NULL AS gross_margin",
    ]
    row = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM financial_metrics
        WHERE symbol = ?
        ORDER BY report_date DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return []
    data = dict(row)
    flags: list[str] = []
    operating_cf = _safe_float(data.get("operating_cf"))
    net_profit = _safe_float(data.get("net_profit"))
    current_ratio = _safe_float(data.get("current_ratio"))
    gross_margin = _safe_float(data.get("gross_margin"))
    if operating_cf is not None and net_profit is not None and operating_cf <= net_profit:
        flags.append("CFO<净利")
    if current_ratio is not None and current_ratio < 1:
        flags.append("流动比率<1")
    if gross_margin is not None and gross_margin < 10:
        flags.append("毛利率过薄")
    return flags


def _piotroski_display(db_session, symbol: str) -> str:
    if db_session is None:
        return "-"
    try:
        factors = compute_piotroski_factors(symbol, db_session)
    except Exception:
        return "-"
    if not factors.get("available"):
        return "-"
    denominator = factors.get("score_denominator")
    score = factors.get("score")
    if score is None or denominator is None:
        return "-"
    return f"{score}/{denominator}"


def _fund_flow_rows(con: sqlite3.Connection, symbol: str, as_of: str) -> list[dict[str, Any]] | None:
    if not _table_exists(con, "fund_flows"):
        return None
    cols = _columns(con, "fund_flows")
    required = {"symbol", "trade_date"}
    if not required <= cols:
        return None
    value_cols = [column for column in ("main_net", "super_large_net", "large_net", "medium_net", "small_net") if column in cols]
    if not value_cols:
        return None
    rows = con.execute(
        f"""
        SELECT trade_date, {', '.join(value_cols)}
        FROM fund_flows
        WHERE symbol = ? AND date(trade_date) <= date(?)
        ORDER BY date(trade_date) DESC
        LIMIT 65
        """,
        (symbol, as_of),
    ).fetchall()
    if not rows:
        return None
    return [dict(row) for row in reversed(rows)]


def _s_flow_display(con: sqlite3.Connection, symbol: str, as_of: str) -> float | str:
    try:
        value = flow_floor.compute_s_flow_data(_fund_flow_rows(con, symbol, as_of))
    except Exception:
        return "-"
    return "-" if value is None else round(float(value), 4)


def _next_event_display(con: sqlite3.Connection, symbol: str, as_of: str) -> str:
    if not _table_exists(con, "corporate_events"):
        return "-"
    cols = _columns(con, "corporate_events")
    if not {"symbol", "event_type", "event_date"} <= cols:
        return "-"
    rows = con.execute(
        """
        SELECT event_type, event_date
        FROM corporate_events
        WHERE symbol = ?
          AND date(event_date) >= date(?)
          AND date(event_date) <= date(?, '+90 day')
        ORDER BY date(event_date) ASC
        """,
        (symbol, as_of, as_of),
    ).fetchall()
    for row in rows:
        if corporate_event_visible_as_of(str(row["event_type"]), str(row["event_date"]), as_of):
            return f"{row['event_type']} {_date_only(row['event_date'])}"
    return "-"


def _build_position_health(con: sqlite3.Connection, as_of: str, db_session=None) -> dict[str, Any]:
    if not _table_exists(con, "positions"):
        return {"items": [], "flags": ["missing:table:positions"]}
    required = {"symbol", "name", "quantity", "avg_cost", "stop_loss", "take_profit", "status"}
    cols = _columns(con, "positions")
    if "symbol" not in cols:
        return {"items": [], "flags": ["missing:columns:symbol"]}
    select_cols = [column for column in required if column in cols]
    rows = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM positions
        WHERE COALESCE(status, 'open') = 'open'
        ORDER BY symbol
        """
    ).fetchall()
    items = []
    for row in rows:
        data = dict(row)
        symbol = str(data["symbol"])
        price = _latest_price(con, symbol, as_of)
        current = _safe_float(price["close"]) if price else None
        stop_loss = _safe_float(data.get("stop_loss"))
        take_profit = _safe_float(data.get("take_profit"))
        atr14 = _atr14(con, symbol, as_of)
        missing = []
        if current is None:
            missing.append("missing:price")
        if stop_loss is None:
            missing.append("missing:stop_loss")
        if take_profit is None:
            missing.append("missing:take_profit")
        if atr14 is None:
            missing.append("missing:atr14")

        stop_distance = None
        take_distance = None
        stop_gap_atr = None
        if current not in (None, 0):
            if stop_loss is not None:
                stop_distance = _pct((current - stop_loss) / current)
                if atr14 not in (None, 0):
                    stop_gap_atr = round((current - stop_loss) / atr14, 2)
            if take_profit is not None:
                take_distance = _pct((take_profit - current) / current)

        series = _price_series(con, symbol, as_of)
        _, _, mom20 = _momentum_score(series)
        stop_flags: list[str] = []
        if stop_gap_atr is not None and stop_gap_atr < 1.5:
            stop_flags.append("止损贴身(<1.5×ATR,易被正常波动洗出)")
        if take_profit is not None and mom20 is not None and mom20 > 0.15:
            stop_flags.append("动量股用静态止盈位,建议改ATR追踪")

        items.append(
            {
                "symbol": symbol,
                "name": data.get("name"),
                "quantity": _safe_float(data.get("quantity")),
                "avg_cost": _safe_float(data.get("avg_cost")),
                "current_price": current,
                "price_date": price["date"] if price else None,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "distance_to_stop_loss_pct": stop_distance,
                "distance_to_take_profit_pct": take_distance,
                "atr14": atr14,
                "stop_gap_atr": stop_gap_atr,
                "stop_flags": stop_flags,
                "piotroski": _piotroski_display(db_session, symbol),
                "s_flow": _s_flow_display(con, symbol, as_of),
                "next_event": _next_event_display(con, symbol, as_of),
                "quality_flags": _quality_flags(con, symbol),
                "missing": missing,
                "research_reference": _build_research_reference(con, symbol, as_of),
            }
        )
    return {"items": items, "flags": []}


def _load_universe(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], [f"missing:universe:{path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"invalid:universe_json:{exc.msg}"]
    stocks = payload.get("stocks") if isinstance(payload, dict) else None
    if not isinstance(stocks, list):
        return [], ["missing:universe_stocks"]
    items = []
    for item in stocks:
        if isinstance(item, dict) and item.get("symbol"):
            items.append({"symbol": str(item["symbol"]), "name": item.get("name")})
    return items, []


def _price_series(con: sqlite3.Connection, symbol: str, as_of: str) -> list[tuple[str, float]]:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return []
    rows = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 21
        """,
        (symbol, as_of),
    ).fetchall()
    return [(str(row["date"]), float(row["close"])) for row in reversed(rows) if row["close"] is not None]


def _momentum_score(series: list[tuple[str, float]]) -> tuple[float | None, float | None, float | None]:
    if len(series) < 21:
        return None, None, None
    current = series[-1][1]
    close_5 = series[-6][1]
    close_20 = series[-21][1]
    if current == 0 or close_5 == 0 or close_20 == 0:
        return None, None, None
    mom5 = current / close_5 - 1.0
    mom20 = current / close_20 - 1.0
    return round(0.6 * mom5 + 0.4 * mom20, 6), round(mom5, 6), round(mom20, 6)


def _pool_panel_frame(con: sqlite3.Connection, universe: list[dict[str, Any]], as_of: str) -> pd.DataFrame:
    rows = []
    for stock in universe:
        symbol = str(stock["symbol"])
        for trade_date, close in _price_series(con, symbol, as_of):
            rows.append({"date": trade_date, "symbol": symbol, "close": close})
    return pd.DataFrame(rows, columns=["date", "symbol", "close"])


def _market_regime(con: sqlite3.Connection, universe: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    """Pool equal-weight MA regime (short=5d vs long=20d), used to gate the momentum tail's reliability.

    This is a fallback distinct from the header's HS300-index regime (which is
    blocked on missing index OHLC): it reuses m58's
    regime_from_pool_equal_weight over the same universe used for the momentum
    tail, so ③ can honestly label whether its own risk signal is usable today.
    """
    method = (
        f"pool_equal_weight_ma(short={REGIME_SHORT_WINDOW},long={REGIME_LONG_WINDOW},"
        f"flat_band={REGIME_FLAT_BAND})"
    )
    panel = _pool_panel_frame(con, universe, as_of)
    if panel.empty:
        return {"value": "unknown", "method": method, "as_of_date": None, "flag": "missing:pool_price_data"}
    regimes = regime_from_pool_equal_weight(
        panel,
        short_window=REGIME_SHORT_WINDOW,
        long_window=REGIME_LONG_WINDOW,
        flat_band=REGIME_FLAT_BAND,
    )
    if regimes.empty:
        return {"value": "unknown", "method": method, "as_of_date": None, "flag": "missing:pool_price_data"}
    latest = regimes.sort_values("date").iloc[-1]
    return {"value": str(latest["regime"]), "method": method, "as_of_date": str(latest["date"])}


def _build_concentration(position_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic position-concentration risk info (test1 兆易/test2 天孚单点教训)."""
    if not position_items:
        return {
            "items": [],
            "max_position_symbol": None,
            "max_position_weight_pct": None,
            "top3_weight_pct": None,
            "top3_symbols": [],
            "position_count": 0,
            "basis": "sum_of_open_position_market_value(quantity*current_price_or_avg_cost_fallback)",
            "flags": ["no_open_positions"],
        }
    valued = []
    for item in position_items:
        quantity = item.get("quantity")
        price = item.get("current_price")
        avg_cost = item.get("avg_cost")
        value = None
        used_avg_cost_fallback = False
        if quantity is not None:
            if price is not None:
                value = quantity * price
            elif avg_cost is not None:
                value = quantity * avg_cost
                used_avg_cost_fallback = True
        valued.append(
            {
                "symbol": item["symbol"],
                "name": item.get("name"),
                "value": value,
                "used_avg_cost_fallback": used_avg_cost_fallback,
            }
        )
    priced = [entry for entry in valued if entry["value"] is not None]
    flags: list[str] = []
    unpriced = [entry["symbol"] for entry in valued if entry["value"] is None]
    if unpriced:
        flags.append(f"missing:value_for:{','.join(unpriced)}")
    if not priced:
        return {
            "items": [],
            "max_position_symbol": None,
            "max_position_weight_pct": None,
            "top3_weight_pct": None,
            "top3_symbols": [],
            "position_count": len(position_items),
            "basis": "sum_of_open_position_market_value(quantity*current_price_or_avg_cost_fallback)",
            "flags": flags,
        }
    total = sum(entry["value"] for entry in priced)
    for entry in priced:
        entry["weight_pct"] = round(100 * entry["value"] / total, 2) if total else None
    priced.sort(key=lambda entry: (-(entry["weight_pct"] or -1), entry["symbol"]))
    top3 = priced[:3]
    fallback_symbols = [entry["symbol"] for entry in priced if entry["used_avg_cost_fallback"]]
    if fallback_symbols:
        flags.append(f"used_avg_cost_fallback:{','.join(fallback_symbols)}")
    return {
        "items": [
            {
                "symbol": entry["symbol"],
                "name": entry["name"],
                "weight_pct": entry["weight_pct"],
                "protective_action": (
                    f"集中度超限:建议减仓至{MAX_POSITION_WEIGHT_PCT}%以内"
                    if (entry["weight_pct"] or 0) > MAX_POSITION_WEIGHT_PCT
                    else f"集中度未超{MAX_POSITION_WEIGHT_PCT}%单仓阈值,维持观察"
                ),
            }
            for entry in priced
        ],
        "max_position_symbol": priced[0]["symbol"],
        "max_position_weight_pct": priced[0]["weight_pct"],
        "top3_weight_pct": round(sum(entry["weight_pct"] or 0 for entry in top3), 2),
        "top3_symbols": [entry["symbol"] for entry in top3],
        "position_count": len(position_items),
        "basis": "sum_of_open_position_market_value(quantity*current_price_or_avg_cost_fallback)",
        "flags": flags,
    }


def _momentum_protective_action(item: dict[str, Any], regime_reliable: bool | None) -> str:
    if regime_reliable is False:
        return "下行市动量末档失效,仅观察;若已持仓,观察触发:收盘跌破近5日低点即减半"
    if item.get("in_position"):
        return "动量降级:建议减仓至50%;若连续2日仍在末档,再降至25%"
    return "动量末档候选:暂停新增仓位,等待脱离bottom20%后再评估"


def _build_stop_loss_buffer_ranking(position_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Positions ranked by remaining buffer to stop loss, thinnest buffer first."""
    with_distance = [item for item in position_items if item.get("distance_to_stop_loss_pct") is not None]
    without_distance = [item for item in position_items if item.get("distance_to_stop_loss_pct") is None]
    with_distance.sort(key=lambda item: (item["distance_to_stop_loss_pct"], item["symbol"]))
    items = [
        {
            "symbol": item["symbol"],
            "name": item.get("name"),
            "distance_to_stop_loss_pct": item["distance_to_stop_loss_pct"],
            "current_price": item.get("current_price"),
            "stop_loss": item.get("stop_loss"),
        }
        for item in with_distance
    ]
    missing_symbols = [item["symbol"] for item in without_distance]
    flags = [f"missing:distance_to_stop_loss_pct:{','.join(missing_symbols)}"] if missing_symbols else []
    return {
        "items": items,
        "missing_symbols": missing_symbols,
        "note": "按距止损缓冲空间升序排列,最薄的排最前",
        "flags": flags,
    }


def _build_event_warnings(con: sqlite3.Connection, universe: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    if not _table_exists(con, "corporate_events"):
        return {"items": [], "flags": ["missing:table:corporate_events"]}
    cols = _columns(con, "corporate_events")
    required = {"symbol", "event_type", "event_date"}
    missing = sorted(required - cols)
    if missing:
        return {"items": [], "flags": [f"missing:columns:{','.join(missing)}"]}
    if not universe:
        return {"items": [], "flags": ["missing:universe_symbols"]}

    names = _stock_names(con)
    universe_names = {str(item["symbol"]): item.get("name") for item in universe}
    symbols = sorted(universe_names)
    placeholders = ", ".join("?" for _ in symbols)
    rows = con.execute(
        f"""
        SELECT symbol, event_type, event_date,
               {('title' if 'title' in cols else "'' AS title")},
               {('detail' if 'detail' in cols else "'' AS detail")}
        FROM corporate_events
        WHERE symbol IN ({placeholders})
          AND event_type IN ('解禁', '定增', '监管')
          AND date(event_date) >= date(?, '-7 day')
          AND date(event_date) <= date(?, '+30 day')
        ORDER BY date(event_date) ASC, symbol ASC
        """,
        [*symbols, as_of, as_of],
    ).fetchall()
    rows = [
        row
        for row in rows
        if corporate_event_visible_as_of(str(row["event_type"]), str(row["event_date"]), as_of)
    ]
    # iFinD 事件源对进行中的解禁按日各返回一行(同一解禁连续多日提示)——
    # 按 (symbol, event_type) 归并连续日期段,展示层去重(数据行不动)。
    # 小白测试实证:同一解禁重复 6 行被读成 bug(2026-07-05 修)。
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault((str(row["symbol"]), str(row["event_type"])), []).append(row)
    items = []
    for (symbol, event_type), group in grouped.items():
        name = universe_names.get(symbol) or names.get(symbol) or ""
        dates = [_date_only(r["event_date"]) for r in group]
        first_date, last_date = dates[0], dates[-1]
        detail = group[-1]["detail"] or group[-1]["title"] or "-"
        if len(group) >= 2:
            date_display = f"{first_date}~{last_date}"
            line = f"⚠️ {symbol} {name} {event_type} {date_display} (连续提示{len(group)}天)"
        else:
            date_display = first_date
            line = f"⚠️ {symbol} {name} {event_type} {first_date} ({detail})"
        items.append(
            {
                "symbol": symbol,
                "name": name,
                "event_type": event_type,
                "event_date": first_date,
                "event_date_last": last_date,
                "consecutive_days": len(group),
                "detail": detail,
                "line": line,
                "protective_action": _event_protective_action(con, symbol, as_of),
            }
        )
    items.sort(key=lambda item: (item["event_date"], item["symbol"]))
    return {"items": items, "flags": []}


def _build_risk_warnings(
    con: sqlite3.Connection,
    as_of: str,
    universe_path: Path,
    position_items: list[dict[str, Any]],
) -> dict[str, Any]:
    universe, flags = _load_universe(universe_path)
    positions = _open_position_symbols(con)
    complete: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    for stock in universe:
        symbol = str(stock["symbol"])
        score, mom5, mom20 = _momentum_score(_price_series(con, symbol, as_of))
        if score is None:
            missing_symbols.append(symbol)
            continue
        complete.append(
            {
                "symbol": symbol,
                "name": stock.get("name"),
                "momentum_score": score,
                "mom5": mom5,
                "mom20": mom20,
                "warning_note": "预警≠卖出指令",
                "in_position": symbol in positions,
            }
        )
    complete.sort(key=lambda item: (item["momentum_score"], item["symbol"]))
    n_tail = math.ceil(len(complete) * 0.2) if complete else 0

    regime = _market_regime(con, universe, as_of)
    if regime["value"] in ("up", "flat"):
        regime_reliable: bool | None = True
    elif regime["value"] == "down":
        regime_reliable = False
    else:
        regime_reliable = None
    tail_items = complete[:n_tail]
    for item in tail_items:
        item["protective_action"] = _momentum_protective_action(item, regime_reliable)

    return {
        "section_name": "风险工程区",
        "market_regime": regime,
        "momentum_tail": {
            "method": "placeholder_v0:0.6*mom5+0.4*mom20,bottom20pct",
            "items": tail_items,
            "missing_symbols": missing_symbols,
            "regime_reliable": regime_reliable,
            "note": MOMENTUM_TAIL_REGIME_NOTE,
        },
        "event_warnings": _build_event_warnings(con, universe, as_of),
        "concentration": _build_concentration(position_items),
        "stop_loss_buffer_ranking": _build_stop_loss_buffer_ranking(position_items),
        "flags": flags + (["missing:table:prices"] if not _table_exists(con, "prices") else []),
    }


def _build_review_attribution(con: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    if not _table_exists(con, "positions"):
        return {
            "items": [],
            "note": "positions table missing; no closed trade attribution available",
            "flags": ["missing:table:positions"],
        }
    cols = _columns(con, "positions")
    required = {"symbol", "name", "closed_at", "close_price", "realized_pnl", "realized_pnl_pct"}
    if not {"symbol", "closed_at"} <= cols:
        return {"items": [], "note": "positions closed_at unavailable", "flags": ["missing:closed_at"]}
    select_cols = [column for column in required if column in cols]
    rows = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM positions
        WHERE closed_at = ?
        ORDER BY symbol
        """,
        (as_of,),
    ).fetchall()
    items = []
    for row in rows:
        data = dict(row)
        items.append(
            {
                "symbol": data.get("symbol"),
                "name": data.get("name"),
                "closed_at": data.get("closed_at"),
                "close_price": _safe_float(data.get("close_price")),
                "realized_pnl": _safe_float(data.get("realized_pnl")),
                "realized_pnl_pct": _safe_float(data.get("realized_pnl_pct")),
                "llm_discipline_candidate": None,
                "llm_layer": "not_implemented",
            }
        )
    note = "no closed positions for as_of" if not items else "closed positions from positions table"
    return {"items": items, "note": note, "flags": ["llm_layer:not_implemented"]}


def _find_latest_watchtower_file(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(output_dir.glob("m60_watchtower_*.json"))
    return candidates[-1] if candidates else None


def _build_watchtower_followups(watchtower_output_dir: Path) -> dict[str, Any]:
    """M60 Phase 1 wiring: surface the latest watchtower scan as read-only followup candidates.

    Never generates its own triggers — only reads the most recent
    ``m60_watchtower_*.json`` file written by ``backend.tools.m60_watchtower``.
    When no such file exists yet, this explicitly reports ``missing`` rather
    than silently showing an empty section.
    """
    latest_file = _find_latest_watchtower_file(watchtower_output_dir)
    if latest_file is None:
        return {
            "items": [],
            "source_file": None,
            "as_of": None,
            "note": "触发≠买入,待 LLM 确认层(Phase 2)",
            "flags": [f"missing:no_watchtower_output_in:{watchtower_output_dir}"],
        }
    try:
        payload = json.loads(latest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "items": [],
            "source_file": str(latest_file),
            "as_of": None,
            "note": "触发≠买入,待 LLM 确认层(Phase 2)",
            "flags": [f"invalid:watchtower_json:{exc.msg}"],
        }
    triggers = payload.get("triggers") if isinstance(payload, dict) else None
    items = []
    for trigger in triggers or []:
        items.append(
            {
                "symbol": trigger.get("symbol"),
                "themes": trigger.get("themes"),
                "trigger_type": trigger.get("trigger_type"),
                "value": trigger.get("value"),
                "price": trigger.get("price"),
                "reentry_hint": trigger.get("reentry_hint") or trigger.get("reentry_trigger"),
                "followup_note": "触发≠买入,待 LLM 确认层(Phase 2)",
            }
        )
    return {
        "items": items,
        "source_file": str(latest_file),
        "as_of": payload.get("as_of") if isinstance(payload, dict) else None,
        "note": "触发≠买入,待 LLM 确认层(Phase 2)",
        "flags": [] if items else (["watchtower_no_trigger_today"] if isinstance(payload, dict) else ["invalid:watchtower_payload"]),
    }


def _find_latest_confirm_file(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    candidates = sorted(output_dir.glob("m60_confirm_*.json"))
    return candidates[-1] if candidates else None


def _build_watchtower_confirm(confirm_output_dir: Path) -> dict[str, Any]:
    """M60 Phase 2 wiring: surface the latest LLM confirmation cards, read-only.

    Never triggers an LLM call itself — only reads the most recent
    ``m60_confirm_*.json`` file written by ``backend.research.watchtower_confirm``
    (run manually via ``m60_watchtower --confirm``, off by default). Explicitly
    reports ``missing`` when no such file exists yet, matching
    ``_build_watchtower_followups``'s degrade-explicitly convention.
    """
    latest_file = _find_latest_confirm_file(confirm_output_dir)
    if latest_file is None:
        return {
            "items": [],
            "source_file": None,
            "as_of": None,
            "note": "跟进关注≠买入建议",
            "flags": [f"missing:no_confirm_output_in:{confirm_output_dir}"],
        }
    try:
        payload = json.loads(latest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "items": [],
            "source_file": str(latest_file),
            "as_of": None,
            "note": "跟进关注≠买入建议",
            "flags": [f"invalid:confirm_json:{exc.msg}"],
        }
    cards = payload.get("cards") if isinstance(payload, dict) else None
    items = []
    for card in cards or []:
        items.append(
            {
                "symbol": card.get("symbol"),
                "theme": card.get("theme"),
                "stance": card.get("stance"),
                "reasoning": card.get("reasoning"),
                "risks": card.get("risks"),
                "validation_question": card.get("validation_question"),
                "reentry_hint": card.get("reentry_hint") or card.get("reentry_trigger"),
                "thesis_status": card.get("thesis_status"),
                "used_llm": card.get("used_llm"),
                "flags": card.get("flags"),
            }
        )
    return {
        "items": items,
        "source_file": str(latest_file),
        "as_of": payload.get("as_of") if isinstance(payload, dict) else None,
        "note": "跟进关注≠买入建议",
        "flags": [] if items else (["confirm_no_cards"] if isinstance(payload, dict) else ["invalid:confirm_payload"]),
    }


def _build_summary(
    buy_candidates: dict[str, Any],
    position_health: dict[str, Any],
    risk_warnings: dict[str, Any],
) -> dict[str, Any]:
    """Plain-language rollup for a quick read: candidates / positions near stop loss / risk hints."""
    candidates_count = len(buy_candidates["items"])
    position_items = position_health["items"]
    position_count = len(position_items)
    near_stop_loss = [
        item
        for item in position_items
        if item.get("distance_to_stop_loss_pct") is not None
        and item["distance_to_stop_loss_pct"] <= STOP_LOSS_PROXIMITY_PCT
    ]
    near_stop_loss_count = len(near_stop_loss)
    risk_warning_count = len(risk_warnings["momentum_tail"]["items"])
    tight_stop = [
        item
        for item in position_items
        if any("止损贴身" in flag for flag in (item.get("stop_flags") or []))
    ]
    action_items = []
    action_items.extend(risk_warnings.get("event_warnings", {}).get("items") or [])
    action_items.extend(risk_warnings.get("momentum_tail", {}).get("items") or [])
    action_items.extend(risk_warnings.get("concentration", {}).get("items") or [])
    action_missing = [
        item
        for item in action_items
        if str(item.get("protective_action") or "").startswith("数据不足")
    ]
    text = (
        f"今日候选{candidates_count}只/"
        f"持仓{position_count}只其中{near_stop_loss_count}只贴近止损/"
        f"ATR贴身止损{len(tight_stop)}只/"
        f"风险提示{risk_warning_count}条/"
        f"动作缺数据{len(action_missing)}条"
    )
    return {
        "candidates_count": candidates_count,
        "position_count": position_count,
        "near_stop_loss_count": near_stop_loss_count,
        "near_stop_loss_symbols": [item["symbol"] for item in near_stop_loss],
        "tight_stop_count": len(tight_stop),
        "tight_stop_symbols": [item["symbol"] for item in tight_stop],
        "action_missing_count": len(action_missing),
        "risk_warning_count": risk_warning_count,
        "text": text,
    }


def _build_data_health(db_session) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if db_session is not None:
        try:
            events = recent_degradations(hours=48, db=db_session)
        except Exception:
            events = []
    grouped = Counter(str(event.get("component")) for event in events if event.get("component"))
    placeholders = {
        name: meta
        for name, meta in FAKE_FEATURE_FLAGS.items()
        if isinstance(meta, dict) and meta.get("placeholder") is True
    }
    return {
        "recent_degradations_by_component": dict(sorted(grouped.items())),
        "recent_degradation_count": sum(grouped.values()),
        "active_fake_feature_flags": placeholders,
        "hours": 48,
    }


def build_panel(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    watchtower_output_dir: str | Path = DEFAULT_WATCHTOWER_OUTPUT_DIR,
    confirm_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a postmarket_panel.v1 payload without writing the database."""
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    resolved_universe = Path(universe_path)
    resolved_confirm_dir = Path(confirm_output_dir) if confirm_output_dir is not None else Path(watchtower_output_dir)
    engine, db_session = _open_readonly_orm_session(resolved_db)
    try:
        with _connect_readonly(resolved_db) as con:
            resolved_as_of = _latest_as_of(con, as_of)
            buy_candidates = _build_buy_candidates(con, resolved_as_of)
            position_health = _build_position_health(con, resolved_as_of, db_session)
            risk_warnings = _build_risk_warnings(
                con, resolved_as_of, resolved_universe, position_health["items"]
            )
            return {
                "schema_version": "postmarket_panel.v1",
                "summary": _build_summary(buy_candidates, position_health, risk_warnings),
                "header": _build_header(con, resolved_as_of),
                "buy_candidates": buy_candidates,
                "position_health": position_health,
                "risk_warnings": risk_warnings,
                "review_attribution": _build_review_attribution(con, resolved_as_of),
                "watchtower_followups": _build_watchtower_followups(Path(watchtower_output_dir)),
                "watchtower_confirm": _build_watchtower_confirm(resolved_confirm_dir),
                "overseas_reference": _build_overseas_reference(con),
                "data_health": _build_data_health(db_session),
            }
    finally:
        db_session.close()
        engine.dispose()


def _format_research_reference(reference: dict[str, Any] | None) -> str:
    if not reference:
        return "missing"
    label = reference.get("long_term_label") or {}
    pointer = reference.get("research_pointer") or {}
    label_text = (
        f"{label.get('label')}/{label.get('quality')}(至{label.get('expires_at')})"
        if label.get("status") == "ok"
        else label.get("status", "missing")
    )
    pointer_text = pointer.get("summary") if pointer.get("status") == "ok" else pointer.get("status", "missing")
    return f"标签:{label_text}; 研究指针:{pointer_text}"


def render_markdown(panel: dict[str, Any]) -> str:
    header = panel["header"]
    market_reference = header.get("market_reference") or {}
    market_reference_line = (
        f"{market_reference.get('title')} ({market_reference.get('date')})"
        if market_reference.get("status") == "ok"
        else market_reference.get("status", "missing")
    )
    lines = [
        panel["summary"]["text"],
        "",
        f"# M59 盘后操作面板 ({header['as_of']})",
        "",
        "## 页头",
        f"- 数据新鲜度 prices: {header['freshness']['prices']['value']} ({header['freshness']['prices']['status']})",
        f"- 数据新鲜度 news: {header['freshness']['news']['value']} ({header['freshness']['news']['status']})",
        f"- 数据新鲜度 long_term_labels: {header['freshness']['long_term_labels']['value']} ({header['freshness']['long_term_labels']['status']})",
        f"- 降级 flag: {', '.join(header['degradation_flags'])}",
        f"- 市场 regime: {header['market_regime']['value']} ({header['market_regime']['flag']})",
        f"- 行情参考: {market_reference_line}",
        "",
        "## ① 买入候选",
        "| symbol | name | score | stop_loss | take_profit | llm_layer | 质量 | 研究参考 |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for item in panel["buy_candidates"]["items"]:
        quality_flags = item.get("quality_flags") or []
        quality_text = (
            f"⚠质量: {', '.join(quality_flags)} → 建议仓位上限减半"
            if quality_flags
            else "-"
        )
        lines.append(
            f"| {item['symbol']} | {item.get('name') or ''} | {item.get('composite_score')} | "
            f"{item.get('stop_loss')} | {item.get('take_profit')} | {item.get('llm_layer')} | "
            f"{quality_text} | "
            f"{_format_research_reference(item.get('research_reference'))} |"
        )
    lines.extend(
        [
            "",
            "## ② 持仓体检",
            "| symbol | current | stop distance % | take distance % | 止损/ATR | piotroski | s_flow | next_event | missing | flags | 研究参考 |",
            "|---|---:|---:|---:|---:|---|---:|---|---|---|---|",
        ]
    )
    for item in panel["position_health"]["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('current_price')} | {item.get('distance_to_stop_loss_pct')} | "
            f"{item.get('distance_to_take_profit_pct')} | {item.get('stop_gap_atr')} | "
            f"{item.get('piotroski')} | {item.get('s_flow')} | "
            f"{item.get('next_event')} | {', '.join(item.get('missing') or [])} | "
            f"{'; '.join(item.get('stop_flags') or [])} | "
            f"{_format_research_reference(item.get('research_reference'))} |"
        )
    risk = panel["risk_warnings"]
    momentum_tail = risk["momentum_tail"]
    concentration = risk["concentration"]
    buffer_ranking = risk["stop_loss_buffer_ranking"]
    lines.extend(
        [
            "",
            "## ③ 风险工程区",
            f"市场 regime: {risk['market_regime']['value']} ({risk['market_regime']['method']})",
            "",
            "避雷警示区:",
        ]
    )
    event_warnings = risk.get("event_warnings", {})
    if event_warnings.get("items"):
        for item in event_warnings["items"]:
            lines.append(f"{item.get('line', '')} → 动作: {item.get('protective_action')}")
    else:
        flags = event_warnings.get("flags") or []
        lines.append("暂无" + (f" ({', '.join(flags)})" if flags else ""))
    lines.extend(
        [
            "",
            f"动量末档:{momentum_tail['note']} (regime_reliable={momentum_tail['regime_reliable']})",
            "预警≠卖出指令",
            "| symbol | momentum | in_position | 动作 |",
            "|---|---:|---|---|",
        ]
    )
    for item in momentum_tail["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('momentum_score')} | {item.get('in_position')} | "
            f"{item.get('protective_action')} |"
        )
    lines.extend(
        [
            "",
            f"持仓集中度:最大单仓 {concentration.get('max_position_symbol')} "
            f"{concentration.get('max_position_weight_pct')}%,前三仓 {concentration.get('top3_weight_pct')}%",
            "",
            "止损缓冲排序(最薄在前):",
            "| symbol | distance_to_stop_loss_pct |",
            "|---|---:|",
        ]
    )
    for item in buffer_ranking["items"]:
        lines.append(f"| {item['symbol']} | {item.get('distance_to_stop_loss_pct')} |")
    lines.extend(["", "## ④ 复盘归因", panel["review_attribution"]["note"]])

    followups = panel.get("watchtower_followups", {})
    lines.extend(["", "## ⑤ 跟进候选(观察哨)", followups.get("note", "")])
    if followups.get("source_file") is None:
        lines.append(f"missing: {', '.join(followups.get('flags') or ['no_watchtower_output'])}")
    elif not followups.get("items"):
        lines.append(f"来源: {followups.get('source_file')} (as_of={followups.get('as_of')}) — 今日清单内无触发")
    else:
        lines.append(f"来源: {followups.get('source_file')} (as_of={followups.get('as_of')})")
        lines.append("| symbol | theme | 触发类型 | 数值 |")
        lines.append("|---|---|---|---:|")
        for item in followups["items"]:
            themes = item.get("themes") or []
            lines.append(
                f"| {item.get('symbol')} | {','.join(themes)} | {item.get('trigger_type')} | {item.get('value')} |"
            )

    confirm = panel.get("watchtower_confirm", {})
    lines.extend(["", "### 确认层裁量(LLM,Phase 2)", confirm.get("note", "")])
    if confirm.get("source_file") is None:
        lines.append(f"missing: {', '.join(confirm.get('flags') or ['no_confirm_output'])}")
    elif not confirm.get("items"):
        lines.append(f"来源: {confirm.get('source_file')} (as_of={confirm.get('as_of')}) — 无确认卡")
    else:
        lines.append(f"来源: {confirm.get('source_file')} (as_of={confirm.get('as_of')})")
        lines.append("| symbol | theme | stance | thesis_status | reasoning |")
        lines.append("|---|---|---|---|---|")
        for item in confirm["items"]:
            lines.append(
                f"| {item.get('symbol')} | {item.get('theme')} | {item.get('stance')} | "
                f"{item.get('thesis_status')} | {item.get('reasoning')} |"
            )
    overseas = panel.get("overseas_reference", {})
    lines.extend(["", "### 海外领先指标(reference-only)", "绝不进打分"])
    if overseas.get("items"):
        for item in overseas["items"]:
            lines.append(f"- {item.get('line')}")
    else:
        flags = overseas.get("flags") or []
        lines.append("暂无" + (f" ({', '.join(flags)})" if flags else ""))
    data_health = panel.get("data_health", {})
    grouped = data_health.get("recent_degradations_by_component") or {}
    lines.extend(
        [
            "",
            "## 数据健康区",
            f"最近{data_health.get('hours', 48)}小时降级: {data_health.get('recent_degradation_count', 0)}",
            "| component | count |",
            "|---|---:|",
        ]
    )
    if grouped:
        for component, count in grouped.items():
            lines.append(f"| {component} | {count} |")
    else:
        lines.append("| - | 0 |")
    flags = data_health.get("active_fake_feature_flags") or {}
    lines.append("FAKE_FEATURE_FLAGS: " + (", ".join(sorted(flags)) if flags else "-"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the M59 postmarket panel.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--as-of", default=None, help="Panel date YYYY-MM-DD; defaults to latest signal date")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--watchtower-output-dir", type=Path, default=DEFAULT_WATCHTOWER_OUTPUT_DIR)
    parser.add_argument(
        "--confirm-output-dir",
        type=Path,
        default=None,
        help="Where to look for m60_confirm_*.json; defaults to --watchtower-output-dir",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    panel = build_panel(
        db_path=args.db,
        as_of=args.as_of,
        universe_path=args.universe,
        watchtower_output_dir=args.watchtower_output_dir,
        confirm_output_dir=args.confirm_output_dir,
    )
    if args.format == "markdown":
        print(render_markdown(panel))
    else:
        print(json.dumps(panel, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
