def test_external_source_catalog_prioritizes_evidence_before_signal_inputs():
    from backend.data.external_sources import build_external_source_catalog

    catalog = build_external_source_catalog()

    assert catalog["policy"]["production_signal_impact"] == "none"
    assert catalog["policy"]["first_stage_rule"] == "observe_only"
    assert catalog["summary"]["source_count"] >= 2
    assert catalog["summary"]["recommended_first"] == ["a_stock_data", "ftshare"]

    a_stock = catalog["sources"]["a_stock_data"]
    assert a_stock["recommended_stage"] == "evidence_trial"
    assert "margin_trading" in a_stock["high_value_datasets"]
    assert "limit_up_lhb" in a_stock["high_value_datasets"]

    ftshare = catalog["sources"]["ftshare"]
    assert ftshare["recommended_stage"] == "provider_probe"
    assert "stock_list" in ftshare["high_value_datasets"]


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
            }
        }

    monkeypatch.setattr(system, "probe_external_sources", fake_probe)

    payload = system.external_data_sources(probe=True, symbol="300308")

    assert payload["probes"]["ftshare"]["ok"] is True
    assert payload["probes"]["ftshare"]["symbol"] == "300308"
