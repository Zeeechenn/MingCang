from __future__ import annotations

import json


def _stage2_report(*, exit_before_entry: bool = False) -> dict:
    closed_trade = {
        "symbol": "AAA",
        "entry_date": "2026-06-05" if exit_before_entry else "2026-06-01",
        "exit_date": "2026-06-04",
        "entry_signal_date": "2026-06-01",
    }
    return {
        "schema_version": "atlas_test4_stage2b_shadow.v1",
        "run_mode": "read_only_atlas_stage2b_forward_shadow",
        "non_promoting": True,
        "production_unchanged": True,
        "writes_production_db": False,
        "writes_isolated_gate_db": True,
        "touches_test2_state": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "atlas_enabled_required": False,
        "source_db": "sqlite:////prod.db",
        "gate_db": "sqlite:////tmp/gate.sqlite",
        "start": "2026-06-01",
        "end": "2026-06-12",
        "arms": {
            "test2_baseline": {
                "summary": {"weighted_total_pct": 15.68},
                "closed_trades": [closed_trade],
                "open_holdings": [],
            },
            "atlas_signal_overlay": {
                "summary": {"weighted_total_pct": 8.79},
                "closed_trades": [],
                "open_holdings": [],
                "gate_filter": {"allowed_signals": 67, "blocked_signals": 704},
                "delta_vs_test2_baseline": {"weighted_total_pct": -6.89},
            },
        },
        "stage2b_maturity_rule": {
            "baseline_trades_current": 14,
            "atlas_signal_overlay_trades_current": 6,
            "min_matured_trades_per_runnable_arm": 30,
            "min_forward_weeks": 8,
            "mature": False,
        },
        "blockers": ["stage2b_forward_sample_not_mature", "non_promoting_shadow_only"],
        "decision": {"decision": "collect_forward_shadow", "promotable": False},
    }


def _gate_b_report(verdict: str = "REJECT") -> dict:
    return {
        "verdict": verdict,
        "reason": "delta_or_icir_or_npass_failed",
        "n_realized": 646,
        "n_pass": 47,
        "n_fail": 599,
        "avg_net_return_pass": -0.0460325,
        "avg_net_return_fail": -0.0194864,
        "avg_net_return_delta": -0.0265461,
    }


def test_strict_report_aborts_when_stage2_trade_exits_before_entry():
    from backend.tools.atlas_stage2b_strict_gate import build_strict_report

    report = build_strict_report(
        stage2_report=_stage2_report(exit_before_entry=True),
        gate_b_report=_gate_b_report("PROMOTE"),
        realized_count=10,
    )

    assert report["schema_version"] == "atlas_stage2b_strict_gate.v1"
    assert report["non_promoting"] is True
    assert report["production_unchanged"] is True
    assert report["writes_production_db"] is False
    assert report["touches_test2_state"] is False
    assert report["atlas_enabled_required"] is False
    assert report["sanity_checks"]["exit_before_entry_count"] == 1
    assert report["sanity_checks"]["passed"] is False
    assert report["decision"]["verdict"] == "ABORT"
    assert report["decision"]["promotable"] is False
    assert "stage2b_exit_before_entry_date" in report["decision"]["blockers"]


def test_strict_report_keeps_reject_non_promoting_until_all_gates_pass():
    from backend.tools.atlas_stage2b_strict_gate import build_strict_report

    report = build_strict_report(
        stage2_report=_stage2_report(),
        gate_b_report=_gate_b_report("REJECT"),
        realized_count=646,
    )

    assert report["decision"]["verdict"] == "REJECT"
    assert report["decision"]["decision"] == "keep_atlas_dormant"
    assert report["decision"]["promotable"] is False
    assert report["sanity_checks"]["passed"] is True
    assert report["stage2_summary"]["baseline_weighted_total_pct"] == 15.68
    assert report["stage2_summary"]["atlas_signal_overlay_weighted_total_pct"] == 8.79
    assert report["stage2_summary"]["delta_weighted_total_pct"] == -6.89
    assert report["stage2_summary"]["mature"] is False
    assert "stage2b_forward_sample_not_mature" in report["decision"]["blockers"]


def test_strict_report_does_not_promote_when_gate_b_passes_but_stage2_is_immature():
    from backend.tools.atlas_stage2b_strict_gate import build_strict_report

    report = build_strict_report(
        stage2_report=_stage2_report(),
        gate_b_report=_gate_b_report("PROMOTE"),
        realized_count=646,
    )

    assert report["decision"]["verdict"] == "INCONCLUSIVE"
    assert report["decision"]["decision"] == "keep_atlas_dormant"
    assert report["decision"]["promotable"] is False
    assert "stage2b_forward_sample_not_mature" in report["decision"]["blockers"]


def test_write_artifacts_emits_strict_json_and_markdown(tmp_path):
    from backend.tools.atlas_stage2b_strict_gate import (
        build_strict_report,
        write_artifacts,
    )

    report = build_strict_report(
        stage2_report=_stage2_report(),
        gate_b_report=_gate_b_report("REJECT"),
        realized_count=646,
    )
    json_output = tmp_path / "strict.json"
    markdown_output = tmp_path / "strict.md"

    write_artifacts(report, json_output=json_output, markdown_output=markdown_output)

    payload = json.loads(json_output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")
    assert payload["run_mode"] == "read_only_atlas_stage2b_strict_gate"
    assert "Atlas Stage 2b Strict Gate" in markdown
    assert "keep_atlas_dormant" in markdown
