from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.evidence.decision_desk_session import freeze_plan, inspect_session, run_frozen_attempt

SH = ZoneInfo("Asia/Shanghai")
UTC = ZoneInfo("UTC")
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


@pytest.fixture(autouse=True)
def fixed_session_clock(monkeypatch) -> None:
    import backend.evidence.decision_desk_session as session

    monkeypatch.setattr(session, "_now", lambda: datetime(2026, 9, 8, 2, 0, tzinfo=UTC))


class FakeProvider:
    def __init__(self, *, resolved_model: str = "gpt-6", usage: dict | None = None, fail: bool = False):
        self.resolved_model = resolved_model
        self.usage = usage or {"model_calls": 1, "cost_cny": 0.25}
        self.fail = fail
        self.calls = 0

    def __call__(self, request_bytes: bytes) -> dict:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return {
            "resolved_model": self.resolved_model,
            "response_bytes": b'{"ok": true}',
            "usage": self.usage,
        }


class BlockingProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, request_bytes: bytes) -> dict:
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        return {
            "resolved_model": "gpt-6",
            "response_bytes": b'{"ok": true}',
            "usage": {"model_calls": 1, "cost_cny": 0.25},
        }


def cutoff() -> datetime:
    return datetime(2026, 9, 8, 9, 0, tzinfo=SH)


def plan(*, total_model_calls: int = 2, total_cost_cny: float = 1.0, max_attempt_cost_cny: float = 0.5) -> dict:
    return {
        "problem": "same_model_raw_vs_desk",
        "date_window": {"start": "2026-09-08", "end": "2026-09-09"},
        "shared_input_hash": HASH_A,
        "risk_hash": HASH_B,
        "execution_hash": HASH_C,
        "budget_policy": "matched",
        "arms": [
            {
                "arm_id": "raw",
                "account_id": "acct-raw",
                "requested_model": "gpt-6",
                "budget": {
                    "total_model_calls": total_model_calls,
                    "total_cost_cny": total_cost_cny,
                    "max_attempt_cost_cny": max_attempt_cost_cny,
                },
            },
            {
                "arm_id": "desk",
                "account_id": "acct-desk",
                "requested_model": "gpt-6",
                "budget": {
                    "total_model_calls": total_model_calls,
                    "total_cost_cny": total_cost_cny,
                    "max_attempt_cost_cny": max_attempt_cost_cny,
                },
            },
        ],
    }


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_freeze_and_run_success_for_two_arms(tmp_path) -> None:
    frozen = freeze_plan(tmp_path, "exp-001", plan())

    raw = run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_payload={"symbol": "300308"},
        provider=FakeProvider(),
    )
    desk = run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="desk",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_bytes=b"desk request",
        provider=FakeProvider(),
    )

    assert frozen["status"] == "frozen"
    assert frozen["budget_policy"] == "matched"
    assert raw["status"] == "passed"
    assert desk["status"] == "passed"
    assert raw["model_receipt"]["requested_model"] == "gpt-6"
    assert raw["reservation"]["budget_reserved"] == {"model_calls": 1, "cost_cny": 0.5}
    assert (tmp_path / raw["reservation"]["path"]).is_file()
    assert raw["claims"]["complete_runner"] is False
    assert raw["claims"]["profitability_certified"] is False
    assert raw["claims"]["complete_research_protocol_certified"] is False


def test_existing_experiment_cannot_be_frozen_again(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())

    with pytest.raises(FileExistsError):
        freeze_plan(tmp_path, "exp-001", plan())


def test_freeze_hash_is_verified_before_run(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    freeze_path = tmp_path / "exp-001" / "freeze.json"
    frozen = load_json(freeze_path)
    frozen["plan"]["arms"][0]["requested_model"] = "gpt-5"
    freeze_path.write_text(json.dumps(frozen), encoding="utf-8")

    with pytest.raises(ValueError, match="freeze hash mismatch"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
        )


def test_caller_cannot_supply_frozen_at(tmp_path) -> None:
    bad = plan()
    bad["frozen_at"] = "2026-09-08T09:00:00+08:00"

    with pytest.raises(ValueError, match="frozen_at is machine generated"):
        freeze_plan(tmp_path, "exp-001", bad)


def test_unknown_plan_fields_are_rejected_instead_of_dropped(tmp_path) -> None:
    bad = plan()
    bad["prompt_version"] = "v1"

    with pytest.raises(ValueError, match="unknown plan fields"):
        freeze_plan(tmp_path, "exp-001", bad)


def test_cutoff_must_be_within_frozen_date_window(tmp_path) -> None:
    window_plan = plan()
    window_plan["date_window"] = {"start": "2026-09-07", "end": "2026-09-07"}
    freeze_plan(tmp_path, "exp-001", window_plan)

    with pytest.raises(ValueError, match="cutoff outside frozen date window"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260910",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
        )


def test_future_cutoff_is_rejected_before_provider_call(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    provider = FakeProvider()

    with pytest.raises(ValueError, match="cutoff cannot be in the future"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="future",
            cutoff=datetime.now(SH) + timedelta(days=1),
            request_bytes=b"request",
            provider=provider,
        )

    assert provider.calls == 0


def test_repeated_attempt_does_not_call_provider_again(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    provider = FakeProvider()
    kwargs = {
        "output_root": tmp_path,
        "experiment_id": "exp-001",
        "arm_id": "raw",
        "attempt_id": "20260908",
        "cutoff": cutoff(),
        "request_bytes": b"request",
        "provider": provider,
    }
    run_frozen_attempt(**kwargs)

    with pytest.raises(FileExistsError):
        run_frozen_attempt(**kwargs)

    assert provider.calls == 1


def test_budget_second_attempt_rejected_before_provider_call(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan(total_model_calls=1, total_cost_cny=0.5, max_attempt_cost_cny=0.5))
    first = FakeProvider()
    second = FakeProvider()
    run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_bytes=b"first",
        provider=first,
    )

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260909",
            cutoff=cutoff(),
            request_bytes=b"second",
            provider=second,
        )

    assert first.calls == 1
    assert second.calls == 0


def test_provider_exception_still_consumes_reserved_budget_after_restart(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan(total_model_calls=1, total_cost_cny=0.5, max_attempt_cost_cny=0.5))
    failed = run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_bytes=b"first",
        provider=FakeProvider(fail=True),
    )
    fresh_provider = FakeProvider()

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260909",
            cutoff=cutoff(),
            request_bytes=b"second",
            provider=fresh_provider,
        )

    assert failed["status"] == "failed"
    assert fresh_provider.calls == 0


def test_concurrent_workers_cannot_both_take_last_slot(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan(total_model_calls=1, total_cost_cny=0.5, max_attempt_cost_cny=0.5))
    blocker = BlockingProvider()
    loser = FakeProvider()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            run_frozen_attempt,
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"first",
            provider=blocker,
        )
        assert blocker.started.wait(2)
        second = pool.submit(
            run_frozen_attempt,
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260909",
            cutoff=cutoff(),
            request_bytes=b"second",
            provider=loser,
        )
        with pytest.raises(RuntimeError, match="budget exhausted"):
            second.result()
        blocker.release.set()
        assert first.result()["status"] == "passed"

    assert blocker.calls == 1
    assert loser.calls == 0


@pytest.mark.parametrize(
    "bad_plan",
    [
        {},
        {"problem": "same_model_raw_vs_desk"},
        plan(total_model_calls=0),
        plan(total_cost_cny=float("nan")),
        plan(max_attempt_cost_cny=2.0),
    ],
)
def test_bad_plan_and_budget_types_are_rejected(tmp_path, bad_plan) -> None:
    with pytest.raises(ValueError):
        freeze_plan(tmp_path, "exp-001", bad_plan)


def test_list_problem_or_budget_policy_raise_value_error(tmp_path) -> None:
    bad_problem = plan()
    bad_problem["problem"] = ["same_model_raw_vs_desk"]
    with pytest.raises(ValueError, match="plan problem invalid"):
        freeze_plan(tmp_path / "a", "exp-001", bad_problem)

    bad_policy = plan()
    bad_policy["budget_policy"] = ["matched"]
    with pytest.raises(ValueError, match="plan budget_policy invalid"):
        freeze_plan(tmp_path / "b", "exp-001", bad_policy)


@pytest.mark.parametrize("bad_id", ["../exp", "/abs", "nested/path", "", ".", "with space"])
def test_path_identifiers_cannot_escape(tmp_path, bad_id) -> None:
    with pytest.raises(ValueError, match="invalid path identifier"):
        freeze_plan(tmp_path, bad_id, plan())


def test_output_root_inside_repo_or_symlink_escape_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="output_root must be outside the repository"):
        freeze_plan(Path.cwd() / ".tmp-session-output", "exp-001", plan())

    real_repo_child = Path.cwd() / ".tmp-session-real"
    symlink = tmp_path / "repo-link"
    symlink.symlink_to(real_repo_child)
    with pytest.raises(ValueError, match="output_root must be outside the repository"):
        freeze_plan(symlink, "exp-001", plan())


def test_symlink_child_paths_are_rejected(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    symlink = tmp_path / "exp-001" / "raw"
    symlink.symlink_to(tmp_path / "exp-001" / "desk")

    with pytest.raises(RuntimeError, match="symlink paths are not supported"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
        )


def test_unknown_interrupted_reservation_counts_until_operator_resolution(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan(total_model_calls=1, total_cost_cny=0.5, max_attempt_cost_cny=0.5))
    reservations = tmp_path / "exp-001" / "budget" / "raw" / "manual-interrupt.reservation.json"
    reservations.parent.mkdir(parents=True)
    reservations.write_text(
        json.dumps(
            {
                "status": "reserved",
                "arm_id": "raw",
                "attempt_id": "manual-interrupt",
                "reserved": {"model_calls": 1, "cost_cny": 0.5},
            }
        ),
        encoding="utf-8",
    )
    provider = FakeProvider()

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=provider,
        )

    assert provider.calls == 0


def test_attempt_directory_without_reservation_blocks_future_calls(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    (tmp_path / "exp-001" / "raw" / "orphan").mkdir(parents=True)

    with pytest.raises(RuntimeError, match="attempt missing reservation"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
        )


def test_corrupted_reservation_fails_closed_instead_of_refunding(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan())
    reservation = tmp_path / "exp-001" / "budget" / "raw" / "bad.reservation.json"
    reservation.parent.mkdir(parents=True)
    reservation.write_text(json.dumps({"reserved": {"model_calls": 0, "cost_cny": 0}}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="reservation arm mismatch"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260908",
            cutoff=cutoff(),
            request_bytes=b"request",
            provider=FakeProvider(),
        )


def test_prior_receipt_over_budget_blocks_later_attempts(tmp_path) -> None:
    freeze_plan(tmp_path, "exp-001", plan(total_model_calls=2, total_cost_cny=2.0, max_attempt_cost_cny=1.0))
    first = run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_bytes=b"first",
        provider=FakeProvider(usage={"model_calls": 1, "cost_cny": 1.25}),
    )
    second = FakeProvider()

    with pytest.raises(RuntimeError, match="prior receipt usage exceeds budget"):
        run_frozen_attempt(
            output_root=tmp_path,
            experiment_id="exp-001",
            arm_id="raw",
            attempt_id="20260909",
            cutoff=cutoff(),
            request_bytes=b"second",
            provider=second,
        )

    assert first["status"] == "failed"
    assert second.calls == 0


def test_inspect_session_summarizes_freeze_reservations_and_receipts_without_ledger(tmp_path) -> None:
    frozen = freeze_plan(tmp_path, "exp-001", plan(total_model_calls=2, total_cost_cny=1.0, max_attempt_cost_cny=0.5))
    run_frozen_attempt(
        output_root=tmp_path,
        experiment_id="exp-001",
        arm_id="raw",
        attempt_id="20260908",
        cutoff=cutoff(),
        request_bytes=b"request",
        provider=FakeProvider(),
    )

    summary = inspect_session(tmp_path, "exp-001")

    assert summary["schema_version"] == "decision_desk_session_inspection.v1"
    assert summary["experiment_id"] == "exp-001"
    assert summary["freeze"]["plan_hash"] == frozen["plan_hash"]
    assert summary["freeze"]["machine_generated_frozen_at"] is True
    assert summary["freeze"]["plan_hash_is_trusted_timestamp"] is False
    assert summary["freeze"]["freeze_signature_verified"] is True
    assert summary["arms"]["raw"]["reserved_model_calls"] == 1
    assert summary["arms"]["raw"]["reserved_cost_cny"] == pytest.approx(0.5)
    assert summary["arms"]["raw"]["physical_attempt_root"] == "exp-001/raw/{attempt_id}"
    assert summary["arms"]["raw"]["receipts"]["passed"] == 1
    assert summary["claims"] == {
        "budget_and_input_plan_only": True,
        "complete_research_protocol_certified": False,
        "complete_runner": False,
        "trading_ledger": False,
        "os_isolation_proven": False,
        "profitability_certified": False,
    }
