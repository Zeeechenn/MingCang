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


def test_track_status_can_finalize_independently_of_the_top_level_status(
    tmp_path: Path,
) -> None:
    """收尾时顶层还是 running，两条 track 却必须能各自定局。

    这是 2026-08-27/08-28 两轮 state 里 tracks 停在 running 的直接原因。
    """
    state_path = tmp_path / "state.json"
    update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="08_ab",
        message="AB replay",
        track="one_loop",
    )
    finalized = update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="done",
        message="Track A (①②③⑧) ok",
        track="one_loop",
        track_status="complete",
        track_outcome="ok",
    )

    assert finalized["tracks"]["one_loop"]["status"] == "complete"
    assert finalized["tracks"]["one_loop"]["outcome"] == "ok"
    assert finalized["tracks"]["one_loop"]["finished_at"] == finalized["updated_at"]
    # The top level is deliberately left running until the terminal write.
    assert finalized["status"] == "running"
    assert "finished_at" not in finalized


def test_track_outcome_skipped_and_not_attempted_stay_running_but_are_labelled(
    tmp_path: Path,
) -> None:
    """skipped/not_attempted 既不是失败也不是跑完：状态位留 running，语义靠
    outcome 这一位表达，但仍要打 finished_at 说明这条 track 已定局。"""
    state_path = tmp_path / "state.json"
    skipped = update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="done",
        message="行情门未过",
        track="live",
        track_status="running",
        track_outcome="skipped",
    )

    assert skipped["tracks"]["live"]["status"] == "running"
    assert skipped["tracks"]["live"]["outcome"] == "skipped"
    assert "finished_at" in skipped["tracks"]["live"]

    not_attempted = update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="done",
        message="--one-loop-only 主动跳过",
        track="live",
        track_status="running",
        track_outcome="not_attempted",
    )

    assert not_attempted["tracks"]["live"]["status"] != "complete"
    assert not_attempted["tracks"]["live"]["outcome"] == "not_attempted"


def test_track_update_preserves_a_previously_attached_gate_verdict(tmp_path: Path) -> None:
    """⑤⑥⑦ 与收尾的每次 --track live 写入都不能抹掉 04b 挂上的行情门判决。"""
    state_path = tmp_path / "state.json"
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps({"verdict": "pass", "coverage": 1.0}), encoding="utf-8")

    update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="04b_live_gate",
        message="gate evaluated",
        track="live",
        gate_json=str(gate_path),
    )
    later = update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="05_funnel",
        message="live subset funnel",
        track="live",
    )
    finalized = update_state(
        state_path,
        day="2026-08-28",
        status="running",
        step="done",
        message="Track B (④⑤⑥⑦) ok",
        track="live",
        track_status="complete",
        track_outcome="ok",
    )

    assert later["tracks"]["live"]["gate"] == {"verdict": "pass", "coverage": 1.0}
    assert finalized["tracks"]["live"]["gate"] == {"verdict": "pass", "coverage": 1.0}
    assert finalized["tracks"]["live"]["status"] == "complete"


def test_track_status_via_cli(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    rc = main(
        [
            "--path",
            str(state_path),
            "--date",
            "2026-08-28",
            "--status",
            "running",
            "--step",
            "done",
            "--message",
            "Track A ok",
            "--track",
            "one_loop",
            "--track-status",
            "complete",
            "--track-outcome",
            "ok",
        ]
    )

    assert rc == 0
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["tracks"]["one_loop"]["status"] == "complete"
    assert payload["tracks"]["one_loop"]["outcome"] == "ok"
