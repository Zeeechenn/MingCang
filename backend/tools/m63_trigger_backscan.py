"""M63 trigger backscan harness (zero LLM, read-only DB).

Runs a point-in-time daily replay of M60 watchtower triggers over a fixed
universe and measures which 5-trading-day price-move episodes were observed by
each trigger source. This tool does not write to SQLite and does not call any
LLM provider.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict, deque
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any, TypedDict

from backend.config import default_sqlite_path
from backend.tools.m60_watchtower import (
    CATEGORY_TRIGGER_DAMPER_TRADING_DAYS,
    TRIGGER_FLOW_ANOMALY,
    TRIGGER_LHB_SPOTLIGHT,
    TRIGGER_NEW_HIGH,
    TRIGGER_NEWS,
    TRIGGER_PRICE_PERCENTILE,
    TRIGGER_PRICE_Z,
    TRIGGER_SECTOR_RESONANCE,
    TRIGGER_THESIS_INVALIDATION,
    TRIGGER_THESIS_VALIDATION,
    TRIGGER_VOLUME_RATIO,
    _columns,
    _connect_readonly,
    _table_exists,
    build_watchtower_report_from_entries,
)
from backend.workflows.m63_daily import R6_CHG_1D_PCT, R6_CHG_5D_PCT, R6_DAMPER_DAYS

DEFAULT_UNIVERSE_PATHS = (
    Path("paper_trading/test2_universe.json"),
    Path("paper_trading/biaodi1_universe.json"),
)
DEFAULT_OUTPUT_DIR = Path("paper_trading/m63_out")
SCHEMA_VERSION = "m63_trigger_backscan.v1"
TRIGGER_STEM = "trigger_backscan"
R6_PRODUCTION_LAUNCH_DATE = "2026-07-05"

SOURCE_PRICE_Z = "price_z"


class SourceStats(TypedDict):
    covered_episodes: int
    captured_episodes: int
    captured_trigger_count: int
    capture_rate: float | None
SOURCE_PRICE_PERCENTILE = "price_percentile"
SOURCE_VOLUME_RATIO = "volume_ratio"
SOURCE_NEW_HIGH = "new_high"
SOURCE_SECTOR_RESONANCE = "sector_resonance"
SOURCE_NEWS = "news_trigger"
SOURCE_LHB = "lhb_spotlight"
SOURCE_FLOW = "flow_anomaly"
SOURCE_THESIS_VALIDATION = "thesis_validation"
SOURCE_THESIS_INVALIDATION = "thesis_invalidation"
SOURCE_R6_PRICE_MOVE = "r6_price_move"

PRE_R6_SOURCES = (
    SOURCE_PRICE_Z,
    SOURCE_PRICE_PERCENTILE,
    SOURCE_VOLUME_RATIO,
    SOURCE_NEW_HIGH,
    SOURCE_SECTOR_RESONANCE,
    SOURCE_NEWS,
    SOURCE_LHB,
    SOURCE_FLOW,
    SOURCE_THESIS_VALIDATION,
    SOURCE_THESIS_INVALIDATION,
)

SOURCES = (*PRE_R6_SOURCES, SOURCE_R6_PRICE_MOVE)

TRIGGER_TYPE_TO_SOURCE = {
    TRIGGER_PRICE_Z: SOURCE_PRICE_Z,
    TRIGGER_PRICE_PERCENTILE: SOURCE_PRICE_PERCENTILE,
    TRIGGER_VOLUME_RATIO: SOURCE_VOLUME_RATIO,
    TRIGGER_NEW_HIGH: SOURCE_NEW_HIGH,
    TRIGGER_SECTOR_RESONANCE: SOURCE_SECTOR_RESONANCE,
    TRIGGER_NEWS: SOURCE_NEWS,
    TRIGGER_LHB_SPOTLIGHT: SOURCE_LHB,
    TRIGGER_FLOW_ANOMALY: SOURCE_FLOW,
    TRIGGER_THESIS_VALIDATION: SOURCE_THESIS_VALIDATION,
    TRIGGER_THESIS_INVALIDATION: SOURCE_THESIS_INVALIDATION,
}

DAMPED_SOURCES = {
    SOURCE_LHB,
    SOURCE_FLOW,
    SOURCE_THESIS_VALIDATION,
    SOURCE_THESIS_INVALIDATION,
}

BANNED_MARKDOWN_TERMS = ("买入", "卖出", "加仓", "清仓")


def load_universe(paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS) -> dict[str, dict[str, Any]]:
    universe: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for stock in payload.get("stocks", []):
            symbol = str(stock["symbol"]).strip()
            if not symbol:
                continue
            existing = universe.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": stock.get("name") or "",
                    "sector": stock.get("sector") or "未分组",
                    "origins": [],
                },
            )
            origin = stock.get("origin")
            if origin and origin not in existing["origins"]:
                existing["origins"].append(origin)
            if not existing.get("name") and stock.get("name"):
                existing["name"] = stock["name"]
            if existing.get("sector") == "未分组" and stock.get("sector"):
                existing["sector"] = stock["sector"]
    return universe


def build_universe_entries(universe: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_sector: dict[str, list[str]] = defaultdict(list)
    for symbol, meta in universe.items():
        by_sector[str(meta.get("sector") or "未分组")].append(symbol)
    entries = []
    for index, (sector, symbols) in enumerate(sorted(by_sector.items()), start=1):
        entries.append(
            {
                "theme_key": f"backscan_sector_{index:02d}",
                "title": sector,
                "thesis": "M63 trigger backscan observe-only grouping",
                "symbols": sorted(symbols),
                "validation_conditions": [],
                "invalidation_conditions": [],
                "created_at": "2026-07-03",
                "source_ref": "m63_trigger_backscan",
            }
        )
    return entries


def _placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def _trading_dates(con: sqlite3.Connection, symbols: list[str], start: str, end: str) -> list[str]:
    if not symbols or not _table_exists(con, "prices"):
        return []
    rows = con.execute(
        f"""
        SELECT DISTINCT date
        FROM prices
        WHERE symbol IN ({_placeholders(symbols)})
          AND date(date) >= date(?)
          AND date(date) <= date(?)
        ORDER BY date(date)
        """,
        (*symbols, start, end),
    ).fetchall()
    return [str(row[0])[:10] for row in rows]


def _all_price_rows(con: sqlite3.Connection, symbols: list[str], end: str) -> dict[str, list[dict[str, Any]]]:
    if not symbols or not _table_exists(con, "prices"):
        return {}
    rows = con.execute(
        f"""
        SELECT symbol, date, close
        FROM prices
        WHERE symbol IN ({_placeholders(symbols)})
          AND date(date) <= date(?)
          AND close IS NOT NULL
        ORDER BY symbol, date(date)
        """,
        (*symbols, end),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["symbol"])].append({"date": str(row["date"])[:10], "close": float(row["close"])})
    return grouped


def detect_episodes(
    price_rows_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    start: str,
    end: str,
    threshold_abs_pct: float = 10.0,
    window_trading_days: int = 5,
) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for symbol, rows in sorted(price_rows_by_symbol.items()):
        current: dict[str, Any] | None = None
        previous_hit_index: int | None = None
        for index in range(window_trading_days, len(rows)):
            row = rows[index]
            event_date = row["date"]
            if event_date < start or event_date > end:
                continue
            base = rows[index - window_trading_days]["close"]
            close = row["close"]
            if base == 0:
                continue
            return_pct = (close / base - 1.0) * 100.0
            if abs(return_pct) < threshold_abs_pct:
                if current is not None:
                    episodes.append(current)
                    current = None
                    previous_hit_index = None
                continue
            if current is None or previous_hit_index is None or index != previous_hit_index + 1:
                if current is not None:
                    episodes.append(current)
                current = {
                    "episode_id": f"{symbol}:{event_date}",
                    "symbol": symbol,
                    "start_date": event_date,
                    "end_date": event_date,
                    "direction": "up" if return_pct > 0 else "down",
                    "peak_return_pct": return_pct,
                    "event_dates": [event_date],
                }
            else:
                current["end_date"] = event_date
                current["event_dates"].append(event_date)
                if abs(return_pct) > abs(float(current["peak_return_pct"])):
                    current["peak_return_pct"] = return_pct
                    current["direction"] = "up" if return_pct > 0 else "down"
            previous_hit_index = index
        if current is not None:
            episodes.append(current)
    return episodes


def _source_window_from_table(
    con: sqlite3.Connection,
    table: str,
    date_col: str,
    *,
    symbols: list[str] | None = None,
    min_count: int = 1,
) -> dict[str, Any]:
    if not _table_exists(con, table) or date_col not in _columns(con, table):
        return {"status": "missing_table", "start": None, "end": None, "row_count": 0}
    params: list[Any] = []
    symbol_filter = ""
    cols = _columns(con, table)
    if symbols and "symbol" in cols:
        symbol_filter = f"WHERE symbol IN ({_placeholders(symbols)})"
        params.extend(symbols)
    row = con.execute(
        f"SELECT COUNT(*), MIN(date({date_col})), MAX(date({date_col})) FROM {table} {symbol_filter}",
        params,
    ).fetchone()
    count = int(row[0] or 0)
    status = "ok" if count >= min_count and row[1] and row[2] else "no_coverage"
    return {"status": status, "start": row[1], "end": row[2], "row_count": count}


def _nth_trading_date(rows: list[sqlite3.Row], offset: int) -> str | None:
    if len(rows) <= offset:
        return None
    return str(rows[offset][0])[:10]


def compute_source_coverage(con: sqlite3.Connection, symbols: list[str]) -> dict[str, dict[str, Any]]:
    price_window = _source_window_from_table(con, "prices", "date", symbols=symbols)
    if price_window["status"] == "ok":
        rows = con.execute(
            f"""
            SELECT DISTINCT date
            FROM prices
            WHERE symbol IN ({_placeholders(symbols)})
            ORDER BY date(date)
            """,
            symbols,
        ).fetchall()
        price_window = {**price_window, "first_effective_date": _nth_trading_date(rows, 1)}
        distribution_window = {**price_window, "first_effective_date": _nth_trading_date(rows, 31)}
        volume_window = {**price_window, "first_effective_date": _nth_trading_date(rows, 10)}
        new_high_window = {**price_window, "first_effective_date": _nth_trading_date(rows, 10)}
    else:
        distribution_window = dict(price_window)
        volume_window = dict(price_window)
        new_high_window = dict(price_window)

    news_window = _source_window_from_table(con, "news", "published_at", symbols=symbols)
    lhb_window = _source_window_from_table(con, "lhb_records", "trade_date", symbols=symbols)
    flow_window = _source_window_from_table(con, "fund_flows", "trade_date", symbols=symbols, min_count=20)
    thesis_window = _source_window_from_table(con, "forward_theses", "updated_at")

    coverage = {
        SOURCE_PRICE_Z: distribution_window,
        SOURCE_PRICE_PERCENTILE: distribution_window,
        SOURCE_VOLUME_RATIO: volume_window,
        SOURCE_NEW_HIGH: new_high_window,
        SOURCE_SECTOR_RESONANCE: price_window,
        SOURCE_NEWS: news_window,
        SOURCE_LHB: lhb_window,
        SOURCE_FLOW: flow_window,
        SOURCE_THESIS_VALIDATION: thesis_window,
        SOURCE_THESIS_INVALIDATION: thesis_window,
        SOURCE_R6_PRICE_MOVE: {**price_window, "first_effective_date": _nth_trading_date(rows, 5)} if price_window["status"] == "ok" else dict(price_window),
    }
    for source, item in coverage.items():
        effective = item.get("first_effective_date") or item.get("start")
        item["effective_start"] = effective
        item["source"] = source
    if coverage[SOURCE_FLOW]["status"] != "ok":
        coverage[SOURCE_FLOW]["status"] = "no_coverage"
    return coverage


def _episode_capture_window(
    episode: dict[str, Any],
    trading_dates: list[str],
    date_index: dict[str, int],
    lookback_days: int = 3,
) -> tuple[str, str, list[str]]:
    start_idx = date_index[episode["start_date"]]
    window_start = trading_dates[max(0, start_idx - lookback_days)]
    end_idx = date_index[episode["end_date"]]
    return window_start, episode["end_date"], trading_dates[max(0, start_idx - lookback_days): end_idx + 1]


def _episode_in_coverage(episode: dict[str, Any], coverage: dict[str, Any], window_start: str, window_end: str) -> bool:
    if coverage.get("status") != "ok":
        return False
    start = coverage.get("effective_start") or coverage.get("start")
    end = coverage.get("end")
    if not start or not end:
        return False
    return window_end >= start and window_start <= end


def replay_triggers(
    *,
    con: sqlite3.Connection,
    entries: list[dict[str, Any]],
    symbols: list[str],
    trading_dates: list[str],
    db_path: Path,
) -> dict[str, dict[str, set[str]]]:
    triggered: dict[str, dict[str, set[str]]] = {
        symbol: {source: set() for source in SOURCES} for symbol in symbols
    }
    dampers: dict[tuple[str, str], deque[int]] = defaultdict(deque)
    for day_index, as_of in enumerate(trading_dates):
        report = build_watchtower_report_from_entries(
            entries=entries,
            watchlist_errors=[],
            db_path=db_path,
            as_of=as_of,
            watchlist_dir="m63_trigger_backscan",
        )
        for trigger in report["triggers"]:
            source = TRIGGER_TYPE_TO_SOURCE.get(str(trigger.get("trigger_type")))
            symbol = str(trigger.get("symbol") or "")
            if source is None or symbol not in triggered:
                continue
            key = (symbol, source)
            if source in DAMPED_SOURCES:
                recent = dampers[key]
                while recent and day_index - recent[0] > CATEGORY_TRIGGER_DAMPER_TRADING_DAYS:
                    recent.popleft()
                if recent:
                    continue
                recent.append(day_index)
            triggered[symbol][source].add(as_of)
    r6_triggered = replay_r6_price_move_triggers(con=con, symbols=symbols, trading_dates=trading_dates)
    for symbol, dates in r6_triggered.items():
        if symbol in triggered:
            triggered[symbol][SOURCE_R6_PRICE_MOVE].update(dates)
    return triggered


def replay_r6_price_move_triggers(
    *,
    con: sqlite3.Connection,
    symbols: list[str],
    trading_dates: list[str],
) -> dict[str, set[str]]:
    if not trading_dates:
        return {symbol: set() for symbol in symbols}
    date_index = {date_value: idx for idx, date_value in enumerate(trading_dates)}
    price_rows = _all_price_rows(con, symbols, trading_dates[-1])
    triggered: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    last_trigger_index: dict[str, int] = {}
    for symbol, rows in price_rows.items():
        for index, row in enumerate(rows):
            as_of = row["date"]
            if as_of not in date_index or index < 1:
                continue
            close = float(row["close"])
            previous = float(rows[index - 1]["close"])
            if previous == 0:
                continue
            chg_1d = (close / previous - 1.0) * 100.0
            chg_5d = None
            if index >= 5:
                five_day_base = float(rows[index - 5]["close"])
                if five_day_base != 0:
                    chg_5d = (close / five_day_base - 1.0) * 100.0
            if abs(chg_1d) < R6_CHG_1D_PCT and (chg_5d is None or abs(chg_5d) < R6_CHG_5D_PCT):
                continue
            day_index = date_index[as_of]
            previous_trigger = last_trigger_index.get(symbol)
            if previous_trigger is not None and day_index - previous_trigger <= R6_DAMPER_DAYS:
                continue
            triggered.setdefault(symbol, set()).add(as_of)
            last_trigger_index[symbol] = day_index
    return triggered


def summarize_backscan(
    *,
    episodes: list[dict[str, Any]],
    triggered_by_symbol: dict[str, dict[str, set[str]]],
    trading_dates: list[str],
    coverage: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    date_index = {date_value: idx for idx, date_value in enumerate(trading_dates)}
    source_stats: dict[str, SourceStats] = {
        source: {"covered_episodes": 0, "captured_episodes": 0, "captured_trigger_count": 0, "capture_rate": None}
        for source in SOURCES
    }
    lag_values: dict[str, list[int]] = {source: [] for source in SOURCES}
    misses: list[dict[str, Any]] = []
    captured_any_count = 0
    pre_r6_captured_any_count = 0
    any_covered_count = 0
    pre_r6_any_covered_count = 0

    for episode in episodes:
        window_start, window_end, window_dates = _episode_capture_window(episode, trading_dates, date_index)
        source_status: dict[str, dict[str, Any]] = {}
        any_covered = False
        any_captured = False
        pre_r6_any_covered = False
        pre_r6_any_captured = False
        for source in SOURCES:
            is_covered = _episode_in_coverage(episode, coverage[source], window_start, window_end)
            hits = sorted(triggered_by_symbol.get(episode["symbol"], {}).get(source, set()).intersection(window_dates))
            captured = bool(is_covered and hits)
            first_lag = date_index[hits[0]] - date_index[episode["start_date"]] if captured else None
            source_status[source] = {
                "covered": is_covered,
                "captured": captured,
                "trigger_dates": hits,
                "first_trigger_lag": first_lag,
                "coverage_status": coverage[source]["status"],
            }
            if is_covered:
                any_covered = True
                source_stats[source]["covered_episodes"] += 1
                if captured:
                    source_stats[source]["captured_episodes"] += 1
            if captured:
                any_captured = True
                source_stats[source]["captured_trigger_count"] += len(hits)
                assert first_lag is not None
                lag_values[source].append(int(first_lag))
            if source in PRE_R6_SOURCES:
                pre_r6_any_covered = pre_r6_any_covered or is_covered
                pre_r6_any_captured = pre_r6_any_captured or captured
        if any_covered:
            any_covered_count += 1
            if any_captured:
                captured_any_count += 1
            else:
                misses.append(
                    {
                        **episode,
                        "capture_window_start": window_start,
                        "capture_window_end": window_end,
                        "source_status": source_status,
                    }
                )
        if pre_r6_any_covered:
            pre_r6_any_covered_count += 1
            if pre_r6_any_captured:
                pre_r6_captured_any_count += 1

    for stats in source_stats.values():
        denom = stats["covered_episodes"]
        stats["capture_rate"] = (stats["captured_episodes"] / denom) if denom else None

    missed = any_covered_count - captured_any_count
    pre_r6_missed = pre_r6_any_covered_count - pre_r6_captured_any_count
    miss_by_direction = Counter(item["direction"] for item in misses)
    miss_by_month = Counter(item["start_date"][:7] for item in misses)
    miss_by_band = Counter(_amplitude_band(abs(float(item["peak_return_pct"]))) for item in misses)
    return {
        "episodes_total": len(episodes),
        "episodes_with_any_source_coverage": any_covered_count,
        "captured_by_any_source": captured_any_count,
        "missed_by_all_sources": missed,
        "overall_miss_rate": (missed / any_covered_count) if any_covered_count else None,
        "pre_r6_stack": {
            "episodes_with_any_source_coverage": pre_r6_any_covered_count,
            "captured_by_any_source": pre_r6_captured_any_count,
            "missed_by_all_sources": pre_r6_missed,
            "overall_miss_rate": (pre_r6_missed / pre_r6_any_covered_count) if pre_r6_any_covered_count else None,
        },
        "current_stack": {
            "episodes_with_any_source_coverage": any_covered_count,
            "captured_by_any_source": captured_any_count,
            "missed_by_all_sources": missed,
            "overall_miss_rate": (missed / any_covered_count) if any_covered_count else None,
        },
        "per_source": source_stats,
        "capture_lag": {source: _lag_summary(values) for source, values in lag_values.items()},
        "missed_episodes": misses,
        "miss_distribution": {
            "by_direction": dict(sorted(miss_by_direction.items())),
            "by_amplitude_band": dict(sorted(miss_by_band.items())),
            "by_month": dict(sorted(miss_by_month.items())),
        },
    }


def _lag_summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "median": None, "p90": None}
    ordered = sorted(values)
    mid = len(ordered) // 2
    median: int | float
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / 2
    p90_index = max(0, ceil(len(ordered) * 0.9) - 1)
    return {"count": len(ordered), "median": median, "p90": ordered[p90_index]}


def _amplitude_band(value: float) -> str:
    if value < 15:
        return "10-15%"
    if value < 20:
        return "15-20%"
    if value < 30:
        return "20-30%"
    return "30%+"


def build_backscan_report(
    *,
    db_path: str | Path | None,
    start: str,
    end: str,
    universe_paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS,
) -> dict[str, Any]:
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    universe = load_universe(universe_paths)
    symbols = sorted(universe)
    entries = build_universe_entries(universe)
    with _connect_readonly(resolved_db) as con:
        trading_dates = _trading_dates(con, symbols, start, end)
        price_rows = _all_price_rows(con, symbols, end)
        episodes = detect_episodes(price_rows, start=start, end=end)
        coverage = compute_source_coverage(con, symbols)
        triggered = replay_triggers(
            con=con,
            entries=entries,
            symbols=symbols,
            trading_dates=trading_dates,
            db_path=resolved_db,
        )
        summary = summarize_backscan(
            episodes=episodes,
            triggered_by_symbol=triggered,
            trading_dates=trading_dates,
            coverage=coverage,
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(resolved_db),
        "start": start,
        "end": end,
        "universe_paths": [str(path) for path in universe_paths],
        "universe_size": len(symbols),
        "symbols": symbols,
        "trading_dates": {"count": len(trading_dates), "start": trading_dates[0] if trading_dates else None, "end": trading_dates[-1] if trading_dates else None},
        "coverage": coverage,
        "episodes": episodes,
        "meta": {
            "r6_price_move": {
                "production_launch_date": R6_PRODUCTION_LAUNCH_DATE,
                "historical_replay_note": "R6 生产上线日=2026-07-05，历史回放为反事实评估",
                "chg_5d_pct": R6_CHG_5D_PCT,
                "chg_1d_pct": R6_CHG_1D_PCT,
                "damper_trading_days": R6_DAMPER_DAYS,
            }
        },
        "summary": summary,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# M63 Trigger Backscan ({report['start']} to {report['end']})",
        "",
        "Observe-only replay. This report measures historical trigger visibility and blind spots.",
        "",
        "## Summary",
        "",
        f"- Universe symbols: {report['universe_size']}",
        f"- Trading dates replayed: {report['trading_dates']['count']}",
        f"- Episodes total: {summary['episodes_total']}",
        f"- Episodes with at least one source coverage: {summary['episodes_with_any_source_coverage']}",
        f"- Overall miss rate: {_format_rate(summary['overall_miss_rate'])}",
        f"- pre-R6 stack overall miss rate: {_format_rate(summary['pre_r6_stack']['overall_miss_rate'])}",
        f"- current stack overall miss rate: {_format_rate(summary['current_stack']['overall_miss_rate'])}",
        f"- R6 production launch date: {report['meta']['r6_price_move']['production_launch_date']}; historical replay is counterfactual.",
        "",
        "## Per-source Coverage",
        "",
        "| source | status | start | effective_start | end | rows |",
        "|---|---|---|---|---|---:|",
    ]
    for source in SOURCES:
        item = report["coverage"][source]
        lines.append(
            f"| {source} | {item.get('status')} | {item.get('start')} | "
            f"{item.get('effective_start')} | {item.get('end')} | {item.get('row_count')} |"
        )

    lines.extend([
        "",
        "## Per-source Capture",
        "",
        "| source | covered episodes | observed episodes | capture rate |",
        "|---|---:|---:|---:|",
    ])
    for source in SOURCES:
        item = summary["per_source"][source]
        lines.append(
            f"| {source} | {item['covered_episodes']} | {item['captured_episodes']} | "
            f"{_format_rate(item['capture_rate'])} |"
        )

    lines.extend([
        "",
        "## Capture Lag",
        "",
        "| source | captured episodes | median lag | p90 lag |",
        "|---|---:|---:|---:|",
    ])
    for source in SOURCES:
        item = summary["capture_lag"][source]
        lines.append(
            f"| {source} | {item['count']} | {_format_lag(item['median'])} | {_format_lag(item['p90'])} |"
        )

    lines.extend([
        "",
        "## Miss Distribution",
        "",
        f"- Direction: {summary['miss_distribution']['by_direction']}",
        f"- Amplitude band: {summary['miss_distribution']['by_amplitude_band']}",
        f"- Month: {summary['miss_distribution']['by_month']}",
        "",
        "## Missed Episodes",
        "",
    ])
    misses = summary["missed_episodes"]
    if not misses:
        lines.append("No missed episodes under the current coverage accounting.")
    else:
        lines.append("| symbol | start | end | direction | peak_return_pct | source window status |")
        lines.append("|---|---|---|---|---:|---|")
        for episode in misses:
            source_bits = []
            for source in SOURCES:
                status = episode["source_status"][source]
                if status["captured"]:
                    label = "observed"
                elif status["covered"]:
                    label = "covered-no-hit"
                else:
                    label = f"outside-{status['coverage_status']}"
                source_bits.append(f"{source}:{label}")
            lines.append(
                f"| {episode['symbol']} | {episode['start_date']} | {episode['end_date']} | "
                f"{episode['direction']} | {float(episode['peak_return_pct']):.2f} | "
                f"{'; '.join(source_bits)} |"
            )
    markdown = "\n".join(lines)
    for term in BANNED_MARKDOWN_TERMS:
        if term in markdown:
            raise ValueError(f"markdown contains banned operation term: {term}")
    return markdown


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def _format_lag(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def output_paths(end: str, out_dir: Path) -> tuple[Path, Path]:
    stem = f"{TRIGGER_STEM}_{end.replace('-', '')}"
    return out_dir / f"{stem}.json", out_dir / f"{stem}.md"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run M63 zero-LLM trigger backscan.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args(argv)

    report = build_backscan_report(db_path=args.db, start=args.start, end=args.end)
    markdown = render_markdown(report)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = output_paths(args.end, args.out_dir)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(
        "episodes={episodes} miss_rate={miss_rate}".format(
            episodes=report["summary"]["episodes_total"],
            miss_rate=_format_rate(report["summary"]["overall_miss_rate"]),
        )
    )


if __name__ == "__main__":
    main()
