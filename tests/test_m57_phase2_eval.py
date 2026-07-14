from __future__ import annotations

import json
import sqlite3


def _fixture(case_count: int = 20, industries: int = 3):
    cases = []
    for index in range(case_count):
        cases.append({
            "id": f"case-{index:02d}",
            "industry": f"industry-{index % industries}",
            "as_of": "2026-07-15",
            "question": "证据支持什么，哪些条件会证伪？",
            "evidence_snapshot": {"facts": [f"fact-{index}"]},
            "output_template_version": "research_report.v1",
            "arms": {
                arm: {"response": f"{arm} response", "cost_units": 100 if arm == "base" else 120}
                for arm in ("base", "memory", "serenity", "both")
            },
        })
    return {"cases": cases}


def _scores(case_count: int = 20, *, both_quality: float = 0.80):
    return {
        "default_daily_llm_calls": 0,
        "signal_boundary_diff": 0,
        "cases": [{
            "case_id": f"case-{index:02d}",
            "arms": {
                "base": {
                    "source_fidelity": 0.60,
                    "key_fact_coverage": 0.60,
                    "contradiction_handling": 0.60,
                    "falsifiability": 0.60,
                    "hallucination_error_rate": 0.10,
                },
                "memory": {
                    "source_fidelity": 0.65,
                    "key_fact_coverage": 0.65,
                    "contradiction_handling": 0.65,
                    "falsifiability": 0.65,
                    "hallucination_error_rate": 0.10,
                },
                "serenity": {
                    "source_fidelity": 0.70,
                    "key_fact_coverage": 0.70,
                    "contradiction_handling": 0.70,
                    "falsifiability": 0.70,
                    "hallucination_error_rate": 0.09,
                },
                "both": {
                    "source_fidelity": both_quality,
                    "key_fact_coverage": both_quality,
                    "contradiction_handling": both_quality,
                    "falsifiability": both_quality,
                    "hallucination_error_rate": 0.08,
                },
            },
        } for index in range(case_count)],
    }


def test_four_arm_eval_passes_only_when_all_registered_gates_pass():
    from backend.tools.m57_phase2_eval import evaluate_scores

    result = evaluate_scores(_fixture(), _scores())
    assert result["decision"] == "GO_PHASE_3_4"
    assert all(result["gates"].values())
    assert all(delta >= 0.15 for delta in result["quality_deltas"].values())


def test_four_arm_eval_holds_on_sample_or_quality_failure():
    from backend.tools.m57_phase2_eval import evaluate_scores

    too_few = evaluate_scores(_fixture(case_count=6), _scores(case_count=6))
    assert too_few["decision"] == "HOLD_STOP_PHASE_3_4"
    assert too_few["gates"]["sample_cases"] is False

    weak = evaluate_scores(_fixture(), _scores(both_quality=0.70))
    assert weak["decision"] == "HOLD_STOP_PHASE_3_4"
    assert weak["gates"]["source_fidelity_delta"] is False


def test_blind_packets_do_not_disclose_arm_keys(tmp_path):
    from backend.tools.m57_phase2_eval import build_blind_packets

    fixture = _fixture(case_count=1, industries=1)
    result = build_blind_packets(fixture, tmp_path)
    packet = (tmp_path / "packets" / "case-00.md").read_text(encoding="utf-8")
    assert result["status"] == "AWAITING_BLIND_SCORES"
    assert "方案甲" in packet
    assert "base response" in packet
    assert "base:" not in packet
    assert (tmp_path / "answer_key.json").exists()


def test_fixture_rejects_cross_arm_input_drift():
    import pytest

    from backend.tools.m57_phase2_eval import validate_fixture

    fixture = _fixture(case_count=1, industries=1)
    fixture["cases"][0]["arms"]["both"]["input_fingerprint"] = "wrong"
    with pytest.raises(ValueError, match="fingerprint differs"):
        validate_fixture(fixture)


def test_eval_module_does_not_call_retired_serenity_analyzer():
    import inspect

    import backend.tools.m57_phase2_eval as module

    source = inspect.getsource(module)
    assert "serenity_chokepoint" not in source
    assert ".analyze(" not in source


def test_live_audit_counts_only_readable_report_files(tmp_path):
    from backend.tools.m57_phase2_eval import audit_live_readiness

    db_path = tmp_path / "audit.db"
    readable = tmp_path / "readable.md"
    readable.write_text("# report", encoding="utf-8")
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE decision_runs (id INTEGER, run_type TEXT, input_snapshot_json TEXT)")
    con.executemany(
        "INSERT INTO decision_runs VALUES (?, 'deep_research', ?)",
        [
            (1, json.dumps({"report_path": str(readable)})),
            (2, json.dumps({"report_path": str(tmp_path / "missing.md")})),
            (3, json.dumps({})),
        ],
    )
    con.commit()
    con.close()

    result = audit_live_readiness(db_path)

    assert result["recorded_report_paths"] == 2
    assert result["independent_cases"] == 1
    assert result["sample_gate_pass"] is False
    assert result["missing_report_paths"] == [str(tmp_path / "missing.md")]
