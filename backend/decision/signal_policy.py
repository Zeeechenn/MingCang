"""统一信号语义：观察动作与资金动作分离。"""
from __future__ import annotations

from datetime import date

from backend.config import active_signal_weights

ENTRY_RECS = {"可小仓试错"}
LEGACY_ENTRY_RECS = {"买入", "强买"}
WATCH_RECS = {"可关注"}
EXIT_RECS = {"规避", "卖出", "强卖"}


def score_to_recommendation(score: float, as_of: date | None = None) -> str:
    """Map a composite score to a recommendation string based on current thresholds."""
    entry_threshold = active_signal_weights(as_of).entry_threshold
    if score > entry_threshold:
        return "可小仓试错"
    if score > 0:
        return "可关注"
    if score > -20:
        return "观望"
    return "规避"


def is_watch_signal(recommendation: str | None) -> bool:
    """Return True if the recommendation is a watch (observe) signal."""
    return recommendation in WATCH_RECS


def is_entry_signal(recommendation: str | None, *, include_legacy: bool = True) -> bool:
    """Return True if the recommendation is an actionable entry signal."""
    entry = set(ENTRY_RECS)
    if include_legacy:
        entry |= LEGACY_ENTRY_RECS
    return recommendation in entry


def entry_recommendations(*, include_legacy: bool = True) -> list[str]:
    """Return sorted list of all entry recommendation strings."""
    values = set(ENTRY_RECS)
    if include_legacy:
        values |= LEGACY_ENTRY_RECS
    return sorted(values)


def should_send_signal_alert(recommendation: str | None) -> bool:
    """Return True if the recommendation should trigger a push notification."""
    return is_entry_signal(recommendation, include_legacy=True) or is_watch_signal(recommendation)
