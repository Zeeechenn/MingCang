from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.evidence.decision_desk_recording import record_model_observation

SH = ZoneInfo("Asia/Shanghai")


class FakeProvider:
    def __init__(self, *, resolved_model: str = "gpt-6", response: bytes = b'{"ok": true}', usage: dict | None = None):
        self.resolved_model = resolved_model
        self.response = response
        self.usage = usage or {"model_calls": 1, "cost_cny": 0.25}
        self.seen_requests: list[bytes] = []

    def __call__(self, request_bytes: bytes) -> dict:
        self.seen_requests.append(request_bytes)
        return {
            "resolved_model": self.resolved_model,
            "response_bytes": self.response,
            "usage": self.usage,
        }


def cutoff() -> datetime:
    return datetime(2026, 9, 8, 9, 0, tzinfo=SH)


def budget(max_model_calls=1, max_cost_cny=1.0) -> dict:
    return {"max_model_calls": max_model_calls, "max_cost_cny": max_cost_cny}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_records_success_with_saved_request_response_and_artifact_index(tmp_path) -> None:
    provider = FakeProvider(response=b'{"decision": "watch"}')

    receipt = record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_payload={"symbol": "300308", "features": [1, 2]},
        provider=provider,
        budget=budget(),
        tool_observations={"broker_snapshot": b'{"position_pct": 0.12}'},
    )

    attempt_dir = tmp_path / "exp-001" / "raw" / "20260908"
    request_bytes = (attempt_dir / "request.bin").read_bytes()
    response_bytes = (attempt_dir / "response.bin").read_bytes()
    saved_receipt = load_json(attempt_dir / "receipt.json")
    assert receipt["status"] == "passed"
    assert saved_receipt == receipt
    assert provider.seen_requests == [request_bytes]
    assert response_bytes == b'{"decision": "watch"}'
    assert receipt["visible_input"]["path"] == "exp-001/raw/20260908/request.bin"
    assert receipt["model_receipt"]["resolved_model"] == "gpt-6"
    assert receipt["tool_observations"][0]["provider_observed"] is False
    assert receipt["artifacts"][receipt["visible_input"]["sha256"]] == "exp-001/raw/20260908/request.bin"
    assert receipt["claims"] == {
        "complete_runner": False,
        "trading_ledger": False,
        "os_isolation_proven": False,
        "profitability_certified": False,
        "tool_observations_provider_verified": False,
    }


def test_request_bytes_are_passed_exactly_to_provider(tmp_path) -> None:
    provider = FakeProvider()

    record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="desk",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_bytes=b"raw prompt bytes",
        provider=provider,
        budget=budget(),
    )

    assert provider.seen_requests == [b"raw prompt bytes"]


def test_provider_exception_saves_failed_receipt_without_dropping_attempt(tmp_path) -> None:
    def provider(_: bytes) -> dict:
        raise RuntimeError("provider exploded")

    receipt = record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_bytes=b"request",
        provider=provider,
        budget=budget(),
    )

    saved = load_json(tmp_path / "exp-001" / "raw" / "20260908" / "receipt.json")
    assert receipt["status"] == "failed"
    assert saved["status"] == "failed"
    assert "provider_exception" in saved["errors"]
    assert saved["response"] is None


def test_model_replacement_is_recorded_failed_not_silent_fallback(tmp_path) -> None:
    receipt = record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_bytes=b"request",
        provider=FakeProvider(resolved_model="gpt-5"),
        budget=budget(),
    )

    assert receipt["status"] == "failed"
    assert receipt["model_receipt"]["requested_model"] == "gpt-6"
    assert receipt["model_receipt"]["resolved_model"] == "gpt-5"
    assert "resolved_model_mismatch" in receipt["errors"]


def test_repeated_attempt_directory_is_not_overwritten(tmp_path) -> None:
    provider = FakeProvider()
    kwargs = {
        "output_root": tmp_path,
        "experiment_id": "exp-001",
        "arm_id": "raw",
        "attempt_id": "20260908",
        "requested_model": "gpt-6",
        "cutoff": cutoff(),
        "request_bytes": b"request",
        "provider": provider,
        "budget": budget(),
    }
    record_model_observation(**kwargs)

    with pytest.raises(FileExistsError):
        record_model_observation(**kwargs)

    assert len(provider.seen_requests) == 1


@pytest.mark.parametrize("bad_id", ["../exp", "/abs", "nested/path", "", ".", "with space"])
def test_path_identifiers_cannot_escape_or_create_nested_paths(tmp_path, bad_id) -> None:
    with pytest.raises(ValueError, match="invalid path identifier"):
        record_model_observation(
            output_root=tmp_path,
            experiment_id=bad_id,
            arm_id="raw",
            attempt_id="20260908",
            requested_model="gpt-6",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
            budget=budget(),
        )


def test_output_root_inside_repo_is_rejected(tmp_path) -> None:
    repo_path = Path.cwd() / ".tmp_decision_recording_test"
    with pytest.raises(ValueError, match="output_root must be outside the repository"):
        record_model_observation(
            output_root=repo_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            requested_model="gpt-6",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
            budget=budget(),
        )


@pytest.mark.parametrize(
    "bad_budget",
    [
        {"max_model_calls": 0, "max_cost_cny": 1},
        {"max_model_calls": 1, "max_cost_cny": -1},
        {"max_model_calls": True, "max_cost_cny": 1},
        {"max_model_calls": 1, "max_cost_cny": float("inf")},
    ],
)
def test_invalid_budget_is_rejected_before_provider_call(tmp_path, bad_budget) -> None:
    provider = FakeProvider()

    with pytest.raises(ValueError, match="invalid budget"):
        record_model_observation(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            requested_model="gpt-6",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=provider,
            budget=bad_budget,
        )

    assert provider.seen_requests == []


def test_reported_usage_over_budget_is_saved_failed(tmp_path) -> None:
    receipt = record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_bytes=b"request",
        provider=FakeProvider(usage={"model_calls": 1, "cost_cny": 1.25}),
        budget=budget(max_cost_cny=1.0),
    )

    assert receipt["status"] == "failed"
    assert "usage_exceeds_budget" in receipt["errors"]


def test_reported_usage_must_be_legal_and_single_call(tmp_path) -> None:
    receipt = record_model_observation(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        requested_model="gpt-6",
        cutoff=cutoff(),
        request_bytes=b"request",
        provider=FakeProvider(usage={"model_calls": 2, "cost_cny": 0.1}),
        budget=budget(),
    )

    assert receipt["status"] == "failed"
    assert "usage_exceeds_budget" in receipt["errors"]


def test_cutoff_must_be_timezone_aware(tmp_path) -> None:
    with pytest.raises(ValueError, match="cutoff must be timezone-aware"):
        record_model_observation(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            requested_model="gpt-6",
            cutoff=datetime(2026, 9, 8, 9),
            request_bytes=b"request",
            provider=FakeProvider(),
            budget=budget(),
        )
