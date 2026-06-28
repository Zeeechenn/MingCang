"""M54 content backfill helper for historical news rows.

The tool only reuses existing news fetchers and ``save_news_to_db``. It does
not call the LLM stack, sentiment scoring, or the M54 v2 scoring layers.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import case, func

from backend.data.database import NewsItem, SessionLocal
from backend.data.news import fetch_stock_news_anspire, fetch_stock_news_cn, save_news_to_db
from backend.data.news_models import RawNews

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test3_universe_50.json"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockTarget:
    symbol: str
    name: str


@dataclass(frozen=True)
class BackfillResult:
    stocks_total: int
    stocks_processed: int
    stocks_failed: int
    inserted: int


def load_universe(path: Path) -> list[StockTarget]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    stocks = payload.get("stocks")
    if not isinstance(stocks, list):
        raise ValueError("universe JSON must contain a stocks list")

    targets: list[StockTarget] = []
    for item in stocks:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        name = str(item.get("name") or "").strip()
        if symbol:
            targets.append(StockTarget(symbol=symbol, name=name))
    return targets


def run_backfill(
    *,
    db: Any,
    universe_path: Path = DEFAULT_UNIVERSE,
    stock_limit: int | None = None,
    cn_limit: int = 20,
) -> BackfillResult:
    targets = load_universe(universe_path)
    if stock_limit is not None:
        targets = targets[:stock_limit]

    processed = 0
    failed = 0
    inserted = 0

    for target in targets:
        try:
            items: list[RawNews] = []
            items.extend(fetch_stock_news_cn(target.symbol, limit=cn_limit))
            items.extend(fetch_stock_news_anspire(target.symbol, target.name))
            inserted += save_news_to_db(items, db)
            processed += 1
        except Exception as exc:  # pragma: no cover - operator resilience.
            failed += 1
            logger.warning("M54 content backfill skipped %s: %s", target.symbol, exc)
            db.rollback()

    return BackfillResult(
        stocks_total=len(targets),
        stocks_processed=processed,
        stocks_failed=failed,
        inserted=inserted,
    )


def coverage_report(db: Any, *, start: datetime, end: datetime) -> dict[str, Any]:
    content_present = case(
        (func.length(func.trim(func.coalesce(NewsItem.content, ""))) > 0, 1),
        else_=0,
    )
    base_filters = (NewsItem.published_at >= start, NewsItem.published_at <= end)

    total_rows, total_with_content = (
        db.query(func.count(NewsItem.id), func.coalesce(func.sum(content_present), 0))
        .filter(*base_filters)
        .one()
    )

    provider_rows = (
        db.query(
            func.coalesce(NewsItem.provider, "unknown"),
            func.count(NewsItem.id),
            func.coalesce(func.sum(content_present), 0),
        )
        .filter(*base_filters)
        .group_by(func.coalesce(NewsItem.provider, "unknown"))
        .order_by(func.coalesce(NewsItem.provider, "unknown"))
        .all()
    )

    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "total": _coverage_dict(int(total_rows or 0), int(total_with_content or 0)),
        "by_provider": {
            str(provider): _coverage_dict(int(rows or 0), int(with_content or 0))
            for provider, rows, with_content in provider_rows
        },
    }


def _coverage_dict(rows: int, with_content: int) -> dict[str, float | int]:
    coverage = round((with_content / rows) * 100, 2) if rows else 0.0
    return {"rows": rows, "with_content": with_content, "coverage_pct": coverage}


def _parse_datetime(value: str, *, end_of_day: bool = False) -> datetime:
    raw = value.strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        parsed_date = datetime.strptime(raw, "%Y-%m-%d").date()
        boundary = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, boundary)
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"invalid datetime/date: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M54 content backfill and content coverage report")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--limit", type=int, default=None, help="Limit number of universe stocks to process")
    parser.add_argument("--cn-limit", type=int, default=20, help="Eastmoney rows per stock")
    parser.add_argument("--report-only", action="store_true", help="Only report coverage, skip fetching")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.cn_limit < 0:
        raise SystemExit("--cn-limit must be >= 0")
    start = _parse_datetime(args.start)
    end = _parse_datetime(args.end, end_of_day=True)
    if start > end:
        raise SystemExit("--start must be <= --end")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = SessionLocal()
    try:
        result: BackfillResult | None = None
        if not args.report_only:
            result = run_backfill(
                db=db,
                universe_path=args.universe,
                stock_limit=args.limit,
                cn_limit=args.cn_limit,
            )
        report = coverage_report(db, start=start, end=end)
        payload: dict[str, Any] = {
            "ok": True,
            "schema_version": "m54_content_backfill.v1",
            "backfill": None if result is None else result.__dict__,
            "coverage": report,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
