"""Premarket scheduler job implementation."""

import logging
from typing import NotRequired, TypedDict

logger = logging.getLogger(__name__)

PROTECTED_PRICE_FACTOR_WARMUP_ROWS = 240


class _PriceRefreshOptions(TypedDict):
    refresh_today: bool
    expected_latest: NotRequired[str]
    strict_basis_write_guard: NotRequired[bool]
    factor_warmup_rows: NotRequired[int]


def run_premarket(market: str = "CN", *, protected_price_refresh: bool = False) -> dict:
    """Refresh one market; protected CN price refresh is explicit and defaults off."""
    from backend.data.database import SessionLocal, Stock
    from backend.data.fundamentals import sync_financial_metrics_for_market
    from backend.data.market import backfill_if_needed, sync_market_index_to_db
    from backend.data.market_profiles import normalize_market
    from backend.data.news import fetch_stock_news, save_news_to_db
    from backend.decision.market_policy import is_signal_eligible_stock

    market = normalize_market(market)
    if protected_price_refresh and market != "CN":
        raise ValueError("protected price refresh is currently supported for CN only")
    db = SessionLocal()
    try:
        candidates = db.query(Stock).filter(Stock.active, Stock.market == market).all()
        stocks = candidates if market == "CN" else [row for row in candidates if is_signal_eligible_stock(row)]
        price_rows, news_rows, financial_rows, filing_rows, errors = 0, 0, 0, 0, 0
        blocked_price_symbols: list[dict[str, str]] = []
        completed_price_symbols = 0

        expected_latest = None
        if market == "CN":
            try:
                from backend.data.freshness import expected_trade_date

                expected_latest, _basis = expected_trade_date(db)
                expected_latest = expected_latest or None
            except Exception as e:
                logger.error("expected_trade_date failed: %s", e)
                expected_latest = None

        if protected_price_refresh and not expected_latest:
            raise RuntimeError("protected price refresh requires a fixed expected_trade_date")

        for stock in stocks:
            try:
                refresh_options: _PriceRefreshOptions = {"refresh_today": True}
                if expected_latest:
                    refresh_options["expected_latest"] = expected_latest
                if protected_price_refresh:
                    refresh_options["strict_basis_write_guard"] = True
                    refresh_options["factor_warmup_rows"] = PROTECTED_PRICE_FACTOR_WARMUP_ROWS
                price_rows += backfill_if_needed(stock.symbol, stock.market, db, **refresh_options)
                if protected_price_refresh:
                    completed_price_symbols += 1
            except Exception as e:
                errors += 1
                if protected_price_refresh:
                    blocked_price_symbols.append({"symbol": stock.symbol, "reason": str(e)})
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
        if protected_price_refresh:
            if not stocks:
                blocked_price_symbols.append(
                    {"symbol": "", "reason": "no eligible CN symbols to refresh"}
                )
            result["protected_price_refresh"] = {
                "status": (
                    "partial"
                    if blocked_price_symbols and completed_price_symbols
                    else "blocked" if blocked_price_symbols else "complete"
                ),
                "rows_written": price_rows,
                "completed_symbols": completed_price_symbols,
                "blocked_symbols": blocked_price_symbols,
            }
        logger.info("pre-market done: %s", result)
        return result
    finally:
        db.close()
