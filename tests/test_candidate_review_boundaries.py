from datetime import datetime

import pytest

from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.database import FinancialMetric, Price
from backend.data.fundamentals import compute_piotroski_factors_strict
from backend.evidence.decision_desk_validation import validate_experiment_spec


def test_strict_pack_does_not_autoflush_other_sections(test_db):
    pending = Price(symbol="600519", date="2026-09-07", close=100)
    test_db.add(pending)
    build_stock_context_pack("600519", as_of=datetime(2026, 9, 7), db=test_db,
                             strict_research_inputs=True)
    assert pending in test_db.new
    assert pending.id is None


def test_strict_comparison_requires_previous_year_not_any_same_quarter(test_db):
    for year in [2024, 2026]:
        test_db.add(FinancialMetric(symbol="600519", report_date=f"{year}-03-31",
                                   disclosure_date=f"{year}-04-30", net_profit=10,
                                   total_assets=100, operating_cf=11,
                                   fetched_at=datetime(2026, 1, 1)))
    test_db.commit()
    result = compute_piotroski_factors_strict("600519", test_db, as_of="2026-09-07")
    assert result["comparison_period"] is None
    assert result["factors"]["roa_improving"] is None


def test_strict_nonempty_financials_explain_unavailable_in_text():
    pack = {"symbol": "600519", "as_of": "2026-09-07", "financials": {
        "latest": {"report_date": "2026-03-31"},
        "piotroski": {"available": False, "score": 0, "score_denominator": 0,
                      "reason": "insufficient_usable_factors"}}}
    text = render_context_text(pack, strict_research_inputs=True)
    assert "Piotroski unavailable reason=insufficient_usable_factors" in text


@pytest.mark.parametrize("problem,key", [
    ("same_model_raw_vs_desk", "workflow"),
    ("same_desk_model_comparison", "workflow"),
    ("same_model_workflow_improvement", "workflow_version"),
])
def test_experiment_malformed_workflow_is_blocked_not_exception(problem, key):
    result = validate_experiment_spec({"problem": problem, "arms": [{key: []}, {key: {}}]})
    assert result["status"] == "blocked"


def test_validation_cli_signals_blocked_to_shell(tmp_path, capsys):
    from backend.evidence.decision_desk_validation import main

    path = tmp_path / "invalid.json"
    path.write_text("{}")
    assert main([str(path)]) == 1
    assert '"status": "blocked"' in capsys.readouterr().out


def test_candidate_preview_connects_strict_inputs_and_draft_without_model_or_writes(test_db, monkeypatch):
    from backend.data.database import ResearchState
    from backend.research.copilot import prepare_candidate_copilot

    def forbidden(*args, **kwargs):
        raise AssertionError("candidate must not call providers or write state")

    monkeypatch.setattr("backend.research.copilot.get_provider", forbidden)
    monkeypatch.setattr(test_db, "commit", forbidden)
    monkeypatch.setattr(test_db, "flush", forbidden)
    result = prepare_candidate_copilot(
        "600519", db=test_db, as_of=datetime.fromisoformat("2026-09-07T16:00:00+08:00"),
        account_id="research", account_snapshot={}, proposal={"action": "buy", "target_pct": .12},
        risk_limits={"max_position_pct": .15, "max_new_position_pct": .05},
        historical_target={"date": "2026-09-04", "target_pct": .12},
    )
    assert result["draft"]["position_state"] == "unknown"
    assert result["draft"]["target_pct"] is None
    assert result["context"]["financials"]["reason"] == "no_disclosed_financials_as_of"
    assert result["model_called"] is False
    assert result["can_execute"] is False
    with test_db.no_autoflush:
        assert test_db.query(ResearchState).count() == 0


def test_candidate_tiny_context_cannot_produce_numeric_target(test_db):
    from backend.research.copilot import prepare_candidate_copilot

    result = prepare_candidate_copilot(
        "600519", db=test_db, as_of=datetime.fromisoformat("2026-09-07T16:00:00+08:00"),
        account_id="research", account_snapshot={"symbol": "600519", "account_id": "research",
            "source": "fixture", "observed_at": "2026-09-07T15:00:00+08:00", "position_pct": 0},
        proposal={"action": "buy", "target_pct": .12},
        risk_limits={"max_position_pct": .15, "max_new_position_pct": .05}, max_chars=1,
    )
    assert result["context_status"] == "unavailable"
    assert result["draft"]["target_pct"] is None


def test_retained_observation_bytes_detect_tampering_and_root_escape(tmp_path):
    import hashlib

    from backend.evidence.decision_desk_validation import verify_observation_artifacts

    data = b"actual model-visible serialized input\n"
    digest = hashlib.sha256(data).hexdigest()
    root = tmp_path / "evidence"
    root.mkdir()
    path = root / "observation.bin"
    path.write_bytes(data)
    spec = {"arms": [{"visible_input_hashes": [digest]}], "artifacts": {digest: path.name}}
    result = verify_observation_artifacts(spec, root)
    assert result["status"] == "passed"
    assert result["verified_files"] == 1
    assert result["proves_model_observed_bytes"] is False
    path.write_bytes(b"tampered")
    assert verify_observation_artifacts(spec, root)["status"] == "blocked"

    outside = tmp_path / "outside.bin"
    outside.write_bytes(data)
    spec["artifacts"][digest] = "../outside.bin"
    assert verify_observation_artifacts(spec, root)["status"] == "blocked"
    path.unlink()
    path.symlink_to(outside)
    spec["artifacts"][digest] = path.name
    assert verify_observation_artifacts(spec, root)["status"] == "blocked"


def test_recorded_request_and_response_resolve_in_artifact_verifier(tmp_path):
    from backend.evidence.decision_desk_recording import record_model_observation
    from backend.evidence.decision_desk_validation import verify_observation_artifacts

    receipt = record_model_observation(
        output_root=tmp_path, experiment_id="exp", arm_id="raw", attempt_id="one",
        requested_model="fake", cutoff=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        request_bytes=b"input", budget={"max_model_calls": 1, "max_cost_cny": 1},
        provider=lambda request: {"resolved_model": "fake", "response_bytes": b"output",
                                  "usage": {"model_calls": 1, "cost_cny": 0}},
    )
    spec = {"arms": [{"visible_input_hashes": [receipt["visible_input"]],
                      "model_receipt": receipt["model_receipt"]}], "artifacts": receipt["artifacts"]}
    assert verify_observation_artifacts(spec, tmp_path)["status"] == "passed"


def test_recording_rejects_symlink_parent_before_provider(tmp_path):
    from backend.evidence.decision_desk_recording import record_model_observation

    root = tmp_path / "records"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "exp").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        record_model_observation(
            output_root=root, experiment_id="exp", arm_id="raw", attempt_id="one",
            requested_model="fake", cutoff=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            request_bytes=b"input", budget={"max_model_calls": 1, "max_cost_cny": 1},
            provider=lambda request: pytest.fail("must not call provider"),
        )
    assert list(outside.iterdir()) == []
