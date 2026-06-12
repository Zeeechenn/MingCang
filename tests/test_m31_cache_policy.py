from __future__ import annotations

from backend.data.database import Price, Stock


def test_data_coverage_snapshot_exposes_m31_cache_policy(test_db):
    from backend.data.quality import build_data_coverage_snapshot

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", active=True))
    test_db.add(Price(symbol="300308", date="2026-05-29", open=1, high=2, low=1, close=2, volume=100))
    test_db.commit()

    snapshot = build_data_coverage_snapshot(test_db, generated_at="2026-06-02T00:00:00Z")

    assert snapshot["cache_policy"]["workflow_policies"]["intraday"]["remote_fetch_allowed"] is False
    assert snapshot["intraday_zero_network_policy"]["allowed_layers"] == ["L1", "L2"]
    assert "daily_price" in snapshot["freshness_contract"]
    daily_chain = snapshot["provider_fallback_chains"]["chains_by_market"]["CN"]["daily"]
    names = [provider["name"] for provider in daily_chain]
    priorities = [provider["priority"] for provider in daily_chain]
    assert priorities == sorted(priorities)
    assert "akshare_sina_cn" in names
    assert "eastmoney_cn" in names
    assert all("priority" in provider for provider in daily_chain)


def test_m31_cache_benchmark_is_read_only_and_keeps_l3_unmeasured(test_db):
    from backend.tools.m31_cache_benchmark import run_benchmark

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", active=True))
    test_db.add(Price(symbol="300308", date="2026-05-29", open=1, high=2, low=1, close=2, volume=100))
    test_db.commit()

    report = run_benchmark(iterations=2, symbol="300308", session_factory=lambda: test_db)

    assert report["safety"]["network_calls_attempted"] is False
    assert report["safety"]["mingcang_db_writes_attempted"] is False
    assert report["cache_policy"]["workflow_policies"]["intraday"]["allowed_layers"] == ["L1", "L2"]
    l3 = [row for row in report["layers"] if row["layer"] == "L3"][0]
    assert l3["measured"] is False
    assert "remote" in l3["concept"]
