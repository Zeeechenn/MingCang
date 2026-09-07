from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.research.decision_draft import build_decision_draft

SH = ZoneInfo("Asia/Shanghai")


def aware(hour: int = 15, minute: int = 0) -> datetime:
    return datetime(2026, 9, 8, hour, minute, tzinfo=SH)


def account(position_pct, *, symbol="300308", account_id="paper-a", observed_at=None, source="broker_snapshot"):
    observed = observed_at or aware(14, 55)
    return {
        "symbol": symbol,
        "account_id": account_id,
        "source": source,
        "observed_at": observed.isoformat() if isinstance(observed, datetime) else observed,
        "position_pct": position_pct,
    }


def risk(max_position_pct=0.15, max_new_position_pct=0.05):
    return {
        "max_position_pct": max_position_pct,
        "max_new_position_pct": max_new_position_pct,
    }


def proposal(action="buy", target_pct=0.12):
    return {"action": action, "target_pct": target_pct, "reason": "user selected"}


def test_unknown_position_preserves_proposal_but_does_not_create_trial_target() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot={"status": "unknown", "source": "broker_snapshot"},
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        historical_target={"date": "2026-09-07", "target_pct": 0.12},
    )

    assert draft["position_state"] == "unknown"
    assert draft["proposal"]["target_pct"] == pytest.approx(0.12)
    assert draft["target_pct"] is None
    assert draft["can_execute"] is False
    assert draft["review_status"] == "pending"
    assert draft["historical_reference"]["target_pct"] == pytest.approx(0.12)


def test_flat_buy_uses_explicit_new_position_limit() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(max_position_pct=0.15, max_new_position_pct=0.05),
    )

    assert draft["position_state"] == "flat"
    assert draft["current_position_pct"] == pytest.approx(0.0)
    assert draft["target_pct"] == pytest.approx(0.05)
    assert draft["draft_action"] == "buy"
    assert draft["can_execute"] is False


def test_held_add_caps_target_by_max_position() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.12),
        proposal=proposal("add", 0.2),
        risk_limits=risk(max_position_pct=0.15, max_new_position_pct=0.05),
    )

    assert draft["position_state"] == "held"
    assert draft["current_position_pct"] == pytest.approx(0.12)
    assert draft["target_pct"] == pytest.approx(0.15)
    assert draft["draft_action"] == "add"


def test_watch_and_hold_maintain_real_current_position() -> None:
    for action in ("watch", "hold"):
        draft = build_decision_draft(
            "300308",
            as_of=aware(),
            account_id="paper-a",
            account_snapshot=account(0.12),
            proposal=proposal(action, 0.2),
            risk_limits=risk(),
        )
        assert draft["target_pct"] == pytest.approx(0.12)
        assert draft["draft_action"] == action
        assert "maintain_current_position" in draft["blockers"]


def test_trim_cannot_become_add() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.12),
        proposal=proposal("trim", 0.2),
        risk_limits=risk(),
    )

    assert draft["target_pct"] == pytest.approx(0.12)
    assert draft["draft_action"] == "hold"
    assert "trim_cannot_increase_position" in draft["blockers"]


def test_exit_can_suggest_zero_for_known_position_but_not_execute() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.12),
        proposal=proposal("exit", 0),
        risk_limits=risk(),
    )

    assert draft["target_pct"] == pytest.approx(0.0)
    assert draft["draft_action"] == "exit"
    assert draft["can_execute"] is False
    assert draft["review_status"] == "pending"


def test_exit_unknown_position_stays_unknown_without_execution_target() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot={"status": "unknown", "source": "broker_snapshot"},
        proposal=proposal("exit", 0),
        risk_limits=risk(),
    )

    assert draft["position_state"] == "unknown"
    assert draft["target_pct"] is None
    assert "position_unknown" in draft["blockers"]


def test_human_no_buy_constraint_blocks_increase_but_does_not_clear_existing_position() -> None:
    constraint = {
        "symbol": "300308",
        "account_id": "paper-a",
        "no_new_buy": True,
        "valid_from": "2026-09-08T09:00:00+08:00",
        "valid_until": "2026-09-08T23:59:00+08:00",
    }

    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.12),
        proposal=proposal("add", 0.15),
        risk_limits=risk(),
        human_constraint=constraint,
    )

    assert draft["target_pct"] == pytest.approx(0.12)
    assert draft["draft_action"] == "hold"
    assert draft["proposal"]["action"] == "add"
    assert draft["human_constraint_status"] == "active"
    assert "human_constraint_no_new_buy" in draft["blockers"]


def test_human_constraint_does_not_expand_when_symbol_or_account_mismatch() -> None:
    constraint = {
        "symbol": "600519",
        "account_id": "paper-a",
        "no_new_buy": True,
        "valid_from": "2026-09-08T09:00:00+08:00",
        "valid_until": "2026-09-08T23:59:00+08:00",
    }

    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        human_constraint=constraint,
    )

    assert draft["human_constraint_status"] == "not_applicable"
    assert draft["target_pct"] == pytest.approx(0.05)


def test_invalid_human_constraint_fails_closed() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        human_constraint={"symbol": "300308", "account_id": "paper-a", "no_new_buy": True},
    )

    assert draft["target_pct"] == pytest.approx(0.0)
    assert draft["human_constraint_status"] == "invalid"
    assert "human_constraint_invalid" in draft["blockers"]


@pytest.mark.parametrize(
    ("snapshot", "blocker"),
    [
        (account(0.0, observed_at=datetime(2026, 9, 7, 15, tzinfo=SH).isoformat()), "account_snapshot_not_same_trading_day"),
        (account(0.0, observed_at=aware(16).isoformat()), "account_snapshot_after_as_of"),
        (account(0.0, account_id="wrong"), "account_snapshot_account_mismatch"),
        (account(float("nan")), "account_snapshot_position_pct_invalid"),
        (account(0.0, source=""), "account_snapshot_source_required"),
    ],
)
def test_bad_account_snapshot_blocks_target(snapshot, blocker) -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=snapshot,
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
    )

    assert draft["position_state"] == "unknown"
    assert draft["target_pct"] is None
    assert blocker in draft["blockers"]


@pytest.mark.parametrize(
    ("symbol", "account_id", "snapshot", "blocker"),
    [
        ("", "paper-a", account(0.0), "symbol_required"),
        ("300308", "", account(0.0), "account_id_required"),
        ("300308", "paper-a", {"account_id": "paper-a", "source": "broker_snapshot", "observed_at": aware().isoformat(), "position_pct": 0.0}, "account_snapshot_symbol_mismatch"),
        ("300308", "paper-a", {"symbol": "300308", "source": "broker_snapshot", "observed_at": aware().isoformat(), "position_pct": 0.0}, "account_snapshot_account_mismatch"),
        ("300308", "paper-a", account(0.0, source={"kind": "broker"}), "account_snapshot_source_required"),
    ],
)
def test_root_and_snapshot_identity_fields_must_be_explicit_strings(symbol, account_id, snapshot, blocker) -> None:
    draft = build_decision_draft(
        symbol,
        as_of=aware(),
        account_id=account_id,
        account_snapshot=snapshot,
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
    )

    assert draft["target_pct"] is None
    assert blocker in draft["blockers"]


def test_non_string_action_is_blocked_without_target() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal(["buy"], 0.12),
        risk_limits=risk(),
    )

    assert draft["draft_action"] is None
    assert draft["target_pct"] is None
    assert "proposal_action_invalid" in draft["blockers"]


def test_historical_target_after_asof_is_rejected_as_reference() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        historical_target={"date": "2026-09-09", "target_pct": 0.12},
    )

    assert draft["historical_reference"] is None
    assert "historical_target_after_as_of" in draft["blockers"]
    assert draft["target_pct"] == pytest.approx(0.05)


def test_historical_target_same_day_date_only_is_rejected_as_unknown_time() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        historical_target={"date": "2026-09-08", "target_pct": 0.12},
    )

    assert draft["historical_reference"] is None
    assert "historical_target_same_day_date_only_rejected" in draft["blockers"]


def test_historical_target_aware_same_day_before_asof_preserves_time_precision() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(15),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
        historical_target={"date": "2026-09-08T14:00:00+08:00", "target_pct": 0.12},
    )

    assert draft["historical_reference"] == {"date": "2026-09-08T14:00:00+08:00", "target_pct": 0.12}


def test_risk_limit_invalid_keeps_known_position_but_no_target() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.12),
        proposal=proposal("add", 0.15),
        risk_limits=risk(max_position_pct=float("nan")),
    )

    assert draft["position_state"] == "held"
    assert draft["current_position_pct"] == pytest.approx(0.12)
    assert draft["target_pct"] is None
    assert "risk_limits_invalid" in draft["blockers"]


def test_max_new_position_above_max_position_is_inconsistent_and_blocks_target() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=aware(),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(max_position_pct=0.05, max_new_position_pct=0.08),
    )

    assert draft["position_state"] == "flat"
    assert draft["target_pct"] is None
    assert "risk_limits_inconsistent" in draft["blockers"]


def test_asof_must_be_timezone_aware() -> None:
    draft = build_decision_draft(
        "300308",
        as_of=datetime(2026, 9, 8, 15),
        account_id="paper-a",
        account_snapshot=account(0.0),
        proposal=proposal("buy", 0.12),
        risk_limits=risk(),
    )

    assert draft["target_pct"] is None
    assert "as_of_timezone_aware_required" in draft["blockers"]
