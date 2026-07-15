def test_external_source_catalog_prioritizes_evidence_before_signal_inputs():
    from backend.data.external_sources import build_external_source_catalog

    catalog = build_external_source_catalog()

    assert catalog["policy"]["production_signal_impact"] == "none"
    assert catalog["policy"]["first_stage_rule"] == "observe_only"
    assert catalog["summary"]["source_count"] >= 2
    assert catalog["summary"]["recommended_first"] == [
        "ifind_mcp.search_news",
        "ifind_mcp.search_notice",
        "tushare_qfq.daily_kline",
    ]

    a_stock = catalog["sources"]["a_stock_data"]
    assert a_stock["recommended_stage"] == "evidence_trial"
    assert "margin_trading" in a_stock["high_value_datasets"]
    assert "limit_up_lhb" in a_stock["high_value_datasets"]
    trial = catalog["evidence_trials"]["a_stock_data.margin_trading"]
    assert trial["signal_impact"] == "none"
    assert trial["write_policy"] == "no_database_writes"
    assert "financing_balance" in trial["required_fields"]
    assert "do_not_block_signal_generation" == trial["failure_policy"]

    ftshare = catalog["sources"]["ftshare"]
    assert ftshare["recommended_stage"] == "provider_probe"
    assert "stock_list" in ftshare["high_value_datasets"]
    ifind = catalog["sources"]["ifind_mcp"]
    assert ifind["recommended_stage"] == "evidence_probe"
    assert "search_news" in ifind["high_value_datasets"]
    tushare_qfq = catalog["sources"]["tushare_qfq"]
    assert tushare_qfq["recommended_stage"] == "provider_probe"
    assert "adjustment_factor" in tushare_qfq["high_value_datasets"]
    assert catalog["sources"]["sec_data_api"]["recommended_stage"] == "provider_probe"
    assert "company_submissions" in catalog["sources"]["sec_data_api"]["high_value_datasets"]
    assert catalog["sources"]["hkexnews"]["recommended_stage"] == "provider_probe"
    assert "options_expiries" in catalog["sources"]["yfinance_global"]["high_value_datasets"]
    assert catalog["market_probe_links"]["US"]["filings"][0]["probe_id"] == "sec_filings"
    assert catalog["market_probe_links"]["US"]["fundamentals"][0]["probe_id"] == "sec_companyfacts"
    assert catalog["market_probe_links"]["HK"]["filings"][0]["source_id"] == "hkexnews"
    assert catalog["market_probe_links"]["HK"]["fundamentals"][0]["write_policy"] == "no_database_writes"


def test_external_data_sources_api_is_offline_by_default(monkeypatch):
    from backend.api.routes import system

    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run unless explicitly requested")

    monkeypatch.setattr(system, "probe_external_sources", fail_probe)

    payload = system.external_data_sources(probe=False)

    assert payload["policy"]["production_signal_impact"] == "none"
    assert payload["probes"] == {}
    assert payload["probe_summary"]["probed"] is False
    assert payload["probe_summary"]["safe_for_production_signal"] is False


def test_external_data_sources_api_attaches_probe_when_requested(monkeypatch):
    from backend.api.routes import system

    def fake_probe(symbol: str = "600519", market: str = "CN"):
        return {
            "ftshare": {
                "ok": True,
                "provider": "ftshare",
                "symbol": symbol,
                "market": market,
                "layer": "capital_flow",
                "latency_ms": 12,
                "sample_size": 1,
                "fields_present": ["symbol", "trade_date", "metric", "value", "source"],
                "write_policy": "no_database_writes",
                "signal_impact": "none",
                "error": None,
            },
            "ifind_mcp": {"ok": False, "enabled": False},
            "tushare_qfq": {"ok": False, "enabled": False},
        }

    monkeypatch.setattr(system, "probe_external_sources", fake_probe)

    payload = system.external_data_sources(probe=True, symbol="300308", market="CN")

    assert payload["probes"]["ftshare"]["ok"] is True
    assert payload["probes"]["ftshare"]["symbol"] == "300308"
    assert payload["probes"]["ftshare"]["market"] == "CN"
    assert payload["probe_summary"]["total_probes"] == 3
    assert payload["probe_summary"]["ok_count"] == 1
    assert payload["probe_summary"]["safe_for_research_scoring"] is False
    assert payload["probe_summary"]["rows"][0]["write_policy"] == "no_database_writes"
    ftshare_summary = next(row for row in payload["probe_summary"]["rows"] if row["probe_id"] == "ftshare")
    assert ftshare_summary["field_status"] == "required_fields_present"


def test_external_data_sources_api_validates_market():
    import pytest
    from fastapi import HTTPException

    from backend.api.routes import system

    with pytest.raises(HTTPException) as exc:
        system.external_data_sources(probe=False, market="JP")

    assert exc.value.status_code == 400


def test_ftshare_probe_uses_requests_with_timeout_and_size_guard(monkeypatch):
    import requests

    from backend.data import external_sources

    calls = []

    class Response:
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [{"stock_code": "600519.SH"}]}

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)

    result = external_sources.probe_ftshare_stock_list("600519", timeout_seconds=2.5)

    assert result["ok"] is True
    assert result["matched_symbol"] is True
    assert calls == [
        (
            external_sources.FTSHARE_STOCK_LIST_URL,
            {"User-Agent": "MingCang/1.0"},
            2.5,
        )
    ]


def test_ftshare_probe_reports_oversized_response(monkeypatch):
    import requests

    from backend.data import external_sources

    class Response:
        content = b"x" * 512_001

        def raise_for_status(self):
            return None

        def json(self):
            raise AssertionError("oversized response should be rejected before json parsing")

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    result = external_sources.probe_ftshare_stock_list("600519")

    assert result["ok"] is False
    assert result["error"] == "response too large"


def test_sec_filings_probe_maps_symbol_to_cik_and_checks_recent_fields(monkeypatch):
    from backend.data import external_sources

    urls = []

    def fake_fetch_json(url, timeout_seconds, max_bytes=512_000):
        urls.append((url, timeout_seconds, max_bytes))
        if url == external_sources.SEC_COMPANY_TICKERS_URL:
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        if url == external_sources.SEC_SUBMISSIONS_URL.format(cik="0000320193"):
            return {
                "filings": {
                    "recent": {
                        "form": ["10-K", "10-Q"],
                        "accessionNumber": ["0001", "0002"],
                        "filingDate": ["2026-01-01", "2026-04-01"],
                    }
                }
            }
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(external_sources, "_fetch_json", fake_fetch_json)

    result = external_sources.probe_sec_filings("AAPL", timeout_seconds=2.0)

    assert result["ok"] is True
    assert result["provider"] == "sec_data_api"
    assert result["market"] == "US"
    assert result["layer"] == "filings"
    assert result["sample_size"] == 2
    assert result["fields_present"] == ["form", "accessionNumber", "filingDate"]
    assert urls[0] == (external_sources.SEC_COMPANY_TICKERS_URL, 2.0, 2_000_000)


def test_sec_companyfacts_probe_reports_namespaces(monkeypatch):
    from backend.data import external_sources

    def fake_fetch_json(url, timeout_seconds, max_bytes=512_000):
        if url == external_sources.SEC_COMPANY_TICKERS_URL:
            return {"0": {"ticker": "MSFT", "cik_str": 789019}}
        if url == external_sources.SEC_COMPANYFACTS_URL.format(cik="0000789019"):
            return {"facts": {"us-gaap": {"Revenue": {}}, "dei": {"EntityCommonStockSharesOutstanding": {}}}}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(external_sources, "_fetch_json", fake_fetch_json)

    result = external_sources.probe_sec_companyfacts("MSFT")

    assert result["ok"] is True
    assert result["layer"] == "fundamentals"
    assert result["fields_present"] == ["dei", "us-gaap"]
    assert result["sample_size"] == 2


def test_yfinance_basic_probe_maps_hk_symbol(monkeypatch):
    from backend.data import external_sources

    calls = []

    class FakeTicker:
        def __init__(self, ticker):
            calls.append(ticker)
            self.info = {
                "marketCap": 1_000_000,
                "currency": "HKD",
                "longName": "Tencent Holdings",
            }

    monkeypatch.setattr(external_sources.yf, "Ticker", FakeTicker)

    result = external_sources.probe_yfinance_basic("700", market="HK")

    assert result["ok"] is True
    assert calls == ["0700.HK"]
    assert result["market"] == "HK"
    assert result["layer"] == "fundamentals"
    assert result["fields_present"] == ["marketCap", "currency", "longName"]


def test_yfinance_options_probe_reads_expiries_only(monkeypatch):
    from backend.data import external_sources

    class FakeTicker:
        options = ("2026-06-19", "2026-07-17")

        def __init__(self, ticker):
            self.ticker = ticker

    monkeypatch.setattr(external_sources.yf, "Ticker", FakeTicker)

    result = external_sources.probe_yfinance_options("AAPL")

    assert result["ok"] is True
    assert result["market"] == "US"
    assert result["layer"] == "derivatives"
    assert result["sample_size"] == 2


def test_hkex_filings_probe_checks_title_search_page(monkeypatch):
    from backend.data import external_sources

    calls = []

    def fake_fetch_text(url, timeout_seconds, max_bytes=512_000):
        calls.append((url, timeout_seconds, max_bytes))
        return "<html><title>HKEXnews</title><body>Headline Category</body></html>"

    monkeypatch.setattr(external_sources, "_fetch_text", fake_fetch_text)

    result = external_sources.probe_hkex_filings("700", timeout_seconds=1.5)

    assert result["ok"] is True
    assert result["provider"] == "hkexnews"
    assert result["market"] == "HK"
    assert result["layer"] == "filings"
    assert result["fields_present"] == ["HKEXnews", "Headline Category"]
    assert calls == [(external_sources.HKEXNEWS_TITLE_SEARCH_URL, 1.5, 512_000)]


def test_probe_external_sources_dispatches_by_market(monkeypatch):
    from backend.data import external_sources

    monkeypatch.setattr(external_sources, "probe_sec_filings", lambda symbol: {"symbol": symbol, "layer": "filings"})
    monkeypatch.setattr(external_sources, "probe_sec_companyfacts", lambda symbol: {"symbol": symbol, "layer": "fundamentals"})
    monkeypatch.setattr(external_sources, "probe_yfinance_basic", lambda symbol, market: {"symbol": symbol, "market": market})
    monkeypatch.setattr(external_sources, "probe_yfinance_options", lambda symbol: {"symbol": symbol, "layer": "derivatives"})
    monkeypatch.setattr(external_sources, "probe_hkex_filings", lambda symbol: {"symbol": symbol, "layer": "filings"})

    us = external_sources.probe_external_sources("AAPL", market="US")
    hk = external_sources.probe_external_sources("700", market="HK")

    assert sorted(us) == ["sec_companyfacts", "sec_filings", "yfinance_basic", "yfinance_options"]
    assert sorted(hk) == ["hkex_filings", "yfinance_basic"]
    assert us["yfinance_basic"]["market"] == "US"
    assert hk["yfinance_basic"]["market"] == "HK"


def test_probe_external_sources_rejects_unknown_market():
    import pytest

    from backend.data.external_sources import probe_external_sources

    with pytest.raises(ValueError, match="market must be CN, HK, or US"):
        probe_external_sources("7203", market="JP")


def test_probe_summary_reports_field_gaps_without_promoting_to_signals():
    from backend.data.external_sources import summarize_probe_results

    summary = summarize_probe_results(
        {
            "sec_filings": {
                "ok": True,
                "provider": "sec_data_api",
                "market": "US",
                "layer": "filings",
                "symbol": "AAPL",
                "latency_ms": 34,
                "sample_size": 2,
                "fields_present": ["form", "accessionNumber", "filingDate"],
                "write_policy": "no_database_writes",
                "signal_impact": "none",
                "error": None,
            },
            "yfinance_options": {
                "ok": False,
                "provider": "yfinance_global",
                "market": "US",
                "layer": "derivatives",
                "symbol": "AAPL",
                "sample_size": 0,
                "fields_present": [],
                "error": "no option expiries in yfinance payload",
            },
        },
        market="US",
        symbol="AAPL",
    )

    assert summary["probed"] is True
    assert summary["total_probes"] == 2
    assert summary["ok_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["safe_for_research_scoring"] is False
    assert summary["safe_for_production_signal"] is False
    filings = next(row for row in summary["rows"] if row["probe_id"] == "sec_filings")
    assert filings["field_status"] == "normalization_pending"
    assert "published_at" in filings["missing_fields"]
    assert "title" in filings["missing_fields"]
    assert filings["write_policy"] == "no_database_writes"
    options = next(row for row in summary["rows"] if row["probe_id"] == "yfinance_options")
    assert options["health_status"] == "failed"
    assert options["freshness_status"] == "unmeasured"


def test_probe_summary_handles_mixed_cn_probe_payload_shapes():
    from backend.data.external_sources import summarize_probe_results

    summary = summarize_probe_results(
        {
            "ftshare": {
                "ok": True,
                "symbol": "600519",
                "latency_ms": 10,
                "sample_size": 3200,
                "matched_symbol": True,
                "error": None,
            },
            "ifind_mcp": {"ok": False, "enabled": False},
            "tickflow": {
                "ok": True,
                "market": "CN",
                "layer": "kline",
                "fields_present": ["symbol", "date", "open", "high", "low", "close"],
                "rows": 5,
            },
        },
        market="CN",
        symbol="600519",
    )

    assert summary["total_probes"] == 3
    assert summary["ok_count"] == 2
    assert summary["safe_for_production_signal"] is False
    ftshare = next(row for row in summary["rows"] if row["probe_id"] == "ftshare")
    assert ftshare["layer"] == "capital_flow"
    assert ftshare["field_status"] == "normalization_pending"
    assert ftshare["provider"] == "ftshare"
    tickflow = next(row for row in summary["rows"] if row["probe_id"] == "tickflow")
    assert tickflow["field_status"] == "normalization_pending"
    assert "volume" in tickflow["missing_fields"]


def test_price_quality_module_reports_warning_without_blocking():
    from datetime import date, datetime

    from backend.data.database import Price
    from backend.data.price_quality import evaluate_price_quality

    row = {
        "date": date.today().isoformat(),
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "volume": 100,
        "source": "akshare_sina_cn",
        "fetched_at": datetime(2026, 6, 3, 8, 0).isoformat(),
        "adjustment": "qfq",
    }
    gate = evaluate_price_quality(
        market="CN",
        row=row,
        recent_rows=[
            Price(symbol="600519", date=row["date"], close=10.5, source="akshare_sina_cn", adjustment="qfq"),
            Price(symbol="600519", date=row["date"], close=10.4, source="eastmoney_cn", adjustment="qfq"),
        ],
    )

    assert gate.status == "warning"
    assert gate.blockers == []
    assert gate.warnings == ["mixed_recent_sources"]
    assert gate.to_payload() == {
        "status": "warning",
        "blockers": [],
        "warnings": ["mixed_recent_sources"],
        "recent_sources": ["akshare_sina_cn", "eastmoney_cn"],
        "recent_adjustments": ["qfq"],
    }


def test_price_quality_module_policy_thresholds_and_not_applicable_gate():
    from datetime import date

    from backend.data.database import Price
    from backend.data.price_quality import (
        PriceQualityPolicy,
        evaluate_price_quality,
        not_applicable_price_quality_gate,
    )

    row = {
        "date": date.today().isoformat(),
        "open": 25,
        "high": 30,
        "low": 20,
        "close": 25,
        "volume": 100,
        "source": "yfinance_hk",
        "adjustment": "auto_adjust",
    }
    gate = evaluate_price_quality(
        market="HK",
        row=row,
        recent_rows=[
            Price(symbol="700", date=row["date"], close=1, source="yfinance_hk", adjustment="auto_adjust"),
            Price(symbol="700", date=row["date"], close=25, source="yfinance_hk", adjustment="auto_adjust"),
        ],
        policy=PriceQualityPolicy(extreme_price_range_ratio=10.0),
    )

    assert gate.status == "blocked"
    assert "extreme_recent_price_range" in gate.blockers
    assert not_applicable_price_quality_gate().to_payload() == {
        "status": "not_applicable",
        "blockers": [],
        "warnings": [],
        "recent_sources": [],
        "recent_adjustments": [],
    }


def test_price_quality_module_reports_unavailable_without_local_row():
    from backend.data.price_quality import evaluate_price_quality

    gate = evaluate_price_quality(market="CN", row=None, recent_rows=[])

    assert gate.to_payload() == {
        "status": "unavailable",
        "blockers": ["no_local_price_row"],
        "warnings": [],
        "recent_sources": [],
        "recent_adjustments": [],
    }


def test_global_data_context_returns_read_only_envelope_for_hk_price(test_db):
    from datetime import date

    from backend.data.database import Price, Stock
    from backend.data.global_data import build_global_data_context

    test_db.add(Stock(symbol="700", name="Tencent", market="HK", active=True))
    test_db.add(
        Price(
            symbol="700",
            market="HK",
            date=date.today().isoformat(),
            open=300,
            high=310,
            low=299,
            close=305,
            volume=1000,
        )
    )
    test_db.commit()

    payload = build_global_data_context(test_db, market="HK", symbol="700", intent="daily_ohlcv")

    assert payload["status"] == "available"
    assert payload["write_policy"] == "no_database_writes"
    assert payload["signal_impact"] == "none"
    assert payload["safe_for_research_scoring"] is False
    assert payload["safe_for_production_signal"] is False
    assert payload["freshness_status"] == "latest_local_bar"
    assert payload["quality_gate"] == {
        "status": "passed",
        "blockers": [],
        "warnings": [],
        "recent_sources": [],
        "recent_adjustments": [],
    }
    assert payload["normalization"]["currency"] == "HKD"
    assert payload["pit_gate"]["status"] == "passed_for_read_only"
    assert payload["data"]["close"] == 305


def test_global_data_context_blocks_cn_price_without_provenance(test_db):
    from backend.data.database import Price
    from backend.data.global_data import build_global_data_context

    test_db.add(Price(
        symbol="600519",
        date="2026-06-02",
        open=1300,
        high=1320,
        low=1290,
        close=1307.22,
        volume=100,
    ))
    test_db.commit()

    payload = build_global_data_context(test_db, market="CN", symbol="600519", intent="daily_ohlcv")

    assert payload["status"] == "available"
    assert payload["quality_gate"]["status"] == "blocked"
    assert "missing_provenance_source" in payload["quality_gate"]["blockers"]
    assert "missing_provenance_fetched_at" in payload["quality_gate"]["blockers"]
    assert "missing_provenance_adjustment" in payload["quality_gate"]["blockers"]
    assert payload["freshness_status"] == "blocked"
    assert payload["safe_for_production_signal"] is False


def test_global_data_context_blocks_mixed_recent_adjustments(test_db):
    from datetime import date, datetime, timedelta

    from backend.data.database import Price
    from backend.data.global_data import build_global_data_context
    latest_day = date.today().isoformat()
    previous_day = (date.today() - timedelta(days=1)).isoformat()

    test_db.add(Price(
        symbol="300308",
        date=previous_day,
        open=1100,
        high=1120,
        low=1090,
        close=1110,
        volume=100,
        source="tickflow_cn",
        fetched_at=datetime(2026, 6, 1, 8, 0),
        adjustment="forward_additive",
    ))
    test_db.add(Price(
        symbol="300308",
        date=latest_day,
        open=1130,
        high=1200,
        low=1120,
        close=1191.81,
        volume=100,
        source="akshare_sina_cn",
        fetched_at=datetime(2026, 6, 2, 8, 0),
        adjustment="qfq",
    ))
    test_db.commit()

    payload = build_global_data_context(test_db, market="CN", symbol="300308", intent="daily_ohlcv")

    assert payload["quality_gate"]["status"] == "blocked"
    assert "mixed_recent_adjustments" in payload["quality_gate"]["blockers"]
    assert payload["quality_gate"]["recent_adjustments"] == ["forward_additive", "qfq"]
    assert payload["quality_gate"]["warnings"] == ["mixed_recent_sources"]
    assert payload["safe_for_production_signal"] is False


def test_global_data_context_reports_unavailable_price_without_local_row(test_db):
    from backend.data.global_data import build_global_data_context

    payload = build_global_data_context(test_db, market="CN", symbol="600519", intent="daily_ohlcv")

    assert payload["status"] == "unavailable"
    assert payload["data"] is None
    assert payload["freshness_status"] == "unmeasured"
    assert payload["quality_gate"] == {
        "status": "unavailable",
        "blockers": ["no_local_price_row"],
        "warnings": [],
        "recent_sources": [],
        "recent_adjustments": [],
    }
    assert payload["safe_for_production_signal"] is False


def test_global_data_context_reports_missing_non_price_adapter(test_db):
    from backend.data.global_data import build_global_data_context

    payload = build_global_data_context(test_db, market="US", symbol="AAPL", intent="filings")

    assert payload["status"] == "observe_only_unavailable"
    assert payload["data"] is None
    assert payload["field_status"] == "missing_fields"
    assert "published_at" in payload["missing_fields"]
    assert payload["pit_gate"]["blockers"] == ["no_normalized_row"]
    assert payload["quality_gate"] == {
        "status": "not_applicable",
        "blockers": [],
        "warnings": [],
        "recent_sources": [],
        "recent_adjustments": [],
    }
    assert payload["safe_for_production_signal"] is False


def test_market_capability_catalog_exposes_ifind_runtime_status(monkeypatch):
    from backend.config import settings
    from backend.data.market_capabilities import build_market_capability_catalog

    monkeypatch.setattr(settings, "ifind_mcp_enabled", True)
    monkeypatch.setattr(settings, "ifind_mcp_token", "unit-token")
    monkeypatch.setattr(settings, "ifind_mcp_qps_limit", 0.5)

    catalog = build_market_capability_catalog()
    cn_layers = catalog["markets_detail"]["CN"]["layers"]
    fundamentals = next(row for row in cn_layers if row["id"] == "fundamentals")
    ifind = next(row for row in fundamentals["probe_links"] if row["probe_id"] == "ifind_mcp")

    assert ifind["enabled"] is True
    assert ifind["configured"] is True
    assert ifind["qps_limit"] == 0.5
    assert "read-only evidence" in ifind["role"]


def test_probe_health_ledger_aggregates_multiple_summaries():
    from backend.data.global_data import build_probe_health_ledger, probe_summary_from_payload

    summaries = [
        probe_summary_from_payload(
            {
                "sec_filings": {
                    "ok": True,
                    "provider": "sec_data_api",
                    "market": "US",
                    "layer": "filings",
                    "symbol": "AAPL",
                    "latency_ms": 20,
                    "sample_size": 2,
                    "fields_present": ["form"],
                    "error": None,
                }
            },
            market="US",
            symbol="AAPL",
        ),
        probe_summary_from_payload(
            {
                "sec_filings": {
                    "ok": False,
                    "provider": "sec_data_api",
                    "market": "US",
                    "layer": "filings",
                    "symbol": "MSFT",
                    "latency_ms": 40,
                    "sample_size": 0,
                    "fields_present": [],
                    "error": "timeout",
                }
            },
            market="US",
            symbol="MSFT",
        ),
    ]

    ledger = build_probe_health_ledger(summaries, generated_at="2026-06-03T00:00:00+00:00")

    assert ledger["write_policy"] == "no_database_writes"
    assert ledger["total_rows"] == 2
    row = ledger["health_rows"][0]
    assert row["provider"] == "sec_data_api"
    assert row["ok_count"] == 1
    assert row["ok_rate"] == 0.5
    assert row["continuous_health_status"] == "needs_more_samples"
    assert row["safe_for_production_signal"] is False


def test_m41_probe_health_ledger_tool_aggregates_input_json(tmp_path):
    import json

    from backend.tools import m41_probe_health_ledger

    input_path = tmp_path / "probe.json"
    output_path = tmp_path / "ledger.json"
    input_path.write_text(
        json.dumps({
            "probe_summary": {
                "market": "HK",
                "symbol": "700",
                "rows": [
                    {
                        "probe_id": "hkex_filings",
                        "provider": "hkexnews",
                        "market": "HK",
                        "layer": "filings",
                        "symbol": "700",
                        "ok": True,
                        "latency_ms": 15,
                        "sample_size": 1,
                        "missing_fields": ["published_at"],
                    }
                ],
            }
        }),
        encoding="utf-8",
    )

    ledger = m41_probe_health_ledger.main([
        "--input-json",
        str(input_path),
        "--output",
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert ledger["total_rows"] == 1
    assert payload["safety"]["network_probes_attempted"] is False
    assert payload["safety"]["database_writes_attempted"] is False
    assert payload["health_rows"][0]["provider"] == "hkexnews"
