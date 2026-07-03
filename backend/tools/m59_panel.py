"""Build the read-only M59 postmarket operation panel."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backend.config import default_sqlite_path
from backend.tools.m58_grid_backtest import regime_from_pool_equal_weight

DEFAULT_UNIVERSE_PATH = Path("paper_trading/test2_universe.json")
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


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
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


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
                "research_reference": _build_research_reference(con, symbol, as_of),
            }
        )
    return {"items": items, "flags": flags}


def _build_position_health(con: sqlite3.Connection, as_of: str) -> dict[str, Any]:
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
        missing = []
        if current is None:
            missing.append("missing:price")
        if stop_loss is None:
            missing.append("missing:stop_loss")
        if take_profit is None:
            missing.append("missing:take_profit")

        stop_distance = None
        take_distance = None
        if current not in (None, 0):
            if stop_loss is not None:
                stop_distance = _pct((current - stop_loss) / current)
            if take_profit is not None:
                take_distance = _pct((take_profit - current) / current)

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
            {"symbol": entry["symbol"], "name": entry["name"], "weight_pct": entry["weight_pct"]}
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

    return {
        "section_name": "风险工程区",
        "market_regime": regime,
        "momentum_tail": {
            "method": "placeholder_v0:0.6*mom5+0.4*mom20,bottom20pct",
            "items": complete[:n_tail],
            "missing_symbols": missing_symbols,
            "regime_reliable": regime_reliable,
            "note": MOMENTUM_TAIL_REGIME_NOTE,
        },
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
    text = (
        f"今日候选{candidates_count}只/"
        f"持仓{position_count}只其中{near_stop_loss_count}只贴近止损/"
        f"风险提示{risk_warning_count}条"
    )
    return {
        "candidates_count": candidates_count,
        "position_count": position_count,
        "near_stop_loss_count": near_stop_loss_count,
        "near_stop_loss_symbols": [item["symbol"] for item in near_stop_loss],
        "risk_warning_count": risk_warning_count,
        "text": text,
    }


def build_panel(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
) -> dict[str, Any]:
    """Return a postmarket_panel.v1 payload without writing the database."""
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    resolved_universe = Path(universe_path)
    with _connect_readonly(resolved_db) as con:
        resolved_as_of = _latest_as_of(con, as_of)
        buy_candidates = _build_buy_candidates(con, resolved_as_of)
        position_health = _build_position_health(con, resolved_as_of)
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
        }


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
        "| symbol | name | score | stop_loss | take_profit | llm_layer | 研究参考 |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for item in panel["buy_candidates"]["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('name') or ''} | {item.get('composite_score')} | "
            f"{item.get('stop_loss')} | {item.get('take_profit')} | {item.get('llm_layer')} | "
            f"{_format_research_reference(item.get('research_reference'))} |"
        )
    lines.extend(
        [
            "",
            "## ② 持仓体检",
            "| symbol | current | stop distance % | take distance % | missing | 研究参考 |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for item in panel["position_health"]["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('current_price')} | {item.get('distance_to_stop_loss_pct')} | "
            f"{item.get('distance_to_take_profit_pct')} | {', '.join(item.get('missing') or [])} | "
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
            f"动量末档:{momentum_tail['note']} (regime_reliable={momentum_tail['regime_reliable']})",
            "预警≠卖出指令",
            "| symbol | momentum | in_position |",
            "|---|---:|---|",
        ]
    )
    for item in momentum_tail["items"]:
        lines.append(f"| {item['symbol']} | {item.get('momentum_score')} | {item.get('in_position')} |")
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
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the M59 postmarket panel.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--as-of", default=None, help="Panel date YYYY-MM-DD; defaults to latest signal date")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    panel = build_panel(db_path=args.db, as_of=args.as_of, universe_path=args.universe)
    if args.format == "markdown":
        print(render_markdown(panel))
    else:
        print(json.dumps(panel, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
