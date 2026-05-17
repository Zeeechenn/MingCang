"""Data coverage and provider reliability reports."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func

from backend.data.database import FinancialMetric, NewsItem, Price, Stock
from backend.data.providers import get_provider_health


def build_data_coverage_report(db) -> dict:
    """Build a compact coverage report for active stocks."""
    stocks = db.query(Stock).filter(Stock.active == True).order_by(Stock.symbol).all()
    cutoff = datetime.utcnow() - timedelta(hours=24)
    rows: list[dict] = []

    for stock in stocks:
        price = (
            db.query(func.count(Price.id), func.min(Price.date), func.max(Price.date))
            .filter(Price.symbol == stock.symbol)
            .first()
        )
        latest_fin = (
            db.query(FinancialMetric.report_date)
            .filter(FinancialMetric.symbol == stock.symbol)
            .order_by(FinancialMetric.report_date.desc())
            .first()
        )
        news_count = (
            db.query(func.count(NewsItem.id))
            .filter(NewsItem.symbol == stock.symbol, NewsItem.published_at >= cutoff)
            .scalar()
            or 0
        )
        rows.append({
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market,
            "industry": stock.industry,
            "price_rows": int(price[0] or 0),
            "first_price_date": price[1],
            "latest_price_date": price[2],
            "latest_financial_report": latest_fin[0] if latest_fin else None,
            "news_24h_count": int(news_count),
        })

    def _covered(key: str) -> int:
        return sum(1 for row in rows if row.get(key))

    return {
        "summary": {
            "active_stocks": len(rows),
            "price_covered": sum(1 for row in rows if row["price_rows"] > 0),
            "two_year_price_covered": sum(1 for row in rows if row["price_rows"] >= 480),
            "financial_covered": _covered("latest_financial_report"),
            "news_24h_covered": sum(1 for row in rows if row["news_24h_count"] > 0),
        },
        "provider_health": get_provider_health(),
        "stocks": rows,
    }
