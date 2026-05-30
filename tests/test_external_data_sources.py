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


def test_external_data_sources_api_is_offline_by_default(monkeypatch):
    from backend.api.routes import system

    def fail_probe(*args, **kwargs):
        raise AssertionError("probe should not run unless explicitly requested")

    monkeypatch.setattr(system, "probe_external_sources", fail_probe)

    payload = system.external_data_sources(probe=False)

    assert payload["policy"]["production_signal_impact"] == "none"
    assert payload["probes"] == {}


def test_external_data_sources_api_attaches_probe_when_requested(monkeypatch):
    from backend.api.routes import system

    def fake_probe(symbol: str = "600519"):
        return {
            "ftshare": {
                "ok": True,
                "symbol": symbol,
                "latency_ms": 12,
                "sample_size": 1,
                "error": None,
            },
            "ifind_mcp": {"ok": False, "enabled": False},
            "tushare_qfq": {"ok": False, "enabled": False},
        }

    monkeypatch.setattr(system, "probe_external_sources", fake_probe)

    payload = system.external_data_sources(probe=True, symbol="300308")

    assert payload["probes"]["ftshare"]["ok"] is True
    assert payload["probes"]["ftshare"]["symbol"] == "300308"
