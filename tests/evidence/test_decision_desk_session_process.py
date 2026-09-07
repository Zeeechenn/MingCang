import json
import subprocess
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.evidence.decision_desk_session import freeze_plan, inspect_session, run_frozen_attempt


def _plan():
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    return {
        "problem": "same_model_raw_vs_desk",
        "date_window": {"start": today, "end": today},
        "shared_input_hash": "a" * 64, "risk_hash": "b" * 64, "execution_hash": "c" * 64,
        "budget_policy": "matched",
        "arms": [{"arm_id": arm, "account_id": arm,
                  "requested_model": "fake",
                  "budget": {"total_model_calls": 1, "total_cost_cny": 1,
                             "max_attempt_cost_cny": 1}} for arm in ("raw", "desk")],
    }


def test_process_exit_keeps_budget_reservation_after_restart(tmp_path):
    plan = _plan()
    freeze_plan(tmp_path, "exp", plan)
    program = '''
import os, sys
from pathlib import Path
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from backend.evidence.decision_desk_session import run_frozen_attempt
def crash(request):
    os._exit(23)
run_frozen_attempt(output_root=Path(sys.argv[1]), experiment_id="exp", arm_id="raw",
    attempt_id="interrupted", cutoff=datetime.now(UTC), request_bytes=b"exact input",
    provider=crash)
'''
    completed = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 23, completed.stderr
    snapshot = inspect_session(tmp_path, "exp")
    assert snapshot["arms"]["raw"]["reserved_model_calls"] == 1
    assert snapshot["arms"]["raw"]["receipts"]["missing"] == 1
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_frozen_attempt(output_root=tmp_path, experiment_id="exp", arm_id="raw",
                           attempt_id="retry", cutoff=datetime.now(UTC), request_bytes=b"retry",
                           provider=lambda request: pytest.fail("must not call again"))
    saved = tmp_path / "exp" / "raw" / "interrupted" / "request.bin"
    assert saved.read_bytes() == b"exact input"
    assert not (saved.parent / "receipt.json").exists()
    assert json.loads((tmp_path / "exp" / "freeze.json").read_text())["plan"] == plan


@pytest.mark.parametrize("arm_id", ["budget", "freeze.json", "BUDGET.LOCK", "DESK"])
def test_freeze_rejects_reserved_or_case_colliding_arm_paths(tmp_path, arm_id):
    plan = _plan()
    plan["arms"][0]["arm_id"] = arm_id
    with pytest.raises(ValueError):
        freeze_plan(tmp_path, "exp", plan)
    assert not (tmp_path / "exp").exists()


def test_cost_overrun_stops_the_other_arm_too(tmp_path):
    freeze_plan(tmp_path, "exp", _plan())
    first = run_frozen_attempt(
        output_root=tmp_path, experiment_id="exp", arm_id="raw", attempt_id="overrun",
        cutoff=datetime.now(UTC), request_bytes=b"input",
        provider=lambda request: {"resolved_model": "fake", "response_bytes": b"output",
                                  "usage": {"model_calls": 1, "cost_cny": 2}},
    )
    assert first["status"] == "failed"
    with pytest.raises(RuntimeError, match="prior receipt usage exceeds budget"):
        run_frozen_attempt(
            output_root=tmp_path, experiment_id="exp", arm_id="desk", attempt_id="next",
            cutoff=datetime.now(UTC), request_bytes=b"input",
            provider=lambda request: pytest.fail("must not call the other arm"),
        )


@pytest.mark.parametrize("corruption", ["filename", "receipt_identity"])
def test_prior_record_corruption_blocks_new_call(tmp_path, corruption):
    freeze_plan(tmp_path, "exp", _plan())
    receipt = run_frozen_attempt(
        output_root=tmp_path, experiment_id="exp", arm_id="raw", attempt_id="first",
        cutoff=datetime.now(UTC), request_bytes=b"input",
        provider=lambda request: {"resolved_model": "fake", "response_bytes": b"output",
                                  "usage": {"model_calls": 1, "cost_cny": 0.1}},
    )
    assert receipt["session"]["account_id"] == "raw"
    if corruption == "filename":
        reservation = tmp_path / "exp/budget/raw/first.reservation.json"
        reservation.rename(reservation.with_name("wrong.reservation.json"))
        message = "reservation attempt filename mismatch"
    else:
        path = tmp_path / "exp/raw/first/receipt.json"
        payload = json.loads(path.read_text())
        payload["arm_id"] = "desk"
        path.write_text(json.dumps(payload))
        message = "prior receipt identity mismatch"
    with pytest.raises(RuntimeError, match=message):
        run_frozen_attempt(
            output_root=tmp_path, experiment_id="exp", arm_id="desk", attempt_id="next",
            cutoff=datetime.now(UTC), request_bytes=b"input",
            provider=lambda request: pytest.fail("corrupt evidence must stop new calls"),
        )


def test_cutoff_window_uses_same_shanghai_day_for_both_timezones(tmp_path, monkeypatch):
    import backend.evidence.decision_desk_session as session

    instant = datetime(2026, 9, 7, 18, tzinfo=UTC)  # September 8 in Shanghai
    monkeypatch.setattr(session, "_now", lambda: instant)
    plan = _plan()
    plan["date_window"] = {"start": "2026-09-08", "end": "2026-09-08"}
    frozen = freeze_plan(tmp_path, "exp", plan)
    assert frozen["date_window_timezone"] == "Asia/Shanghai"
    for arm, cutoff in [("raw", instant), ("desk", instant.astimezone(ZoneInfo("Asia/Shanghai")))]:
        receipt = run_frozen_attempt(
            output_root=tmp_path, experiment_id="exp", arm_id=arm, attempt_id="first",
            cutoff=cutoff, request_bytes=b"input",
            provider=lambda request: {"resolved_model": "fake", "response_bytes": b"output",
                                      "usage": {"model_calls": 1, "cost_cny": 0.1}},
        )
        assert receipt["status"] == "passed"


@pytest.mark.parametrize("problem", ["same_model_raw_vs_desk", "same_desk_model_comparison"])
def test_frozen_question_must_match_requested_models(tmp_path, problem):
    plan = _plan()
    plan["problem"] = problem
    if problem == "same_model_raw_vs_desk":
        plan["arms"][1]["requested_model"] = "different"
    with pytest.raises(ValueError, match="requested models"):
        freeze_plan(tmp_path, "exp", plan)
    assert not (tmp_path / "exp").exists()


def test_copying_frozen_experiment_cannot_silently_change_identity(tmp_path):
    freeze_plan(tmp_path, "original", _plan())
    (tmp_path / "original").rename(tmp_path / "renamed")
    with pytest.raises(ValueError, match="freeze experiment identity mismatch"):
        run_frozen_attempt(
            output_root=tmp_path, experiment_id="renamed", arm_id="raw", attempt_id="first",
            cutoff=datetime.now(UTC), request_bytes=b"input",
            provider=lambda request: pytest.fail("must not use another experiment's freeze"),
        )
    assert not (tmp_path / "renamed/budget").exists()
