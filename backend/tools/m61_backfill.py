"""M61 Phase 2 B6a category backfill CLI."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from backend.data.category_fetchers import (  # noqa: F401
    save_announcements,
    save_corporate_events,
    save_holder_snapshots,
    save_lhb,
    save_research_reports,
)
from backend.data.category_registry import FetchRequest, fetch_by_category
from backend.data.degradation import emit_degradation
from backend.data.orm import Base
from backend.data.database import SessionLocal

logger = logging.getLogger(__name__)

SAVE_HELPERS = {
    "announcements": save_announcements,
    "research_reports": save_research_reports,
    "lhb": save_lhb,
    "corporate_events": save_corporate_events,
    "holders": save_holder_snapshots,
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill M61 category provider data.")
    parser.add_argument(
        "--category",
        required=True,
        choices=("announcements", "research_reports", "lhb", "corporate_events", "holders"),
    )
    parser.add_argument("--universe", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit-stocks", type=int, default=None)
    return parser.parse_args(argv)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _load_universe(path: str, limit: int | None) -> list[dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    stocks = []
    for item in payload.get("stocks", []):
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        stocks.append({"symbol": symbol, "name": str(item.get("name") or "").strip()})
    return stocks[:limit] if limit is not None else stocks


def _ten_day_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=9), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _quarter_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows = []
    current = start
    while current <= end:
        quarter_end_month = ((current.month - 1) // 3 + 1) * 3
        next_month = quarter_end_month + 1
        next_year = current.year
        if next_month == 13:
            next_month = 1
            next_year += 1
        quarter_end = date(next_year, next_month, 1) - timedelta(days=1)
        window_end = min(quarter_end, end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _record_degradation(category: str, provider: str, error: str, context: dict, db) -> dict:
    emit_degradation("m61_backfill", category, provider, error, context=context, db=db)
    event = {"category": category, "provider": provider, "error": error}
    event.update(context)
    return event


def _backfill_lhb(stocks: list[dict[str, str]], start: date, end: date, db) -> tuple[int, list[dict]]:
    symbols = {row["symbol"] for row in stocks}
    degradations: list[dict] = []
    result = fetch_by_category("lhb", FetchRequest(symbol=None, start=start, end=end), db=db)
    degradations.extend(result.degradations)
    if not result.ok:
        return 0, degradations
    rows = [row for row in result.rows if row.get("symbol") in symbols]
    inserted = 0
    for symbol in sorted({row["symbol"] for row in rows}):
        try:
            inserted += save_lhb([row for row in rows if row["symbol"] == symbol], db)
        except Exception as exc:  # noqa: BLE001 - per-symbol resilience
            db.rollback()
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("lhb save failed for %s: %s", symbol, error)
            degradations.append(
                _record_degradation("lhb", result.provider or "akshare_lhb", error, {"symbol": symbol}, db)
            )
    return inserted, degradations


def _backfill_stock_category(
    category: str,
    stocks: list[dict[str, str]],
    start: date,
    end: date,
    db,
) -> tuple[int, list[dict]]:
    inserted = 0
    degradations: list[dict] = []
    saver = SAVE_HELPERS[category]
    windows = _ten_day_windows(start, end) if category == "announcements" else [(start, end)]

    for stock in stocks:
        symbol = stock["symbol"]
        for window_start, window_end in windows:
            try:
                result = fetch_by_category(
                    category,
                    FetchRequest(
                        symbol=symbol,
                        start=window_start,
                        end=window_end,
                        limit=20 if category == "announcements" else 50,
                        extra={"name": stock.get("name") or symbol},
                    ),
                    db=db,
                )
                degradations.extend(result.degradations)
                if not result.ok:
                    degradations.append(
                        _record_degradation(
                            category,
                            result.provider or category,
                            "fetch_failed",
                            {
                                "symbol": symbol,
                                "start": window_start.isoformat(),
                                "end": window_end.isoformat(),
                            },
                            db,
                        )
                    )
                    continue
                inserted += saver(result.rows, db)
            except Exception as exc:  # noqa: BLE001 - per-stock resilience
                db.rollback()
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("%s backfill failed for %s: %s", category, symbol, error)
                degradations.append(
                    _record_degradation(
                        category,
                        category,
                        error,
                        {
                            "symbol": symbol,
                            "start": window_start.isoformat(),
                            "end": window_end.isoformat(),
                        },
                        db,
                    )
                )
    return inserted, degradations


def _fetch_stock_category_once(
    category: str,
    stock: dict[str, str],
    start: date,
    end: date,
    db,
):
    return fetch_by_category(
        category,
        FetchRequest(
            symbol=stock["symbol"],
            start=start,
            end=end,
            limit=50,
            extra={"name": stock.get("name") or stock["symbol"]},
        ),
        db=db,
    )


def _backfill_corporate_events(
    stocks: list[dict[str, str]],
    start: date,
    end: date,
    db,
) -> tuple[int, list[dict]]:
    inserted = 0
    degradations: list[dict] = []

    for stock in stocks:
        symbol = stock["symbol"]
        try:
            result = _fetch_stock_category_once("corporate_events", stock, start, end, db)
            degradations.extend(result.degradations)
            if not result.ok:
                degradations.append(
                    _record_degradation(
                        "corporate_events",
                        result.provider or "corporate_events",
                        "fetch_failed",
                        {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat()},
                        db,
                    )
                )
                continue
            if len(result.rows) < 10:
                inserted += save_corporate_events(result.rows, db)
                continue

            for window_start, window_end in _quarter_windows(start, end):
                split_result = _fetch_stock_category_once("corporate_events", stock, window_start, window_end, db)
                degradations.extend(split_result.degradations)
                if not split_result.ok:
                    degradations.append(
                        _record_degradation(
                            "corporate_events",
                            split_result.provider or "corporate_events",
                            "fetch_failed",
                            {
                                "symbol": symbol,
                                "start": window_start.isoformat(),
                                "end": window_end.isoformat(),
                            },
                            db,
                        )
                    )
                    continue
                inserted += save_corporate_events(split_result.rows, db)
        except Exception as exc:  # noqa: BLE001 - per-stock resilience
            db.rollback()
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("corporate_events backfill failed for %s: %s", symbol, error)
            degradations.append(
                _record_degradation(
                    "corporate_events",
                    "corporate_events",
                    error,
                    {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat()},
                    db,
                )
            )
    return inserted, degradations


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stocks = _load_universe(args.universe, args.limit_stocks)
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
        if args.category == "lhb":
            inserted, degradations = _backfill_lhb(stocks, start, end, db)
        elif args.category == "corporate_events":
            inserted, degradations = _backfill_corporate_events(stocks, start, end, db)
        else:
            inserted, degradations = _backfill_stock_category(args.category, stocks, start, end, db)
        print(
            json.dumps(
                {
                    "category": args.category,
                    "stocks": len(stocks),
                    "inserted": inserted,
                    "degradations": degradations,
                },
                ensure_ascii=False,
                default=str,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
