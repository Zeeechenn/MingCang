from __future__ import annotations

LIVE_STAGES = {
    "provider_chain",
    "normalized_db",
    "daily_price_bridge",
    "provider_observability",
}
CANDIDATE_STATUSES = {"planned", "candidate", "observe_only"}
CANDIDATE_STAGES = {"candidate_probe", "evidence", "not_connected"}

CAPABILITY_TO_CATEGORIES = {
    "quote": {"quotes"},
    "kline": {"quotes"},
    "fundamentals": {"financials"},
    "capital_flow": {"fund_flow"},
    "filings": {"announcements"},
}


def _live_claims(catalog: dict) -> list[tuple[str, dict]]:
    claims: list[tuple[str, dict]] = []
    for market, market_payload in catalog["markets_detail"].items():
        for layer in market_payload["layers"]:
            if layer.get("status") in CANDIDATE_STATUSES:
                continue
            if layer.get("stage") in CANDIDATE_STAGES:
                continue
            if layer.get("stage") in LIVE_STAGES:
                claims.append((market, layer))
    return claims


def test_live_market_capabilities_have_a_verification_surface():
    from backend.data import category_fetchers  # noqa: F401 - registers M61 category providers
    from backend.data.category_registry import list_capability_gaps
    from backend.data.market_capabilities import build_market_capability_catalog
    from backend.data.quality import CAPABILITY_COVERAGE_COUNTERS
    from backend.tools.m61_source_health import registered_probe_matrix

    catalog = build_market_capability_catalog()
    category_gaps = list_capability_gaps()
    probe_categories = {row["category"] for row in registered_probe_matrix()}

    missing: list[str] = []
    for market, layer in _live_claims(catalog):
        capability_id = str(layer["id"])
        categories = CAPABILITY_TO_CATEGORIES.get(capability_id, set())
        has_quality_counter = capability_id in CAPABILITY_COVERAGE_COUNTERS
        has_category_provider = any(
            category_gaps.get(category, {}).get("has_provider") for category in categories
        )
        has_source_health_probe = bool(categories & probe_categories)
        has_provider_observability = capability_id == "tools_fallback" and bool(
            catalog["markets_detail"][market].get("provider_fallback")
        )
        if not (
            has_quality_counter
            or has_category_provider
            or has_source_health_probe
            or has_provider_observability
        ):
            missing.append(f"{market}.{capability_id}:{layer.get('stage')}/{layer.get('status')}")

    assert missing == []


def test_data_coverage_report_counts_filings(test_db, sample_stocks):
    from datetime import datetime

    from backend.data.database import Announcement
    from backend.data.quality import build_data_coverage_report

    test_db.add(
        Announcement(
            symbol="600519",
            title="年度报告",
            published_at=datetime(2026, 3, 20, 9, 30),
            provider="unit_test",
        )
    )
    test_db.commit()

    report = build_data_coverage_report(test_db)

    assert report["summary"]["filings_covered"] == 1
    assert report["summary"]["market_coverage"]["CN"]["filings_covered"] == 1
    row = next(row for row in report["stocks"] if row["symbol"] == "600519")
    assert row["filings_count"] == 1
