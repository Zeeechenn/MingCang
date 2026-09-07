"""Pure decision-draft builder for separating user intent from real holdings."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
VALID_ACTIONS = frozenset({"buy", "watch", "hold", "add", "trim", "exit"})


def build_decision_draft(
    symbol: str,
    *,
    as_of: datetime,
    account_id: str,
    account_snapshot: dict[str, Any],
    proposal: dict[str, Any],
    risk_limits: dict[str, Any],
    human_constraint: dict[str, Any] | None = None,
    historical_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-persistent draft from explicit account, proposal, and risk inputs."""
    blockers: list[str] = []
    normalized_symbol = str(symbol or "").strip()
    normalized_account = str(account_id or "").strip()
    result: dict[str, Any] = {
        "schema_version": "decision_draft.v1",
        "symbol": normalized_symbol,
        "account_id": normalized_account,
        "as_of": _iso_or_none(as_of),
        "proposal": dict(proposal) if isinstance(proposal, dict) else proposal,
        "historical_reference": None,
        "current_position_pct": None,
        "position_state": "unknown",
        "draft_action": None,
        "target_pct": None,
        "human_constraint_status": "not_provided" if human_constraint is None else "invalid",
        "review_status": "pending",
        "can_execute": False,
        "blockers": blockers,
    }

    if not _is_aware(as_of):
        blockers.append("as_of_timezone_aware_required")
        return result
    if not normalized_symbol:
        blockers.append("symbol_required")
    if not normalized_account:
        blockers.append("account_id_required")
    if blockers:
        return result

    _attach_historical_reference(result, blockers, historical_target, as_of)

    action = proposal.get("action") if isinstance(proposal, dict) else None
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        blockers.append("proposal_action_invalid")
        return result
    result["draft_action"] = action
    proposal_target = _valid_pct(proposal.get("target_pct")) if isinstance(proposal, dict) else None

    current_pct = _validate_account_snapshot(
        result,
        blockers,
        symbol=normalized_symbol,
        account_id=normalized_account,
        account_snapshot=account_snapshot,
        as_of=as_of,
    )
    if current_pct is None:
        blockers.append("position_unknown")
        return result

    result["current_position_pct"] = current_pct
    result["position_state"] = "flat" if current_pct == 0 else "held"

    max_position_pct = _valid_pct(risk_limits.get("max_position_pct")) if isinstance(risk_limits, dict) else None
    max_new_position_pct = (
        _valid_pct(risk_limits.get("max_new_position_pct")) if isinstance(risk_limits, dict) else None
    )
    if max_position_pct is None or max_new_position_pct is None:
        blockers.append("risk_limits_invalid")
        return result
    if max_new_position_pct > max_position_pct:
        blockers.append("risk_limits_inconsistent")
        return result

    target_pct = _derive_target_pct(
        action=action,
        current_pct=current_pct,
        proposal_target=proposal_target,
        max_position_pct=max_position_pct,
        max_new_position_pct=max_new_position_pct,
        blockers=blockers,
    )
    if "draft_action_normalized_to_hold" in blockers:
        result["draft_action"] = "hold"

    constraint_status = _human_constraint_status(
        human_constraint,
        symbol=normalized_symbol,
        account_id=normalized_account,
        as_of=as_of,
    )
    result["human_constraint_status"] = constraint_status
    if constraint_status == "invalid":
        blockers.append("human_constraint_invalid")
        target_pct = current_pct
        result["draft_action"] = "hold" if current_pct > 0 else "watch"
    elif constraint_status == "active" and target_pct is not None and target_pct > current_pct:
        blockers.append("human_constraint_no_new_buy")
        target_pct = current_pct
        result["draft_action"] = "hold" if current_pct > 0 else "watch"

    result["target_pct"] = target_pct
    return result


def _validate_account_snapshot(
    result: dict[str, Any],
    blockers: list[str],
    *,
    symbol: str,
    account_id: str,
    account_snapshot: dict[str, Any],
    as_of: datetime,
) -> float | None:
    if not isinstance(account_snapshot, dict):
        blockers.append("account_snapshot_required")
        return None
    if account_snapshot.get("symbol") != symbol:
        blockers.append("account_snapshot_symbol_mismatch")
        return None
    if account_snapshot.get("account_id") != account_id:
        blockers.append("account_snapshot_account_mismatch")
        return None
    source = account_snapshot.get("source")
    if not isinstance(source, str) or not source.strip():
        blockers.append("account_snapshot_source_required")
        return None
    observed_at = _parse_aware_datetime(account_snapshot.get("observed_at"))
    if observed_at is None:
        blockers.append("account_snapshot_observed_at_timezone_aware_required")
        return None
    if observed_at > as_of:
        blockers.append("account_snapshot_after_as_of")
        return None
    if observed_at.astimezone(SHANGHAI_TZ).date() != as_of.astimezone(SHANGHAI_TZ).date():
        blockers.append("account_snapshot_not_same_trading_day")
        return None
    current_pct = _valid_pct(account_snapshot.get("position_pct"))
    if current_pct is None:
        blockers.append("account_snapshot_position_pct_invalid")
        return None
    result["account_snapshot_source"] = account_snapshot["source"]
    result["account_snapshot_observed_at"] = observed_at.isoformat()
    return current_pct


def _derive_target_pct(
    *,
    action: str,
    current_pct: float,
    proposal_target: float | None,
    max_position_pct: float,
    max_new_position_pct: float,
    blockers: list[str],
) -> float | None:
    if action in {"watch", "hold"}:
        blockers.append("maintain_current_position")
        return current_pct
    if action == "exit":
        return 0.0
    if proposal_target is None:
        blockers.append("proposal_target_pct_invalid")
        return None
    if action in {"buy", "add"}:
        capped = min(proposal_target, max_position_pct)
        if current_pct == 0:
            capped = min(capped, max_new_position_pct)
        return max(current_pct, capped)
    if action == "trim":
        if proposal_target > current_pct:
            blockers.append("trim_cannot_increase_position")
            blockers.append("draft_action_normalized_to_hold")
            return current_pct
        return proposal_target
    return None


def _attach_historical_reference(
    result: dict[str, Any],
    blockers: list[str],
    historical_target: dict[str, Any] | None,
    as_of: datetime,
) -> None:
    if historical_target is None:
        return
    if not isinstance(historical_target, dict):
        blockers.append("historical_target_invalid")
        return
    date = historical_target.get("date")
    target_pct = _valid_pct(historical_target.get("target_pct"))
    if not isinstance(date, str) or target_pct is None:
        blockers.append("historical_target_invalid")
        return
    if _is_date_only(date):
        try:
            historical_date = datetime.fromisoformat(date).date()
        except ValueError:
            blockers.append("historical_target_invalid")
            return
        as_of_date = as_of.astimezone(SHANGHAI_TZ).date()
        if historical_date > as_of_date:
            blockers.append("historical_target_after_as_of")
            return
        if historical_date == as_of_date:
            blockers.append("historical_target_same_day_date_only_rejected")
            return
    else:
        historical_at = _parse_aware_datetime(date)
        if historical_at is None:
            blockers.append("historical_target_invalid")
            return
        if historical_at > as_of:
            blockers.append("historical_target_after_as_of")
            return
    result["historical_reference"] = {"date": date, "target_pct": target_pct}


def _human_constraint_status(
    human_constraint: dict[str, Any] | None,
    *,
    symbol: str,
    account_id: str,
    as_of: datetime,
) -> str:
    if human_constraint is None:
        return "not_provided"
    if not isinstance(human_constraint, dict):
        return "invalid"
    if human_constraint.get("symbol") != symbol or human_constraint.get("account_id") != account_id:
        return "not_applicable"
    if human_constraint.get("no_new_buy") is not True:
        return "invalid"
    valid_from = _parse_aware_datetime(human_constraint.get("valid_from"))
    valid_until = _parse_aware_datetime(human_constraint.get("valid_until"))
    if valid_from is None or valid_until is None or valid_until < valid_from:
        return "invalid"
    if valid_from <= as_of <= valid_until:
        return "active"
    return "not_applicable"


def _valid_pct(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or parsed > 1:
        return None
    return parsed


def _parse_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if not _is_aware(parsed):
        return None
    return parsed


def _is_date_only(value: str) -> bool:
    return len(value) == 10 and value[4] == "-" and value[7] == "-"


def _is_aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
