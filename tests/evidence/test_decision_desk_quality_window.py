from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime

import pytest

from backend.evidence import decision_desk_readiness as readiness
from backend.evidence.decision_desk_readiness import CARD_TYPES, build_readiness_report

DAY = "2026-09-16"
SCHEDULE = {
    "timezone": "Asia/Singapore", "contract_start": DAY,
    "scheduled_at": [f"2026-09-{d}T23:30:00+08:00" for d in (16, 17, 18, 21, 22)],
}
NOW = datetime.fromisoformat("2026-09-17T12:00:00+08:00")


def save_collection(root, day=DAY):
    folder = root / day / "collection"
    folder.mkdir(parents=True)
    snapshot = b"synthetic snapshot; never a production database"
    digest = hashlib.sha256(snapshot).hexdigest()
    continuity = {"status": "complete", "days": [{
        "date": day, "status": "complete", "run_id": "run-1", "checks": {
            "artifact_panel": "complete", "batch_envelope_match": "matched",
            "run_envelope": "complete", "signal_batch_identity": "unique", "signal_run": "complete",
        },
    }]}
    panel = {"as_of": day, "ledger_commit_state": "committed",
             "artifact_contract": {"close_confirmed": True, "source_job_run_id": "run-1"},
             "cards": [{"card_type": k, "status": "ready"} for k in CARD_TYPES]}
    nav = {"snapshot": {"sha256_before": digest, "sha256_after": digest},
           "lineage": {"price_basis_issues": [], "price_window": {"end": day},
                       "corporate_actions": {"status": "authoritative"}}}
    saved = build_readiness_report(as_of=day, continuity=continuity, panel=panel, nav_evidence=nav)
    collected = f"{day}T23:31:00+08:00"
    saved.update(collected_at=collected, prospective_collection=True, snapshot_sha256=digest)
    values = {"continuity.json": continuity, "panel.json": panel, "nav.json": nav, "readiness.json": saved}
    for name, value in values.items():
        (folder / name).write_text(json.dumps(value))
    (folder / "snapshot.db").write_bytes(snapshot)
    manifest = {"as_of": day, "collected_at": collected, "snapshot_unchanged": True,
                "writes_production": False, "provider_called": False,
                "scope": "quality_collection_not_economic_trial",
                "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def report(root, now=NOW, schedule=None):
    return readiness.build_quality_window_report(
        runs_root=root, schedule=schedule or SCHEDULE, evaluated_at=now,
    )


def update_json(folder, name, change, *, rehash=True):
    path = folder / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    if rehash and name != "manifest.json":
        manifest = json.loads((folder / "manifest.json").read_text())
        manifest["sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps(manifest))


def test_window_keeps_missing_and_not_due_in_fixed_denominators(tmp_path):
    save_collection(tmp_path)
    result = report(tmp_path, datetime.fromisoformat("2026-09-18T12:00:00+08:00"))
    assert [d["status"] for d in result["days"]] == ["passed", "missing", "not_due", "not_due", "not_due"]
    assert result["counts"] == {"scheduled": 5, "due": 2, "passed": 1, "blocked": 0,
                                 "failed": 0, "missing": 1, "not_due": 3}
    assert result["gates"]["output_quality"]["pass_rate_due"] == 0.5
    assert result["gates"]["economic"]["status"] == "blocked"
    assert result["human_completion"]["status"] == "not_evaluated"
    assert result["certifies_returns"] is False


def test_no_due_day_has_no_success_rate_and_does_not_read_future(tmp_path):
    (tmp_path / DAY).symlink_to(tmp_path / "absent", target_is_directory=True)
    result = report(tmp_path, datetime.fromisoformat("2026-09-16T23:29:59+08:00"))
    assert result["counts"]["not_due"] == 5
    assert result["gates"]["output_quality"]["pass_rate_due"] is None
    assert result["gates"]["output_quality"]["status"] == "pending"


def test_exact_due_time_is_due_and_partial_attempt_is_failed(tmp_path):
    (tmp_path / DAY).mkdir()
    result = report(tmp_path, datetime.fromisoformat(SCHEDULE["scheduled_at"][0]))
    assert result["days"][0]["status"] == "failed"
    assert result["counts"]["due"] == 1


@pytest.mark.parametrize("name", ["panel.json", "continuity.json", "nav.json", "readiness.json", "snapshot.db"])
def test_tampered_bytes_fail_closed_without_modifying_input(tmp_path, name):
    folder = save_collection(tmp_path)
    path = folder / name
    path.write_bytes(path.read_bytes() + b" ")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    result = report(tmp_path)
    assert result["days"][0]["status"] == "failed"
    assert f"hash_mismatch:{name}" in result["days"][0]["blockers"]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize("name,change,reason", [
    ("manifest.json", lambda d: d.update(as_of="2026-09-15"), "collection_date_mismatch"),
    ("manifest.json", lambda d: d.update(collected_at="2026-09-18T00:00:00+08:00"), "collection_time_invalid"),
    ("readiness.json", lambda d: d.update(prospective_collection=False), "not_prospective_collection"),
    ("readiness.json", lambda d: d["gates"]["economic"].update(status="passed"), "saved_gates_mismatch"),
    ("nav.json", lambda d: d["snapshot"].update(sha256_before="b" * 64), "snapshot_binding_mismatch"),
    ("continuity.json", lambda d: d["days"].append(d["days"][0]), "day_identity_not_unique"),
    ("continuity.json", lambda d: d.update(days=None), "invalid_artifact_shape"),
])
def test_invalid_or_rewritten_evidence_is_not_accepted(tmp_path, name, change, reason):
    folder = save_collection(tmp_path)
    update_json(folder, name, change)
    result = report(tmp_path)
    assert result["days"][0]["status"] == "failed"
    assert reason in result["days"][0]["blockers"]


def test_a_valid_degraded_day_remains_blocked(tmp_path):
    folder = save_collection(tmp_path)
    update_json(folder, "panel.json", lambda d: d["cards"][4].update(status="degraded"))
    update_json(folder, "readiness.json", lambda d: (
        d["gates"]["output_quality"].update(status="blocked", blockers=["watchtower:degraded"]),
        d["card_states"].update(watchtower="degraded"),
    ))
    result = report(tmp_path)
    assert result["days"][0]["status"] == "blocked"
    assert result["card_blockers"] == {"watchtower:degraded": [DAY]}


@pytest.mark.parametrize("kind", ["file", "collection", "day"])
def test_symlinked_input_cannot_escape_the_collection(tmp_path, kind):
    folder = save_collection(tmp_path / "runs")
    path = {"file": folder / "panel.json", "collection": folder, "day": folder.parent}[kind]
    outside = tmp_path / "outside"
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    assert report(tmp_path / "runs")["days"][0]["status"] == "failed"


def test_snapshot_sidecars_are_rejected(tmp_path):
    folder = save_collection(tmp_path)
    (folder / "snapshot.db-wal").touch()
    assert "snapshot_sidecar_present" in report(tmp_path)["days"][0]["blockers"]


def test_completed_window_does_not_pass_economics_or_certify_users(tmp_path):
    for slot in SCHEDULE["scheduled_at"]:
        save_collection(tmp_path, slot[:10])
    result = report(tmp_path, datetime.fromisoformat("2026-09-23T00:00:00+08:00"))
    assert result["status"] == "passed"
    assert result["counts"]["passed"] == 5
    assert result["gates"]["output_quality"]["pass_rate_due"] == 1
    assert result["gates"]["economic"]["status"] == "blocked"
    assert result["economic_trial_ready"] is False


def test_zero_due_day_requires_an_aware_clock(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        report(tmp_path, datetime(2026, 9, 16))


def test_declared_timezone_determines_date(tmp_path):
    save_collection(tmp_path)
    slots = ["2026-09-16T15:30:00+00:00"]
    result = report(tmp_path, schedule={**SCHEDULE, "scheduled_at": slots})
    assert result["days"][0]["as_of"] == DAY
    assert result["days"][0]["status"] == "passed"


def test_changed_file_during_read_cannot_pass(tmp_path, monkeypatch):
    save_collection(tmp_path)
    digest = readiness._file_digest
    calls = 0

    def changing(folder, name):
        nonlocal calls
        calls += 1
        return "b" * 64 if calls > 1 else digest(folder, name)

    monkeypatch.setattr(readiness, "_file_digest", changing)
    assert "collection_changed_during_read" in report(tmp_path)["days"][0]["blockers"]


@pytest.mark.parametrize("slots", [[], [SCHEDULE["scheduled_at"][0]] * 2,
                                    list(reversed(SCHEDULE["scheduled_at"])),
                                    ["2026-09-15T23:30:00+08:00"], ["2026-09-16T23:30:00"]])
def test_bad_schedule_is_rejected(tmp_path, slots):
    with pytest.raises(ValueError):
        report(tmp_path, schedule={**SCHEDULE, "scheduled_at": slots})


def test_cli_emits_machine_readable_failure_without_writes(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(SCHEDULE))
    result = subprocess.run([sys.executable, "-m", "backend.evidence.decision_desk_readiness",
                             "--runs-root", str(tmp_path / "runs"), "--schedule", str(path),
                             "--evaluated-at", NOW.isoformat()], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)["counts"]["missing"] == 1
    assert not (tmp_path / "runs").exists()
