"""Premarket scheduler job implementation."""

import logging

logger = logging.getLogger(__name__)


def run_premarket(market: str = "CN") -> dict:
    """Market-scoped refresh: prices, news, PIT fundamentals, and benchmark."""
    from backend.data.database import SessionLocal, Stock
    from backend.data.fundamentals import sync_financial_metrics_for_market
    from backend.data.market import backfill_if_needed, sync_market_index_to_db
    from backend.data.market_profiles import normalize_market
    from backend.data.news import fetch_stock_news, save_news_to_db
    from backend.decision.market_policy import is_signal_eligible_stock

    market = normalize_market(market)
    db = SessionLocal()
    try:
        candidates = db.query(Stock).filter(Stock.active, Stock.market == market).all()
        stocks = candidates if market == "CN" else [row for row in candidates if is_signal_eligible_stock(row)]
        price_rows, news_rows, financial_rows, filing_rows, errors = 0, 0, 0, 0, 0

        expected_latest = None
        if market == "CN":
            try:
                from backend.data.freshness import expected_trade_date

                expected_latest, _basis = expected_trade_date(db)
                expected_latest = expected_latest or None
            except Exception as e:
                logger.error("expected_trade_date failed: %s", e)
                expected_latest = None

        for stock in stocks:
            try:
                if stock.market == "CN" and expected_latest:
                    price_rows += backfill_if_needed(
                        stock.symbol, stock.market, db, refresh_today=True, expected_latest=expected_latest
                    )
                else:
                    price_rows += backfill_if_needed(stock.symbol, stock.market, db, refresh_today=True)
            except Exception as e:
                errors += 1
                logger.error("backfill failed %s %s: %s", stock.market, stock.symbol, e)

            try:
                news = fetch_stock_news(stock.symbol, stock.name, stock.market)
                news_rows += save_news_to_db(news, db, market=stock.market)
            except Exception as e:
                errors += 1
                logger.error("news fetch failed %s %s: %s", stock.market, stock.symbol, e)

            try:
                financial_rows += sync_financial_metrics_for_market(
                    stock.symbol,
                    stock.market,
                    db,
                )
            except Exception as e:
                errors += 1
                logger.error("fundamentals sync failed %s %s: %s", stock.market, stock.symbol, e)

            if stock.market in {"HK", "US"}:
                try:
                    from backend.data.global_disclosures import sync_global_disclosures

                    filing_rows += sync_global_disclosures(stock, db)
                except Exception as e:
                    errors += 1
                    logger.error("filings sync failed %s %s: %s", stock.market, stock.symbol, e)

        index_rows = 0
        try:
            index_rows = sync_market_index_to_db(db, market)
        except Exception as e:
            errors += 1
            logger.error("index sync failed %s: %s", market, e)

        result = {
            "market": market,
            "input_stocks": len(candidates),
            "stocks": len(stocks),
            "market_skipped": len(candidates) - len(stocks),
            "price_rows": price_rows,
            "news_rows": news_rows,
            "financial_rows": financial_rows,
            "filing_rows": filing_rows,
            "index_rows": index_rows,
            "errors": errors,
        }
        logger.info("pre-market done: %s", result)
        return result
    finally:
        db.close()
