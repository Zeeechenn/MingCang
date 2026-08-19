"""Deterministic notification dedupe/suppression contract.

Default mode is shadow/log-only: callers can see what would have been
suppressed without changing existing Bark send behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

EnforcementMode = Literal["shadow", "enforce"]

NOTIFICATION_GOVERNANCE = {
    "owner_domain": "backend.notification",
    "unique_consumer": "Bark/stock-monitor notification routing",
    "input_contract": "notification event plus recent delivery history",
    "output_contract": "notification_delivery_contract.v1",
    "failure_mode": "events lacking dedupe_key are degraded but not silently dropped",
    "degradation": "shadow mode preserves send behavior while returning reasons",
    "baseline": "existing Bark send_result/send behavior",
    "success_metric": "100% of evaluated notifications return suppression reasons and rate-limit state",
    "minimum_sample": "30 evaluated notifications across at least 5 symbols",
    "expiry_or_exit": "expires when router-level notification ledger is canonical",
    "rollback": "do not call evaluate_notification_contract; Bark behavior is unchanged",
    "replacement": "persistent notification ledger with deterministic replay",
    "lifecycle": "shadow",
    "signal_impact": "none",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _key(event: dict[str, Any]) -> str:
    return str(
        event.get("dedupe_key")
        or "|".join(
            str(event.get(part, ""))
            for part in ("channel", "symbol", "event_type", "title")
        )
    )


def evaluate_notification_contract(
    event: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    dedupe_window_minutes: int = 240,
    rate_limit_window_minutes: int = 60,
    max_per_window: int = 3,
    enforcement_mode: EnforcementMode = "shadow",
) -> dict:
    """Return deterministic delivery decision, reasons, and rate-limit state."""

    current = now or _now()
    dedupe_key = _key(event)
    channel = str(event.get("channel") or event.get("group") or "default")
    symbol = str(event.get("symbol") or "")
    rows = history or []

    duplicate_rows = []
    rate_rows = []
    for row in rows:
        sent_at = _parse_dt(row.get("sent_at") or row.get("created_at") or row.get("timestamp"))
        if sent_at is None:
            continue
        age = current - sent_at
        row_key = _key(row)
        same_channel = str(row.get("channel") or row.get("group") or "default") == channel
        same_symbol = str(row.get("symbol") or "") == symbol
        if row_key == dedupe_key and age <= timedelta(minutes=dedupe_window_minutes):
            duplicate_rows.append(row)
        if same_channel and same_symbol and age <= timedelta(minutes=rate_limit_window_minutes):
            rate_rows.append(row)

    suppression_reasons: list[str] = []
    if not event.get("dedupe_key"):
        suppression_reasons.append("dedupe_key_missing")
    if duplicate_rows:
        suppression_reasons.append("duplicate_in_window")
    rate_limited = len(rate_rows) >= max_per_window
    if rate_limited:
        suppression_reasons.append("rate_limit_exceeded")

    would_suppress = any(reason != "dedupe_key_missing" for reason in suppression_reasons)
    should_send = not would_suppress if enforcement_mode == "enforce" else True

    return {
        "schema_version": "notification_delivery_contract.v1",
        "enforcement_mode": enforcement_mode,
        "should_send": should_send,
        "would_suppress": would_suppress,
        "suppression_reasons": suppression_reasons,
        "silently_dropped": False,
        "dedupe": {
            "key": dedupe_key,
            "window_minutes": dedupe_window_minutes,
            "duplicate_count": len(duplicate_rows),
        },
        "rate_limit": {
            "channel": channel,
            "symbol": symbol,
            "window_minutes": rate_limit_window_minutes,
            "max_per_window": max_per_window,
            "count_in_window": len(rate_rows),
            "remaining": max(0, max_per_window - len(rate_rows)),
            "limited": rate_limited,
        },
        "read_only": True,
        "write_policy": "no_database_writes",
        "signal_impact": "none",
        "governance": dict(NOTIFICATION_GOVERNANCE),
    }
