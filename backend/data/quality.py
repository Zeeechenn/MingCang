"""Data coverage and provider reliability reports."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from backend.data.cache_policy import cache_policy_payload
from backend.data.database import Announcement, FinancialMetric, NewsItem, Price, Signal, Stock
from backend.data.market import register_default_market_providers
from backend.data.market_capabilities import SUPPORTED_MARKETS, build_market_capability_catalog
from backend.data.providers import get_provider_health, provider_fallback_chains
from backend.decision.market_policy import (
    is_production_signal_market,
    production_signal_policy_payload,
    signal_scope_for,
)

CAPABILITY_COVERAGE_COUNTERS = {
    "quote": ("price_covered",),
    "kline": ("price_covered", "two_year_price_covered"),
    "fundamentals": ("financial_covered",),
    "filings": ("filings_covered",),
}


def _market_profiles_payload() -> dict:
    from backend.data.market_profiles import all_market_profiles_payload

    return all_market_profiles_payload()


def build_data_coverage_report(db) -> dict:
    """Build a compact coverage report for active stocks."""
    register_default_market_providers()
    stocks = db.query(Stock).filter(Stock.active).order_by(Stock.symbol).all()
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    rows: list[dict] = []

    for stock in stocks:
        from backend.data.instruments import symbol_candidates

        price = (
            db.query(func.count(Price.id), func.min(Price.date), func.max(Price.date))
            .filter(Price.asset_key == stock.asset_key)
            .first()
        )
        if not int(price[0] or 0):
            price = (
                db.query(func.count(Price.id), func.min(Price.date), func.max(Price.date))
                .filter(Price.symbol.in_(symbol_candidates(stock.symbol)))
                .first()
            )
        latest_fin = (
            db.query(FinancialMetric.report_date)
            .filter(FinancialMetric.asset_key == stock.asset_key)
            .order_by(FinancialMetric.report_date.desc())
            .first()
        )
        if latest_fin is None:
            latest_fin = (
                db.query(FinancialMetric.report_date)
                .filter(FinancialMetric.symbol.in_(symbol_candidates(stock.symbol)))
                .order_by(FinancialMetric.report_date.desc())
                .first()
            )
        news_count = (
            db.query(func.count(NewsItem.id))
            .filter(NewsItem.asset_key == stock.asset_key, NewsItem.published_at >= cutoff)
            .scalar()
            or 0
        )
        if not news_count:
            news_count = (
                db.query(func.count(NewsItem.id))
                .filter(
                    NewsItem.symbol.in_(symbol_candidates(stock.symbol)),
                    NewsItem.published_at >= cutoff,
                )
                .scalar()
                or 0
            )
        filings_count = (
            db.query(func.count(Announcement.id))
            .filter(Announcement.asset_key == stock.asset_key)
            .scalar()
            or 0
        )
        if not filings_count:
            filings_count = (
                db.query(func.count(Announcement.id))
                .filter(Announcement.symbol.in_(symbol_candidates(stock.symbol)))
                .scalar()
                or 0
            )
        rows.append({
            "symbol": stock.symbol,
            "asset_key": stock.asset_key,
            "name": stock.name,
            "market": stock.market,
            "industry": stock.industry,
            "price_rows": int(price[0] or 0),
            "first_price_date": price[1],
            "latest_price_date": price[2],
            "latest_financial_report": latest_fin[0] if latest_fin else None,
            "news_24h_count": int(news_count),
            "filings_count": int(filings_count),
            "signal_scope": signal_scope_for(stock.market, stock.symbol),
            "currency": stock.currency,
            "timezone": stock.timezone,
        })

    def _covered(key: str) -> int:
        return sum(1 for row in rows if row.get(key))

    observed_markets = sorted({row["market"] for row in rows if row.get("market")})
    markets = sorted(set(SUPPORTED_MARKETS) | set(observed_markets))
    market_coverage = {}
    for market in markets:
        market_rows = [row for row in rows if row.get("market") == market]
        market_coverage[market] = {
            "active_stocks": len(market_rows),
            "price_covered": sum(1 for row in market_rows if row["price_rows"] > 0),
            "two_year_price_covered": sum(1 for row in market_rows if row["price_rows"] >= 480),
            "financial_covered": sum(1 for row in market_rows if row.get("latest_financial_report")),
            "news_24h_covered": sum(1 for row in market_rows if row["news_24h_count"] > 0),
            "filings_covered": sum(1 for row in market_rows if row["filings_count"] > 0),
            "signal_scopes": sorted({row["signal_scope"] for row in market_rows}),
            "signal_scope": (
                next(iter({row["signal_scope"] for row in market_rows}), "observe_only")
                if len({row["signal_scope"] for row in market_rows}) <= 1
                else "mixed"
            ),
        }
    production_rows = [row for row in rows if is_production_signal_market(row.get("market"))]
    gray_rows = [row for row in rows if row.get("signal_scope") == "gray"]
    observe_only_rows = [row for row in rows if row.get("signal_scope") == "observe_only"]

    def _coverage(rows_: list[dict]) -> dict:
        return {
            "active_stocks": len(rows_),
            "price_covered": sum(1 for row in rows_ if row["price_rows"] > 0),
            "two_year_price_covered": sum(1 for row in rows_ if row["price_rows"] >= 480),
            "financial_covered": sum(1 for row in rows_ if row.get("latest_financial_report")),
            "news_24h_covered": sum(1 for row in rows_ if row["news_24h_count"] > 0),
            "filings_covered": sum(1 for row in rows_ if row["filings_count"] > 0),
        }

    cache_policy = cache_policy_payload()
    capability_catalog = build_market_capability_catalog()
    return {
        "summary": {
            "active_stocks": len(rows),
            "markets": markets,
            "market_coverage": market_coverage,
            "price_covered": sum(1 for row in rows if row["price_rows"] > 0),
            "two_year_price_covered": sum(1 for row in rows if row["price_rows"] >= 480),
            "financial_covered": _covered("latest_financial_report"),
            "news_24h_covered": sum(1 for row in rows if row["news_24h_count"] > 0),
            "filings_covered": sum(1 for row in rows if row["filings_count"] > 0),
            "production_coverage": _coverage(production_rows),
            "gray_coverage": _coverage(gray_rows),
            "observe_only_coverage": _coverage(observe_only_rows),
            "cache_policy": cache_policy,
            "freshness_contract": cache_policy.get("freshness_contracts", {}),
            "intraday_zero_network_policy": cache_policy.get("intraday_zero_network_policy", {}),
            "provider_fallback_chains": {
                "markets": markets,
                "chains_by_market": {
                    market: provider_fallback_chains(market)
                    for market in markets
                },
            },
            "market_capability_catalog": capability_catalog,
            "production_signal_policy": production_signal_policy_payload(),
            "market_profiles": _market_profiles_payload(),
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
    production = summary.get("production_coverage") or {}
    production_active = max(1, int(production.get("active_stocks") or 0))
    checks = {
        "price_coverage_ok": production.get("price_covered", 0) == production.get("active_stocks", 0),
        "two_year_price_coverage_ok": (
            production.get("two_year_price_covered", 0) == production.get("active_stocks", 0)
        ),
        "financial_coverage_ok": production.get("financial_covered", 0) / production_active >= 0.8,
        "fresh_news_ok": production.get("news_24h_covered", 0) / production_active >= 0.8,
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
    observed_markets = sorted({row["market"] for row in report["stocks"] if row.get("market")})
    markets = sorted(set(SUPPORTED_MARKETS) | set(observed_markets))
    cache_policy = summary.get("cache_policy", {})

    return {
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "summary": summary,
        "checks": checks,
        "warnings": warnings,
        "provider_health": report.get("provider_health", {}),
        "freshness_contract": cache_policy.get("freshness_contracts", {}),
        "intraday_zero_network_policy": cache_policy.get("intraday_zero_network_policy", {}),
        "provider_fallback_chains": {
            "markets": markets,
            "chains_by_market": {
                market: provider_fallback_chains(market)
                for market in markets
            },
        },
        "market_capability_catalog": summary.get("market_capability_catalog", {}),
        "cache_policy": cache_policy,
        "stocks": report["stocks"],
    }
