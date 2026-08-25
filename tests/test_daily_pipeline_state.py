from __future__ import annotations

import json
from pathlib import Path

from scripts.update_daily_pipeline_state import SCHEMA_VERSION, update_state


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
