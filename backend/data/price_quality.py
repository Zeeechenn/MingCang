"""Local price quality gates used by read-only data envelopes."""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Literal

from backend.data.database import Price

logger = logging.getLogger(__name__)

PriceQualityStatus = Literal["not_applicable", "unavailable", "passed", "warning", "blocked"]

# M42: threshold for the write-time hfq-detection guard.
# A row whose close > HFQ_JUMP_RATIO_THRESHOLD × median(preceding 10 closes) is
# treated as a contaminated hfq row and rejected before it is written to the DB.
# Validated on 8 years of A-share data: 0 false positives at K=3; minimum
# contamination ratio observed is 3.41×.  Do NOT lower below 3.0 without
# re-validating on the full universe.
#
# M58: the same threshold is reused symmetrically for the *down*-direction
# splice check (close < median / K) — see DOWN_SPLICE_WINDOW below for why
# the down-check uses a narrower preceding-closes window than the up-check.
HFQ_JUMP_RATIO_THRESHOLD: float = 3.0


@dataclass(frozen=True)
class PriceQualityPolicy:
    recent_window: int = 20
    stale_warning_days: int = 7
    extreme_price_range_ratio: float = 20.0
    cn_required_provenance: tuple[str, ...] = ("source", "fetched_at", "adjustment")
    # M42 write-time guard: multiplier applied to median of preceding closes.
    adjustment_jump_ratio: float = HFQ_JUMP_RATIO_THRESHOLD


@dataclass(frozen=True)
class PriceQualityGate:
    status: PriceQualityStatus
    blockers: list[str]
    warnings: list[str]
    recent_sources: list[str]
    recent_adjustments: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "recent_sources": self.recent_sources,
            "recent_adjustments": self.recent_adjustments,
        }


DEFAULT_PRICE_QUALITY_POLICY = PriceQualityPolicy()


#  M58: window used for the *down-splice* half of the guard.  This is
# intentionally smaller than the up-direction window (which uses all of
# ``preceding_closes``, up to 10 per caller convention) because the down and
# up directions are NOT symmetric once you account for real A-share limit
# moves compounding over several days:
#
#   up-direction (validated safe up to a 10-row window, see
#   HFQ_JUMP_RATIO_THRESHOLD comment above): a run of consecutive +20%
#   limit-up days compounds as 1.2**k, and 1.2**6 / 1.1 ≈ 2.71 stays under the
#   3x threshold even at a 10-row window.
#
#   down-direction: a run of consecutive -20% limit-down days compounds as
#   0.8**k, which shrinks much faster in ratio terms.  Worked example (see
#   tests): comparing the incoming close against the median of a *window of
#   w* preceding closes drawn from a pure 0.8x/day decline gives
#   ratio = 0.8**((w+1)//2) for odd w.  That ratio is:
#     w=5  -> 0.8**3  = 0.512   (safely above 1/3 = 0.333)
#     w=8  -> 0.8**4/0.9 ≈ 0.364 (still above 1/3, thin margin)
#     w=9  -> 0.8**5  = 0.328   (BELOW 1/3 -> would misfire on a real,
#                                 if rare, 20%-board delisting-risk crash)
#     w=10 -> ratio ≈ 0.291     (BELOW 1/3 -> would misfire)
#   So a 9-10 row window is NOT safe for the down-check at threshold=3.  A
#   5-row window keeps a comfortable margin (0.512 vs 0.333) and — because the
#   ratio at steady-state decline does not degrade further as the window
#   slides forward (it only depends on the window length, not on how many
#   total days the decline has run) — stays safe no matter how long a real
#   consecutive limit-down streak lasts.  Do not widen this without
#   re-deriving the bound above.
DOWN_SPLICE_WINDOW: int = 5


def check_adjustment_basis_jump(
    incoming_close: float,
    preceding_closes: Sequence[float],
    *,
    threshold: float = HFQ_JUMP_RATIO_THRESHOLD,
) -> bool:
    """Return True when *incoming_close* looks like an adjustment-basis splice.

    A row is flagged when at least 5 usable preceding closes are available
    (otherwise no meaningful baseline exists — pass through and let the
    read-time gate handle it later), AND either:

      - UP direction (M42): incoming_close > threshold × median(preceding
        closes), using the full window the caller supplies (up to 10); or
      - DOWN direction (M58): incoming_close < median(preceding closes) /
        threshold, using only the most recent ``DOWN_SPLICE_WINDOW`` (5)
        preceding closes — see the module-level comment on
        ``DOWN_SPLICE_WINDOW`` for why the down-check uses a narrower window
        than the up-check.

    This is a WRITE-TIME, point-in-time check operating on the incoming row
    before it is committed.  It does NOT require next-day data, so it is safe
    to call inside the records-building loop in ``backfill_if_needed``.

    Args:
        incoming_close: The ``close`` value of the candidate Price row.
        preceding_closes: The closes of the symbol's *existing* rows that
            immediately precede the candidate date, oldest→newest (caller
            supplies up to 10).
        threshold: Override the default ratio (useful for tests).

    Returns:
        True  → row is flagged as a probable adjustment-basis contaminant
                (either an hfq-scale up-splice or a down-splice); caller
                should skip/reject it.
        False → row passes the guard.
    """
    usable = [c for c in preceding_closes if c and c > 0]
    if len(usable) < 5:
        # Insufficient history — cannot distinguish genuine first-data from
        # a contaminated splice.
        return False

    med = median(usable)
    if med <= 0:
        return False
    if incoming_close > threshold * med:
        return True

    # M58: symmetric down-splice check, using only the closest DOWN_SPLICE_WINDOW
    # preceding closes (see module comment for the safety derivation).
    down_usable = usable[-DOWN_SPLICE_WINDOW:]
    down_med = median(down_usable)
    if down_med <= 0:
        return False
    return incoming_close < down_med / threshold


def not_applicable_price_quality_gate() -> PriceQualityGate:
    return PriceQualityGate(
        status="not_applicable",
        blockers=[],
        warnings=[],
        recent_sources=[],
        recent_adjustments=[],
    )


def evaluate_price_quality(
    *,
    market: str,
    row: Mapping[str, Any] | None,
    recent_rows: Sequence[Price],
    policy: PriceQualityPolicy = DEFAULT_PRICE_QUALITY_POLICY,
) -> PriceQualityGate:
    """Return local DB price quality warnings without fetching remote providers."""
    blockers: list[str] = []
    warnings: list[str] = []

    if row is None:
        return PriceQualityGate(
            status="unavailable",
            blockers=["no_local_price_row"],
            warnings=[],
            recent_sources=[],
            recent_adjustments=[],
        )

    for field in ("open", "high", "low", "close", "volume"):
        value = row.get(field)
        if value is None:
            blockers.append(f"missing_{field}")
            continue
        if field != "volume" and float(value) <= 0:
            blockers.append(f"non_positive_{field}")

    high = row.get("high")
    low = row.get("low")
    open_ = row.get("open")
    close = row.get("close")
    if high is not None and low is not None and float(high) < float(low):
        blockers.append("high_below_low")
    if high is not None and low is not None:
        for field_name, value in (("open", open_), ("close", close)):
            if value is not None and not (float(low) <= float(value) <= float(high)):
                blockers.append(f"{field_name}_outside_daily_range")

    if market.upper() == "CN":
        for field in policy.cn_required_provenance:
            if not row.get(field):
                blockers.append(f"missing_provenance_{field}")

    try:
        latest_date = date.fromisoformat(str(row.get("date")))
        days_old = (date.today() - latest_date).days
        if days_old > policy.stale_warning_days:
            warnings.append(f"stale_latest_bar_{days_old}d")
    except (TypeError, ValueError):
        blockers.append("invalid_price_date")

    sources = sorted({str(item.source) for item in recent_rows if item.source})
    adjustments = sorted({str(item.adjustment) for item in recent_rows if item.adjustment})
    if len(adjustments) > 1:
        blockers.append("mixed_recent_adjustments")
    if len(sources) > 1:
        warnings.append("mixed_recent_sources")

    closes = [float(item.close) for item in recent_rows if item.close and float(item.close) > 0]
    if closes:
        min_close = min(closes)
        max_close = max(closes)
        if min_close > 0 and max_close / min_close > policy.extreme_price_range_ratio:
            blockers.append("extreme_recent_price_range")

    status: PriceQualityStatus = "passed" if not blockers and not warnings else "warning"
    if blockers:
        status = "blocked"
    return PriceQualityGate(
        status=status,
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
        recent_sources=sources,
        recent_adjustments=adjustments,
    )
