"""Refresh close-confirmed M29 price coverage for the test3 universe.

This is a narrow M29.3 helper for preparing future forward-shadow evidence. It
only refreshes `prices` rows for an explicit date window and requires
`--execute` before writing the SQLite DB. It does not run signals, write
sentiment_cache, call LLMs, train models, or change production configuration.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.data.database import Price, SessionLocal, Stock
from backend.data.market import fetch_daily
from backend.tools.m27_alpha_diagnostic import _load_universe_symbols
from backend.tools.m27_test3_production_profile_ab import DEFAULT_UNIVERSE_PATH

DEFAULT_JSON_OUTPUT = Path("/private/tmp/m29_price_coverage_refresh.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/m29_price_coverage_refresh.md")

logger = logging.getLogger(__name__)


def _validate_window(
    start: str,
    end: str,
    *,
    allow_today: bool = False,
    today: date | None = None,
) -> tuple[date, date]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("--start must be on or before --end")
    current = today or date.today()
    if end_date >= current and not allow_today:
        raise ValueError("--end must be before today unless --allow-today is set")
    return start_date, end_date


def _normalize_index_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "date" in out.columns:
        out = out.set_index("date")
    out.index = pd.to_datetime(out.index, errors="coerce").strftime("%Y-%m-%d")
    out = out[out.index.notna()]
    return out.sort_index()


def price_record_payloads(symbol: str, df: pd.DataFrame, *, start: str, end: str) -> list[dict[str, Any]]:
    """Convert fetched OHLCV rows into Price constructor payloads for a window."""
    if df.empty:
        return []
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")
    with_factors = add_all_factors(_normalize_index_dates(df))
    window = with_factors[(with_factors.index >= start) & (with_factors.index <= end)]
    payloads: list[dict[str, Any]] = []
    for date_str, row in window.iterrows():
        if any(pd.isna(row.get(column)) for column in ("open", "high", "low", "close", "volume")):
            continue
        atr = row.get("atr14")
        payloads.append({
            "symbol": symbol,
            "date": str(date_str),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "atr14": float(atr) if atr is not None and not pd.isna(atr) else None,
            "source": source,
            "fetched_at": fetched_at,
            "adjustment": adjustment,
        })
    return payloads


def _existing_window_summary(db: Any, symbol: str, *, start: str, end: str) -> dict[str, Any]:
    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date >= start, Price.date <= end)
        .all()
    )
    provenance_complete = [
        row for row in rows if row.source and row.fetched_at and row.adjustment
    ]
    return {
        "rows": len(rows),
        "provenance_complete_rows": len(provenance_complete),
        "dates": sorted(row.date for row in rows),
    }


def _stock_lookup(db: Any, symbols: set[str]) -> dict[str, Stock]:
    rows = db.query(Stock).filter(Stock.symbol.in_(symbols)).all()
    return {str(row.symbol): row for row in rows}


def run_refresh(
    *,
    start: str,
    end: str,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    execute: bool = False,
    allow_today: bool = False,
    symbol_limit: int | None = None,
    sleep_seconds: float = 0.2,
    fetch_days: int | None = None,
) -> dict[str, Any]:
    start_date, end_date = _validate_window(start, end, allow_today=allow_today)
    symbols = sorted(_load_universe_symbols(universe_path))
    if symbol_limit is not None:
        symbols = symbols[:symbol_limit]
    calculated_fetch_days = fetch_days or max((date.today() - start_date).days + 10, 30)

    db = SessionLocal()
    try:
        stocks = _stock_lookup(db, set(symbols))
        symbol_reports: list[dict[str, Any]] = []
        rows_written = 0
        rows_planned = 0
        symbols_with_errors = 0
        for symbol in symbols:
            stock = stocks.get(symbol)
            market = str(stock.market) if stock else "CN"
            before = _existing_window_summary(db, symbol, start=start, end=end)
            report = {
                "symbol": symbol,
                "market": market,
                "before": before,
                "provider_rows": 0,
                "provider_source": None,
                "provider_adjustment": None,
                "planned_dates": [],
                "rows_written": 0,
                "error": None,
            }
            try:
                df = fetch_daily(symbol, market, days=calculated_fetch_days)
                report["provider_source"] = df.attrs.get("source")
                report["provider_adjustment"] = df.attrs.get("adjustment")
                payloads = price_record_payloads(symbol, df, start=start, end=end)
                report["provider_rows"] = len(df)
                report["planned_dates"] = [payload["date"] for payload in payloads]
                rows_planned += len(payloads)
                if execute and payloads:
                    dates = [payload["date"] for payload in payloads]
                    db.query(Price).filter(
                        Price.symbol == symbol,
                        Price.date.in_(dates),
                    ).delete(synchronize_session=False)
                    db.bulk_save_objects(Price(**payload) for payload in payloads)
                    db.commit()
                    report["rows_written"] = len(payloads)
                    rows_written += len(payloads)
            except Exception as exc:
                db.rollback()
                symbols_with_errors += 1
                report["error"] = str(exc)
                logger.warning("M29 price refresh failed %s: %s", symbol, exc)
            symbol_reports.append(report)
            if sleep_seconds:
                time.sleep(sleep_seconds)

        after_ready_dates = _complete_window_dates(db, set(symbols), start=start, end=end)
        return {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "schema_version": "m29_price_coverage_refresh.v1",
            "milestone": "M29.3",
            "purpose": "close-confirmed price/provenance refresh for M29 forward evidence readiness",
            "run_mode": "execute" if execute else "dry_run",
            "production_unchanged": True,
            "writes_db": execute,
            "writes_tables": ["prices"] if execute else [],
            "calls_market_data_provider": True,
            "calls_llm_or_api": False,
            "writes_sentiment_cache": False,
            "trains_model": False,
            "saves_model": False,
            "universe_path": str(universe_path.expanduser()),
            "universe_symbols": len(symbols),
            "window": {"start": start, "end": end, "allow_today": allow_today},
            "fetch_days": calculated_fetch_days,
            "summary": {
                "symbols_attempted": len(symbols),
                "symbols_with_errors": symbols_with_errors,
                "rows_planned": rows_planned,
                "rows_written": rows_written,
                "complete_window_dates_after": after_ready_dates,
            },
            "symbols": symbol_reports,
            "stop_conditions": [
                "do not refresh today's partial bar unless --allow-today is explicitly set",
                "do not write sentiment_cache",
                "do not call LLM/API",
                "do not train or save a model",
                "do not change production config",
                "do not treat refreshed prices as promotion evidence",
            ],
        }
    finally:
        db.close()


def _complete_window_dates(db: Any, symbols: set[str], *, start: str, end: str) -> list[str]:
    if not symbols:
        return []
    rows = (
        db.query(Price.date, Price.symbol, Price.source, Price.fetched_at, Price.adjustment)
        .filter(Price.symbol.in_(symbols), Price.date >= start, Price.date <= end)
        .all()
    )
    by_date: dict[str, set[str]] = {}
    for row in rows:
        if not (row.source and row.fetched_at and row.adjustment):
            continue
        by_date.setdefault(str(row.date), set()).add(str(row.symbol))
    return sorted(date_str for date_str, date_symbols in by_date.items() if date_symbols >= symbols)


def report_to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# M29 Price Coverage Refresh",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- writes_tables: {', '.join(report['writes_tables']) or 'none'}",
        f"- calls_market_data_provider: {report['calls_market_data_provider']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- writes_sentiment_cache: {report['writes_sentiment_cache']}",
        f"- window: {report['window']['start']} to {report['window']['end']}",
        f"- universe_symbols: {report['universe_symbols']}",
        "",
        "## Summary",
        "",
        f"- symbols_attempted: {summary['symbols_attempted']}",
        f"- symbols_with_errors: {summary['symbols_with_errors']}",
        f"- rows_planned: {summary['rows_planned']}",
        f"- rows_written: {summary['rows_written']}",
        f"- complete_window_dates_after: {', '.join(summary['complete_window_dates_after']) or 'none'}",
        "",
        "## Errors",
        "",
    ]
    errors = [row for row in report["symbols"] if row.get("error")]
    if errors:
        lines.extend(f"- {row['symbol']}: {row['error']}" for row in errors[:20])
    else:
        lines.append("- none")
    lines.extend(["", "## Stop Conditions", ""])
    lines.extend(f"- {item}" for item in report["stop_conditions"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="Close-confirmed window start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Close-confirmed window end date, YYYY-MM-DD")
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--execute", action="store_true", help="Actually replace/write prices rows")
    parser.add_argument("--allow-today", action="store_true", help="Permit --end to be today")
    parser.add_argument("--symbol-limit", type=int)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--fetch-days", type=int)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    report = run_refresh(
        start=args.start,
        end=args.end,
        universe_path=args.universe_path,
        execute=args.execute,
        allow_today=args.allow_today,
        symbol_limit=args.symbol_limit,
        sleep_seconds=args.sleep,
        fetch_days=args.fetch_days,
    )
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
