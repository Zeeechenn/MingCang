"""Data coverage and provider reliability reports."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from backend.data.database import FinancialMetric, NewsItem, Price, Signal, Stock
from backend.data.providers import get_provider_health


def build_data_coverage_report(db) -> dict:
    """Build a compact coverage report for active stocks."""
    stocks = db.query(Stock).filter(Stock.active).order_by(Stock.symbol).all()
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
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



def build_data_coverage_snapshot(db, generated_at: str | None = None) -> dict:
    """Build an auditable point-in-time coverage snapshot with quality checks."""
    report = build_data_coverage_report(db)
    summary = dict(report["summary"])
    signal_range = db.query(func.count(Signal.id), func.min(Signal.date), func.max(Signal.date)).first()
    latest_price_date = db.query(func.max(Price.date)).scalar()
    summary.update({
        "latest_price_date": latest_price_date,
        "signals_count": int(signal_range[0] or 0),
        "signals_first_date": signal_range[1],
        "signals_latest_date": signal_range[2],
    })
    active = max(1, int(summary.get("active_stocks") or 0))
    checks = {
        "price_coverage_ok": summary.get("price_covered", 0) == summary.get("active_stocks", 0),
        "two_year_price_coverage_ok": summary.get("two_year_price_covered", 0) == summary.get("active_stocks", 0),
        "financial_coverage_ok": summary.get("financial_covered", 0) / active >= 0.8,
        "fresh_news_ok": summary.get("news_24h_covered", 0) / active >= 0.8,
    }
    warnings = []
    if not checks["price_coverage_ok"]:
        warnings.append({
            "code": "price_coverage_gap",
            "message": "Some active stocks have no price rows.",
        })
    if not checks["two_year_price_coverage_ok"]:
        warnings.append({
            "code": "two_year_price_coverage_gap",
            "message": "Some active stocks have fewer than 480 price rows.",
        })
    if not checks["financial_coverage_ok"]:
        warnings.append({
            "code": "financial_coverage_gap",
            "message": "Financial coverage is below the 80% operating threshold.",
        })
    if not checks["fresh_news_ok"]:
        warnings.append({
            "code": "fresh_news_coverage_gap",
            "message": "Fresh 24h news coverage is below the 80% operating threshold.",
        })

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "summary": summary,
        "checks": checks,
        "warnings": warnings,
        "provider_health": report.get("provider_health", {}),
        "stocks": report["stocks"],
    }
