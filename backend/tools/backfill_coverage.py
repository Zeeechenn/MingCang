"""Backfill StockSage data coverage gaps.

This tool intentionally does not start the scheduler. It fills missing
financial rows, fresh news rows, and short price history where providers have
data available, then prints before/after coverage snapshots.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import func

from backend.analysis.factors import add_all_factors
from backend.data import fundamentals
from backend.data.database import FinancialMetric, NewsItem, Price, SessionLocal, Stock
from backend.data.fundamentals import sync_disclosure_dates, sync_financial_metrics, sync_industry
from backend.data.market import fetch_daily
from backend.data.news import RawNews, fetch_stock_news_cn, save_news_to_db
from backend.data.quality import build_data_coverage_snapshot

logger = logging.getLogger(__name__)


@dataclass
class BackfillStats:
    industries_updated: int = 0
    financial_symbols_attempted: int = 0
    financial_symbols_filled: int = 0
    financial_rows_inserted: int = 0
    disclosure_dates_updated: int = 0
    news_symbols_attempted: int = 0
    news_symbols_filled: int = 0
    news_rows_inserted: int = 0
    price_symbols_attempted: int = 0
    price_symbols_filled: int = 0
    price_rows_inserted: int = 0
    natural_short_price_symbols: list[str] = field(default_factory=list)


def _fetch_tavily_news(stock: Stock, limit: int = 3) -> list[RawNews]:
    from urllib.parse import urlparse

    import requests

    from backend.config import settings

    if not settings.tavily_api_key:
        return []
    symbol = str(stock.symbol)
    name = str(stock.name)
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_api_key,
                "query": f"{name} {symbol} 股票 最新消息 公告 业绩",
                "search_depth": "basic",
                "max_results": limit,
                "days": 1,
                "include_answer": False,
            },
            proxies={"http": "", "https": ""},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("tavily news fallback failed %s: %s", symbol, exc)
        return []
    items = []
    for row in resp.json().get("results", []):
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.") or "tavily"
        items.append(
            RawNews(
                title=title,
                url=url,
                published_at=datetime.utcnow(),
                source=f"tavily:{host}",
                symbol=symbol,
            )
        )
    return items


def _missing_financial_symbols(db, limit: int | None = None) -> list[Stock]:
    query = (
        db.query(Stock).filter(Stock.active.is_(True), Stock.market == "CN").order_by(Stock.symbol)
    )
    rows = []
    for stock in query.all():
        exists = db.query(FinancialMetric.id).filter(FinancialMetric.symbol == stock.symbol).first()
        if not exists:
            rows.append(stock)
            if limit and len(rows) >= limit:
                break
    return rows


def _missing_news_symbols(db, hours: int = 24, limit: int | None = None) -> list[Stock]:
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query = (
        db.query(Stock).filter(Stock.active.is_(True), Stock.market == "CN").order_by(Stock.symbol)
    )
    rows = []
    for stock in query.all():
        exists = (
            db.query(NewsItem.id)
            .filter(NewsItem.symbol == stock.symbol, NewsItem.published_at >= cutoff)
            .first()
        )
        if not exists:
            rows.append(stock)
            if limit and len(rows) >= limit:
                break
    return rows


def _short_price_symbols(
    db, min_rows: int = 480, limit: int | None = None
) -> list[tuple[Stock, int]]:
    rows = []
    stocks = db.query(Stock).filter(Stock.active.is_(True)).order_by(Stock.symbol).all()
    for stock in stocks:
        count = db.query(func.count(Price.id)).filter(Price.symbol == stock.symbol).scalar() or 0
        if count < min_rows:
            rows.append((stock, int(count)))
            if limit and len(rows) >= limit:
                break
    return rows


def _force_price_backfill(stock: Stock, db, years: int = 5) -> tuple[int, bool]:
    symbol = str(stock.symbol)
    market = str(stock.market)
    df = fetch_daily(symbol, market, days=years * 365 + 10)
    if df.empty:
        return 0, False
    df = add_all_factors(df)
    existing = {row[0] for row in db.query(Price.date).filter(Price.symbol == symbol).all()}
    records = []
    for date_str, row in df.iterrows():
        if date_str in existing:
            continue
        atr = row.get("atr14")
        records.append(
            Price(
                symbol=symbol,
                date=date_str,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                atr14=float(atr) if atr is not None else None,
            )
        )
    if records:
        db.bulk_save_objects(records)
        db.commit()
    return len(records), len(df) < 480


def run_backfill(
    *,
    years: int = 5,
    news_limit: int = 20,
    sleep_seconds: float = 0.2,
    financial_limit: int | None = None,
    news_symbol_limit: int | None = None,
    price_limit: int | None = None,
    skip_financial: bool = False,
    skip_news: bool = False,
    skip_prices: bool = False,
    sync_industries: bool = False,
    fast_financial: bool = False,
    use_tavily: bool = False,
) -> dict:
    stats = BackfillStats()
    db = SessionLocal()
    try:
        before = build_data_coverage_snapshot(db)

        if not skip_prices:
            for stock, _count in _short_price_symbols(db, limit=price_limit):
                stats.price_symbols_attempted += 1
                try:
                    inserted, natural_short = _force_price_backfill(stock, db, years=years)
                    stats.price_rows_inserted += inserted
                    if inserted:
                        stats.price_symbols_filled += 1
                    if natural_short:
                        stats.natural_short_price_symbols.append(str(stock.symbol))
                except Exception as exc:
                    logger.warning("price backfill failed %s: %s", stock.symbol, exc)
                time.sleep(sleep_seconds)

        if not skip_financial:
            if fast_financial:
                fundamentals._fetch_indicator = lambda _ak, _symbol, years=5: pd.DataFrame()
            if sync_industries:
                try:
                    stats.industries_updated = sync_industry(db)
                except Exception as exc:
                    logger.warning("industry backfill failed: %s", exc)
            for stock in _missing_financial_symbols(db, limit=financial_limit):
                stats.financial_symbols_attempted += 1
                try:
                    inserted = sync_financial_metrics(str(stock.symbol), db, years=years)
                    stats.financial_rows_inserted += inserted
                    if inserted:
                        stats.financial_symbols_filled += 1
                except Exception as exc:
                    logger.warning("financial backfill failed %s: %s", stock.symbol, exc)
                time.sleep(sleep_seconds)
            try:
                stats.disclosure_dates_updated = sync_disclosure_dates(db, years=years)
            except Exception as exc:
                logger.warning("disclosure date backfill failed: %s", exc)

        if not skip_news:
            for stock in _missing_news_symbols(db, limit=news_symbol_limit):
                stats.news_symbols_attempted += 1
                try:
                    items = fetch_stock_news_cn(str(stock.symbol), limit=news_limit)
                    inserted = save_news_to_db(items, db)
                    if inserted == 0 and use_tavily:
                        inserted = save_news_to_db(_fetch_tavily_news(stock, limit=3), db)
                    stats.news_rows_inserted += inserted
                    if inserted:
                        stats.news_symbols_filled += 1
                except Exception as exc:
                    logger.warning("news backfill failed %s: %s", stock.symbol, exc)
                time.sleep(sleep_seconds)

        after = build_data_coverage_snapshot(db)
        return {"before": before["summary"], "after": after["summary"], "stats": asdict(stats)}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--news-limit", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--financial-limit", type=int)
    parser.add_argument("--news-symbol-limit", type=int)
    parser.add_argument("--price-limit", type=int)
    parser.add_argument("--skip-financial", action="store_true")
    parser.add_argument("--skip-news", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--sync-industries", action="store_true")
    parser.add_argument("--fast-financial", action="store_true")
    parser.add_argument("--use-tavily", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    result = run_backfill(
        years=args.years,
        news_limit=args.news_limit,
        sleep_seconds=args.sleep,
        financial_limit=args.financial_limit,
        news_symbol_limit=args.news_symbol_limit,
        price_limit=args.price_limit,
        skip_financial=args.skip_financial,
        skip_news=args.skip_news,
        skip_prices=args.skip_prices,
        sync_industries=args.sync_industries,
        fast_financial=args.fast_financial,
        use_tavily=args.use_tavily,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
