from __future__ import annotations

import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.evidence import decision_desk_session as session
from backend.evidence.decision_desk_manifest import validate_manifest
from tests.evidence.test_decision_desk_session import FakeProvider, cutoff, manifest_fixture, plan


def design_fixture():
    days = [(date(2026, 1, 1) + timedelta(days=n)).isoformat() for n in range(80)]
    return {
        "family_id": "declared-family",
        "candidates": [{"candidate_id": "candidate-a", "parameters_hash": "a" * 64}],
        "selected_candidate_id": "candidate-a",
        "trial_count": 1,
        "registration_hash": "b" * 64,
        "sessions": days,
        "label_horizon_sessions": 3,
        "purge_sessions": 3,
        "embargo_sessions": 2,
        "outer_folds": [
            {
                "fold_id": "outer-1",
                "train_sessions": days[:30],
                "test_sessions": days[35:40],
                "inner_folds": [
                    {
                        "fold_id": "inner-1",
                        "train_sessions": days[:10],
                        "test_sessions": days[15:20],
                    }
                ],
            }
        ],
        "holdout_sessions": days[65:70],
        "holdout_sha256": hashlib.sha256(b"held-out fixture").hexdigest(),
        "initial_lifecycle": "experimental",
    }


def manifest_v2():
    manifest, requests = manifest_fixture()
    manifest["schema_version"] = "decision_desk_manifest.v2"
    manifest["evaluation"] = design_fixture()
    return manifest, requests


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "_now", lambda: datetime(2026, 9, 16, 2, tzinfo=UTC))
    manifest, requests = manifest_v2()
    session.freeze_plan(tmp_path, "research", plan(), manifest=manifest)
    artifact = tmp_path / "holdout.bin"
    artifact.write_bytes(b"held-out fixture")
    return tmp_path, requests, artifact


def attempt(root, requests, name="attempt"):
    return session.run_frozen_attempt(
        output_root=root,
        experiment_id="research",
        arm_id="raw",
        attempt_id=name,
        cutoff=cutoff(),
        provider=FakeProvider(),
        request_bytes=requests["raw"],
    )


@pytest.mark.parametrize(
    "error",
    [
        "candidate",
        "trials",
        "purge",
        "calendar",
        "inner_leak",
        "inner_overlap",
        "holdout_leak",
        "embargo",
        "duplicate_id",
        "stable",
    ],
)
def test_invalid_design_cannot_freeze_or_reserve(tmp_path, error):
    manifest, _ = manifest_v2()
    design = manifest["evaluation"]
    days = design["sessions"]
    if error == "candidate":
        design["selected_candidate_id"] = "undeclared"
    elif error == "trials":
        design["trial_count"] = 0
    elif error == "purge":
        design["purge_sessions"] = 2
    elif error == "calendar":
        design["sessions"][0] = "not-a-date"
    elif error == "inner_leak":
        design["outer_folds"][0]["inner_folds"][0]["test_sessions"] = days[35:40]
    elif error == "inner_overlap":
        duplicate = copy.deepcopy(design["outer_folds"][0]["inner_folds"][0])
        duplicate["fold_id"] = "inner-2"
        design["outer_folds"][0]["inner_folds"].append(duplicate)
    elif error == "holdout_leak":
        design["holdout_sessions"] = days[38:40]
    elif error == "duplicate_id":
        design["outer_folds"][0]["inner_folds"][0]["fold_id"] = "outer-1"
    elif error == "stable":
        design["initial_lifecycle"] = "stable"
    else:
        second = copy.deepcopy(design["outer_folds"][0])
        second.update(fold_id="outer-2", train_sessions=days[:41], test_sessions=days[48:50])
        second["inner_folds"][0]["fold_id"] = "inner-2"
        design["outer_folds"].append(second)
    with pytest.raises(ValueError):
        session.freeze_plan(tmp_path, "invalid", plan(), manifest=manifest)
    assert not (tmp_path / "invalid").exists()


def test_valid_design_retains_canonical_manifest_and_no_promotion(frozen):
    root, requests, _ = frozen
    receipt = attempt(root, requests)
    assert receipt["status"] == "passed"
    assert receipt["claims"]["profitability_certified"] is False
    assert session.inspect_session(root, "research")["research"]["lifecycle"] == "experimental"


def test_lifecycle_halts_attempts_and_cannot_promote_stable(frozen):
    root, requests, _ = frozen
    with pytest.raises(ValueError):
        session.set_research_lifecycle(
            root, "research", lifecycle="stable", reason="not authorized"
        )
    session.set_research_lifecycle(
        root, "research", lifecycle="dormant", reason="wait for new evidence"
    )
    with pytest.raises(RuntimeError, match="lifecycle"):
        attempt(root, requests)
    assert session.inspect_session(root, "research")["arms"]["raw"]["reserved_model_calls"] == 0
    session.set_research_lifecycle(
        root, "research", lifecycle="experimental", reason="resume offline checks"
    )
    assert attempt(root, requests)["status"] == "passed"
    session.set_research_lifecycle(root, "research", lifecycle="archived", reason="finished")
    with pytest.raises(ValueError):
        session.set_research_lifecycle(root, "research", lifecycle="experimental", reason="reopen")


def test_holdout_read_once_and_blocks_new_model_attempts(frozen):
    root, requests, artifact = frozen
    assert session.read_frozen_holdout(root, "research", artifact=artifact) == b"held-out fixture"
    with pytest.raises(RuntimeError, match="already reserved"):
        session.read_frozen_holdout(root, "research", artifact=artifact)
    with pytest.raises(RuntimeError, match="holdout"):
        attempt(root, requests)
    state = session.inspect_session(root, "research")["research"]
    assert state["holdout_access_reserved"] is True and state["holdout_result"] == "read"


def test_failed_hash_still_consumes_access(frozen):
    root, requests, artifact = frozen
    artifact.write_bytes(b"switched file")
    with pytest.raises(ValueError, match="hash mismatch"):
        session.read_frozen_holdout(root, "research", artifact=artifact)
    assert (
        session.inspect_session(root, "research")["research"]["holdout_result"] == "hash_mismatch"
    )
    with pytest.raises(RuntimeError):
        attempt(root, requests)


def test_unfinished_attempt_prevents_holdout_reservation(frozen):
    root, requests, artifact = frozen

    def provider(payload):
        with pytest.raises(RuntimeError, match="unfinished"):
            session.read_frozen_holdout(root, "research", artifact=artifact)
        assert not session.inspect_session(root, "research")["research"]["holdout_access_reserved"]
        return FakeProvider()(payload)

    receipt = session.run_frozen_attempt(
        output_root=root, experiment_id="research", arm_id="raw", attempt_id="running",
        cutoff=cutoff(), provider=provider, request_bytes=requests["raw"],
    )
    assert receipt["status"] == "passed"
    assert session.read_frozen_holdout(root, "research", artifact=artifact) == b"held-out fixture"


def test_failed_file_read_still_consumes_access(frozen):
    root, _, artifact = frozen
    artifact.unlink()
    with pytest.raises(FileNotFoundError):
        session.read_frozen_holdout(root, "research", artifact=artifact)
    assert session.inspect_session(root, "research")["research"]["holdout_result"] == "read_failed"


def test_fifo_is_rejected_without_waiting_for_writer(frozen):
    root, _, artifact = frozen
    artifact.unlink()
    os.mkfifo(artifact)
    with pytest.raises(OSError, match="regular file"):
        session.read_frozen_holdout(root, "research", artifact=artifact)
    assert session.inspect_session(root, "research")["research"]["holdout_result"] == "read_failed"


def test_concurrent_holdout_read_has_one_winner(frozen):
    root, _, artifact = frozen

    def read(_):
        try:
            return session.read_frozen_holdout(root, "research", artifact=artifact)
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(read, range(2)))
    assert results.count(b"held-out fixture") == 1 and results.count(None) == 1


def test_corrupt_event_chain_blocks_session(frozen):
    root, requests, _ = frozen
    session.set_research_lifecycle(root, "research", lifecycle="dormant", reason="pause")
    path = root / "research/budget/research.events.json"
    data = json.loads(path.read_text())
    data["events"][0]["details"]["to"] = "experimental"
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="chain"):
        attempt(root, requests)


def test_v1_stays_compatible_without_evaluation_metadata():
    manifest, _ = manifest_fixture()
    assert validate_manifest(manifest, plan()) == manifest
