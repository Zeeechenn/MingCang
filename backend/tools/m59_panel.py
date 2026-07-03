"""Build the read-only M59 postmarket operation panel."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path

DEFAULT_UNIVERSE_PATH = Path("paper_trading/test2_universe.json")
BUY_RECOMMENDATIONS = {"买", "买入", "强买", "考虑买入", "watch/考虑买入"}


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


def _build_risk_warnings(con: sqlite3.Connection, as_of: str, universe_path: Path) -> dict[str, Any]:
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
    return {
        "method": "placeholder_v0:0.6*mom5+0.4*mom20,bottom20pct",
        "items": complete[:n_tail],
        "missing_symbols": missing_symbols,
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
        return {
            "schema_version": "postmarket_panel.v1",
            "header": _build_header(con, resolved_as_of),
            "buy_candidates": _build_buy_candidates(con, resolved_as_of),
            "position_health": _build_position_health(con, resolved_as_of),
            "risk_warnings": _build_risk_warnings(con, resolved_as_of, resolved_universe),
            "review_attribution": _build_review_attribution(con, resolved_as_of),
        }


def render_markdown(panel: dict[str, Any]) -> str:
    header = panel["header"]
    lines = [
        f"# M59 盘后操作面板 ({header['as_of']})",
        "",
        "## 页头",
        f"- 数据新鲜度 prices: {header['freshness']['prices']['value']} ({header['freshness']['prices']['status']})",
        f"- 数据新鲜度 news: {header['freshness']['news']['value']} ({header['freshness']['news']['status']})",
        f"- 数据新鲜度 long_term_labels: {header['freshness']['long_term_labels']['value']} ({header['freshness']['long_term_labels']['status']})",
        f"- 降级 flag: {', '.join(header['degradation_flags'])}",
        f"- 市场 regime: {header['market_regime']['value']} ({header['market_regime']['flag']})",
        "",
        "## ① 买入候选",
        "| symbol | name | score | stop_loss | take_profit | llm_layer |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in panel["buy_candidates"]["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('name') or ''} | {item.get('composite_score')} | "
            f"{item.get('stop_loss')} | {item.get('take_profit')} | {item.get('llm_layer')} |"
        )
    lines.extend(["", "## ② 持仓体检", "| symbol | current | stop distance % | take distance % | missing |", "|---|---:|---:|---:|---|"])
    for item in panel["position_health"]["items"]:
        lines.append(
            f"| {item['symbol']} | {item.get('current_price')} | {item.get('distance_to_stop_loss_pct')} | "
            f"{item.get('distance_to_take_profit_pct')} | {', '.join(item.get('missing') or [])} |"
        )
    lines.extend(["", "## ③ 避雷警示", "预警≠卖出指令", "| symbol | momentum | in_position |", "|---|---:|---|"])
    for item in panel["risk_warnings"]["items"]:
        lines.append(f"| {item['symbol']} | {item.get('momentum_score')} | {item.get('in_position')} |")
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
