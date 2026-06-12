from __future__ import annotations

import json
import socket
from datetime import datetime

import pandas as pd


def test_provider_fallback_chains_expose_ordered_metadata_and_skip_observe_only():
    from backend.data.providers import (
        fetch_daily_with_fallback,
        get_provider_health,
        provider_fallback_chains,
        register_daily_provider,
        register_index_provider,
        reset_provider_registry,
    )

    reset_provider_registry()
    calls: list[str] = []

    def observe_only_fetch(symbol: str, days: int) -> pd.DataFrame:
        calls.append("observe_only")
        raise AssertionError("observe-only provider should not be fetched")

    def active_fetch(symbol: str, days: int) -> pd.DataFrame:
        calls.append("active")
        return pd.DataFrame([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    def index_fetch(index_symbol: str, days: int) -> pd.DataFrame:
        return pd.DataFrame([{"close": 1, "change_pct": 0}])

    register_daily_provider(
        "observe_cn",
        {"CN"},
        observe_only_fetch,
        priority=0,
        cooldown_seconds=7,
        data_type="daily_price",
        observe_only=True,
    )
    register_daily_provider("active_cn", {"CN"}, active_fetch, priority=10, cooldown_seconds=11)
    register_index_provider(
        "index_cn",
        index_fetch,
        markets={"CN"},
        priority=5,
        cooldown_seconds=13,
        data_type="index_price",
    )

    chains = provider_fallback_chains("CN")

    assert [item["name"] for item in chains["daily"]] == ["observe_cn", "active_cn"]
    assert chains["daily"][0]["priority"] == 0
    assert chains["daily"][0]["cooldown_seconds"] == 7
    assert chains["daily"][0]["markets"] == ["CN"]
    assert chains["daily"][0]["data_type"] == "daily_price"
    assert chains["daily"][0]["observe_only"] is True
    assert chains["index"][0]["markets"] == ["CN"]
    assert chains["index"][0]["data_type"] == "index_price"

    _, provider = fetch_daily_with_fallback("600519", "CN", 1)

    assert provider == "active_cn"
    assert calls == ["active"]
    assert get_provider_health()["observe_cn"]["skipped"] == 1


def test_data_coverage_snapshot_exposes_freshness_policy_and_market_chains(test_db, monkeypatch):
    from backend.data import quality
    from backend.data.database import Price, Stock
    from backend.data.providers import register_daily_provider, reset_provider_registry

    reset_provider_registry()
    monkeypatch.setattr(quality, "register_default_market_providers", lambda: None)
    register_daily_provider(
        "snapshot_cn",
        {"CN"},
        lambda symbol, days: pd.DataFrame(),
        priority=3,
        cooldown_seconds=17,
        data_type="daily_price",
    )
    test_db.add(Stock(symbol="600519", name="Moutai", market="CN", industry="Food", active=True))
    test_db.add(
        Price(
            symbol="600519",
            date="2026-06-01",
            open=1,
            high=2,
            low=1,
            close=2,
            volume=1000,
        )
    )
    test_db.commit()

    snapshot = quality.build_data_coverage_snapshot(test_db, generated_at="2026-06-02T00:00:00+00:00")

    assert snapshot["freshness_contract"]["daily_price"]["intraday_policy"] == "read_L1_L2_only"
    assert snapshot["intraday_zero_network_policy"]["remote_fetch_allowed"] is False
    assert snapshot["provider_fallback_chains"]["markets"] == ["CN", "HK", "US"]
    chain = snapshot["provider_fallback_chains"]["chains_by_market"]["CN"]["daily"]
    assert chain[0]["name"] == "snapshot_cn"
    assert chain[0]["priority"] == 3
    assert chain[0]["cooldown_seconds"] == 17
    assert snapshot["summary"]["latest_price_date"] == "2026-06-01"
    assert snapshot["summary"]["market_capability_catalog"]["policy"]["write_policy"] == "no_database_writes"
    assert snapshot["summary"]["production_signal_policy"]["production_signal_markets"] == ["CN"]


def test_data_coverage_catalog_covers_cn_hk_us_seven_layers(test_db, monkeypatch):
    from backend.data import quality
    from backend.data.database import Price, Stock
    from backend.data.providers import reset_provider_registry

    reset_provider_registry()
    monkeypatch.setattr(quality, "register_default_market_providers", lambda: None)
    for stock in [
        Stock(symbol="600519", name="Moutai", market="CN", active=True),
        Stock(symbol="700", name="Tencent", market="HK", active=True),
        Stock(symbol="AAPL", name="Apple", market="US", active=True),
    ]:
        test_db.add(stock)
    for symbol in ("600519", "700", "AAPL"):
        test_db.add(
            Price(
                symbol=symbol,
                date="2026-06-01",
                open=1,
                high=2,
                low=1,
                close=2,
                volume=1000,
            )
        )
    test_db.commit()

    snapshot = quality.build_data_coverage_snapshot(test_db, generated_at="2026-06-02T00:00:00+00:00")
    catalog = snapshot["summary"]["market_capability_catalog"]

    assert snapshot["summary"]["markets"] == ["CN", "HK", "US"]
    assert snapshot["summary"]["market_coverage"]["HK"]["price_covered"] == 1
    assert snapshot["summary"]["market_coverage"]["HK"]["signal_scope"] == "observe_only"
    assert snapshot["summary"]["production_coverage"]["active_stocks"] == 1
    assert snapshot["summary"]["observe_only_coverage"]["active_stocks"] == 2
    assert snapshot["provider_fallback_chains"]["markets"] == ["CN", "HK", "US"]
    assert catalog["markets"] == ["CN", "HK", "US"]
    assert [layer["id"] for layer in catalog["layers"]] == [
        "quote",
        "kline",
        "fundamentals",
        "capital_flow",
        "derivatives",
        "filings",
        "tools_fallback",
    ]
    assert catalog["markets_detail"]["CN"]["layers"][1]["status"] == "production"
    assert catalog["markets_detail"]["HK"]["layers"][2]["signal_impact"] == "none"
    assert catalog["markets_detail"]["US"]["layers"][5]["providers"] == ["sec_filings_candidate"]
    assert catalog["markets_detail"]["HK"]["layers"][5]["probe_links"][0]["probe_id"] == "hkex_filings"
    assert catalog["markets_detail"]["US"]["layers"][2]["probe_links"][0]["probe_id"] == "sec_companyfacts"
    assert catalog["markets_detail"]["US"]["layers"][4]["probe_links"][0]["probe_id"] == "yfinance_options"
    assert catalog["probe_links"]["US"]["filings"][0]["write_policy"] == "no_database_writes"
    assert catalog["probe_links"]["HK"]["fundamentals"][0]["signal_impact"] == "none"


def test_data_coverage_checks_use_cn_production_denominator(test_db, monkeypatch):
    from backend.data import quality
    from backend.data.database import Price, Stock
    from backend.data.providers import reset_provider_registry

    reset_provider_registry()
    monkeypatch.setattr(quality, "register_default_market_providers", lambda: None)
    for stock in [
        Stock(symbol="600519", name="Moutai", market="CN", active=True),
        Stock(symbol="700", name="Tencent", market="HK", active=True),
    ]:
        test_db.add(stock)
    test_db.add(
        Price(
            symbol="600519",
            date="2026-06-01",
            open=1,
            high=2,
            low=1,
            close=2,
            volume=1000,
        )
    )
    test_db.commit()

    snapshot = quality.build_data_coverage_snapshot(test_db, generated_at="2026-06-02T00:00:00+00:00")

    assert snapshot["summary"]["active_stocks"] == 2
    assert snapshot["summary"]["price_covered"] == 1
    assert snapshot["summary"]["production_coverage"]["price_covered"] == 1
    assert snapshot["summary"]["observe_only_coverage"]["price_covered"] == 0
    assert snapshot["checks"]["price_coverage_ok"] is True


def test_m31_cache_benchmark_defaults_to_no_network_no_persistent_db_writes(tmp_path, monkeypatch):
    from backend.tools import m31_cache_benchmark as benchmark

    def fail_network(*args, **kwargs):
        raise AssertionError("benchmark should not open network sockets by default")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    json_output = tmp_path / "m31_cache_benchmark.json"
    markdown_output = tmp_path / "m31_cache_benchmark.md"

    report = benchmark.main([
        "--iterations",
        "3",
        "--json-output",
        str(json_output),
        "--markdown-output",
        str(markdown_output),
    ])

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")

    assert str(benchmark.DEFAULT_JSON_OUTPUT).startswith("/private/tmp/")
    assert str(benchmark.DEFAULT_MARKDOWN_OUTPUT).startswith("/private/tmp/")
    assert payload["safety"]["network_calls_attempted"] is False
    assert payload["safety"]["mingcang_db_writes_attempted"] is False
    assert {row["layer"] for row in payload["layers"]} == {"L1", "L2", "L3"}
    l3 = [row for row in payload["layers"] if row["layer"] == "L3"][0]
    assert l3["measured"] is False
    assert "remote" in l3["concept"]
    assert report["iterations"] == 3
    assert "# M31 Cache Benchmark" in markdown
    datetime.fromisoformat(payload["generated_at"])
