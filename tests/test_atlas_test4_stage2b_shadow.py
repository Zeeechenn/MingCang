from __future__ import annotations

import json

import pytest

test2_ab_models = pytest.importorskip(
    "paper_trading.test2_ab_models",
    reason="paper_trading/test2 frozen baseline is local-only and not checked into CI",
)
PriceBar = test2_ab_models.PriceBar
Signal = test2_ab_models.Signal


def test_build_report_runs_signal_overlay_without_touching_test2_state(tmp_path):
    from backend.tools import atlas_test4_stage2b_shadow as tool

    signals = [
        Signal("AAA", "Alpha", "2026-06-01", 0.0, 70.0, 70.0, 9.0, 13.0),
        Signal("BBB", "Beta", "2026-06-01", 0.0, 65.0, 65.0, 18.0, 24.0),
    ]
    prices = {
        ("AAA", "2026-06-02"): PriceBar("AAA", "2026-06-02", 10.0, 10.5, 9.8, 10.2),
        ("BBB", "2026-06-02"): PriceBar("BBB", "2026-06-02", 20.0, 20.5, 19.8, 20.1),
        ("AAA", "2026-06-03"): PriceBar("AAA", "2026-06-03", 10.2, 10.4, 10.0, 10.3),
        ("BBB", "2026-06-03"): PriceBar("BBB", "2026-06-03", 20.2, 20.4, 20.0, 20.3),
    }
    gate_rows = [
        {"symbol": "AAA", "signal_date": "2026-06-01", "gate_pass_variant": True, "card_pass": True},
        {"symbol": "BBB", "signal_date": "2026-06-01", "gate_pass_variant": False, "card_pass": True},
    ]
    test2_state = tmp_path / "test2_ab_state.json"
    test2_state.write_text('{"frozen": true}', encoding="utf-8")

    report = tool.build_report(
        signals=signals,
        prices=prices,
        universe={"AAA", "BBB"},
        sectors={},
        gate_rows=gate_rows,
        start="2026-06-01",
        end="2026-06-03",
        source_db="sqlite:////prod.db",
        gate_db=str(tmp_path / "gate.sqlite"),
        test2_state_path=test2_state,
    )

    assert report["schema_version"] == "atlas_test4_stage2b_shadow.v1"
    assert report["run_mode"] == "read_only_atlas_stage2b_forward_shadow"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_db"] is False
    assert report["touches_test2_state"] is False
    assert report["atlas_enabled_required"] is False
    assert report["arms"]["test2_baseline"]["status"] == "runnable"
    assert report["arms"]["atlas_signal_overlay"]["status"] == "runnable"
    assert report["arms"]["atlas_signal_overlay"]["gate_filter"]["allowed_signals"] == 1
    assert report["arms"]["atlas_signal_overlay"]["gate_filter"]["blocked_signals"] == 1
    assert report["arms"]["atlas_exit_overlay"]["status"] == "registered_not_started"
    assert report["arms"]["atlas_entry_exit_overlay"]["status"] == "registered_not_started"
    assert report["decision"]["promotable"] is False
    assert "stage2b_forward_sample_not_mature" in report["blockers"]
    assert "exit_overlay_not_implemented" in report["blockers"]
    assert test2_state.read_text(encoding="utf-8") == '{"frozen": true}'


def test_write_artifacts_keeps_json_and_markdown_in_requested_paths(tmp_path):
    from backend.tools import atlas_test4_stage2b_shadow as tool

    report = {
        "generated_at": "2026-06-07T00:00:00+00:00",
        "run_mode": "read_only_atlas_stage2b_forward_shadow",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_db": False,
        "touches_test2_state": False,
        "start": "2026-06-01",
        "end": "2026-06-03",
        "arms": {
            "test2_baseline": {"status": "runnable", "summary": {"weighted_total_pct": 1.2}},
            "atlas_signal_overlay": {
                "status": "runnable",
                "summary": {"weighted_total_pct": 0.8},
                "gate_filter": {"allowed_signals": 1, "blocked_signals": 1},
            },
            "atlas_exit_overlay": {"status": "registered_not_started"},
            "atlas_entry_exit_overlay": {"status": "registered_not_started"},
        },
        "blockers": ["stage2b_forward_sample_not_mature"],
        "decision": {"decision": "collect_forward_shadow", "promotable": False},
    }
    json_output = tmp_path / "stage2b.json"
    markdown_output = tmp_path / "stage2b.md"

    tool.write_artifacts(report, json_output=json_output, markdown_output=markdown_output)

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["run_mode"] == "read_only_atlas_stage2b_forward_shadow"
    assert "Atlas Test4 Stage 2b Forward Shadow" in markdown
    assert "stage2b_forward_sample_not_mature" in markdown
