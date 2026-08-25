from __future__ import annotations

import json
from pathlib import Path

from scripts.update_daily_pipeline_state import SCHEMA_VERSION, main, update_state


def test_daily_pipeline_state_is_atomic_and_preserves_one_loop_completion(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    first = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="03_one_loop",
        message="audit passed",
        one_loop_status="complete",
    )
    final = update_state(
        state_path,
        day="2026-08-25",
        status="aborted",
        step="04_live_broad",
        message="command failed",
        llm_calls=2,
    )

    assert first["schema_version"] == SCHEMA_VERSION
    assert final["status"] == "aborted"
    assert final["one_loop_status"] == "complete"
    assert final["llm_calls_total"] == 2
    assert [event["step"] for event in final["events"]] == ["03_one_loop", "04_live_broad"]
    assert json.loads(state_path.read_text(encoding="utf-8")) == final
    assert list(tmp_path.glob(".*.tmp")) == []


def test_daily_pipeline_state_resets_for_a_new_date(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    update_state(
        state_path,
        day="2026-08-25",
        status="complete",
        step="done",
        message="finished",
    )
    result = update_state(
        state_path,
        day="2026-08-26",
        status="running",
        step="01_test2",
        message="started",
    )

    assert result["date"] == "2026-08-26"
    assert len(result["events"]) == 1
    assert result["one_loop_status"] == "pending"
    assert "finished_at" not in result


def test_track_writes_per_track_status_and_keeps_top_level_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    one_loop = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="03_one_loop",
        message="audit passed",
        one_loop_status="complete",
        track="one_loop",
    )

    assert one_loop["tracks"]["one_loop"] == {
        "status": "running",
        "step": "03_one_loop",
        "message": "audit passed",
        "updated_at": one_loop["updated_at"],
    }
    # Backward compatible: existing top-level fields are unchanged.
    assert one_loop["status"] == "running"
    assert one_loop["current_step"] == "03_one_loop"
    assert one_loop["message"] == "audit passed"
    assert one_loop["one_loop_status"] == "complete"

    live = update_state(
        state_path,
        day="2026-08-25",
        status="aborted",
        step="04_live_broad",
        message="stale prices",
        track="live",
    )

    assert live["tracks"]["one_loop"]["status"] == "running"  # untouched by the live update
    assert live["tracks"]["live"] == {
        "status": "aborted",
        "step": "04_live_broad",
        "message": "stale prices",
        "updated_at": live["updated_at"],
    }
    assert live["status"] == "aborted"
    assert live["current_step"] == "04_live_broad"


def test_tracks_key_always_present_even_without_track_arg(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    result = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="01_test2",
        message="started",
    )
    assert result["tracks"] == {}


def test_gate_json_attaches_to_live_track(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(
        json.dumps({"schema_version": "live_track_gate.v1", "verdict": "pass"}),
        encoding="utf-8",
    )

    result = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="04_live_broad",
        message="gate checked",
        gate_json=str(gate_path),
    )

    assert result["tracks"]["live"]["gate"] == {
        "schema_version": "live_track_gate.v1",
        "verdict": "pass",
    }


def test_gate_json_missing_file_does_not_fail_command(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    gate_path = tmp_path / "does_not_exist.json"

    result = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="04_live_broad",
        message="gate missing",
        gate_json=str(gate_path),
    )

    assert "error" in result["tracks"]["live"]["gate"]


def test_gate_json_malformed_does_not_fail_command(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text("{not valid json", encoding="utf-8")

    result = update_state(
        state_path,
        day="2026-08-25",
        status="running",
        step="04_live_broad",
        message="gate malformed",
        gate_json=str(gate_path),
    )

    assert "error" in result["tracks"]["live"]["gate"]


def test_track_and_gate_json_via_cli(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")

    rc = main(
        [
            "--path",
            str(state_path),
            "--date",
            "2026-08-25",
            "--status",
            "running",
            "--step",
            "04_live_broad",
            "--message",
            "cli test",
            "--track",
            "live",
            "--gate-json",
            str(gate_path),
        ]
    )

    assert rc == 0
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["tracks"]["live"]["status"] == "running"
    assert payload["tracks"]["live"]["gate"] == {"verdict": "pass"}
