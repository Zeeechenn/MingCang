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


# M69: tolerance for the stored-vs-fetched overlap comparison below.  Same
# provider + same date should reproduce the same close bit-for-bit modulo float
# rounding, so anything above 0.2% is a basis change, not noise.  A typical
# A-share cash dividend re-bases the series by 1-5% (600900 on 2026-07-15:
# 0.79 on ~28.5 = 2.8%), which sits far under the 3x ratio guard above and is
# why that guard never fired on it.
BASIS_DRIFT_REL_TOLERANCE: float = 0.002
# Below this many overlapping rows the comparison is not conclusive.
BASIS_DRIFT_MIN_COMPARED: int = 3
# Spread of the per-row signed deltas (or ratios), relative to their median,
# under which we call the drift uniform — i.e. a whole-series re-basing rather
# than a handful of individually corrected bars.
BASIS_DRIFT_UNIFORMITY: float = 0.05


@dataclass(frozen=True)
class AdjustmentBasisDrift:
    """Result of comparing stored closes against a freshly fetched series.

    ``detected`` means: for dates present in BOTH the DB and the newly fetched
    frame, the provider now reports different closes than what we stored.  The
    stored history is therefore on a stale adjustment basis and must not be
    compared against newly written bars (P&L, stop/target levels and ATR all
    silently break across the seam).
    """

    detected: bool
    compared_rows: int
    divergent_rows: int
    kind: Literal["none", "additive", "multiplicative", "mixed"]
    median_delta: float
    median_ratio: float
    max_abs_delta: float
    earliest_divergent_date: str | None
    latest_divergent_date: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "compared_rows": self.compared_rows,
            "divergent_rows": self.divergent_rows,
            "kind": self.kind,
            "median_delta": round(self.median_delta, 6),
            "median_ratio": round(self.median_ratio, 6),
            "max_abs_delta": round(self.max_abs_delta, 6),
            "earliest_divergent_date": self.earliest_divergent_date,
            "latest_divergent_date": self.latest_divergent_date,
        }

    def describe(self) -> str:
        if not self.detected:
            return "no adjustment-basis drift"
        if self.kind == "additive":
            shape = f"uniform additive offset ≈ {self.median_delta:+.4f} (cash dividend re-basing)"
        elif self.kind == "multiplicative":
            shape = f"uniform ratio ≈ {self.median_ratio:.6f} (split/scale re-basing)"
        else:
            shape = "non-uniform (individual bars corrected, not a whole-series re-basing)"
        return (
            f"{self.divergent_rows}/{self.compared_rows} overlapping rows disagree, {shape}; "
            f"affected stored range {self.earliest_divergent_date}..{self.latest_divergent_date}"
        )


def _spread_ratio(values: Sequence[float]) -> float:
    """Max deviation from the median, relative to |median|. 0 = perfectly uniform."""
    if not values:
        return float("inf")
    med = median(values)
    if abs(med) < 1e-12:
        return float("inf")
    return max(abs(v - med) for v in values) / abs(med)


def detect_adjustment_basis_drift(
    fetched_closes: Mapping[str, float],
    stored_closes: Mapping[str, float],
    *,
    rel_tolerance: float = BASIS_DRIFT_REL_TOLERANCE,
    min_compared: int = BASIS_DRIFT_MIN_COMPARED,
) -> AdjustmentBasisDrift:
    """Compare same-date closes from a fresh fetch against what the DB holds.

    This is complementary to :func:`check_adjustment_basis_jump`, which is a
    row-local ratio guard tuned for 3x hfq-scale splices.  That guard is blind
    to small re-basings: a cash dividend shifts the whole pre-ex history by a
    couple of percent, every individual step stays smooth, and nothing trips.
    The seam only becomes visible when you notice the provider now reports a
    *different* value for a date you already stored — which is exactly what
    this function checks.

    Only dates present in both mappings are considered, so a normal incremental
    backfill (all-new dates, no overlap) yields ``detected=False`` with
    ``compared_rows=0``.

    Args:
        fetched_closes: date (ISO ``YYYY-MM-DD``) → close, straight from the provider.
        stored_closes: date → close, as currently persisted.
        rel_tolerance: per-row relative difference above which a row counts as divergent.
        min_compared: minimum overlapping rows required to reach a verdict.

    Returns:
        An :class:`AdjustmentBasisDrift`.  ``detected`` is True only when the
        overlap is large enough AND at least one row disagrees beyond tolerance.
    """
    common = sorted(set(fetched_closes) & set(stored_closes))
    deltas: list[float] = []
    ratios: list[float] = []
    divergent_dates: list[str] = []

    for day in common:
        stored = float(stored_closes[day])
        fresh = float(fetched_closes[day])
        if stored <= 0:
            continue
        if abs(fresh - stored) / stored > rel_tolerance:
            divergent_dates.append(day)
            deltas.append(fresh - stored)
            ratios.append(fresh / stored)

    compared = len(common)
    if compared < min_compared or not divergent_dates:
        return AdjustmentBasisDrift(
            detected=False,
            compared_rows=compared,
            divergent_rows=len(divergent_dates),
            kind="none",
            median_delta=0.0,
            median_ratio=1.0,
            max_abs_delta=0.0,
            earliest_divergent_date=None,
            latest_divergent_date=None,
        )

    # With a single divergent row "uniform" is vacuously true, which would let
    # one individually corrected bar be described as a whole-series re-basing.
    # Require at least two rows before claiming a shape.
    if len(deltas) < 2:
        additive_uniform = multiplicative_uniform = False
    else:
        additive_uniform = _spread_ratio(deltas) <= BASIS_DRIFT_UNIFORMITY
        multiplicative_uniform = _spread_ratio(ratios) <= BASIS_DRIFT_UNIFORMITY
    if additive_uniform and not multiplicative_uniform:
        kind: Literal["additive", "multiplicative", "mixed"] = "additive"
    elif multiplicative_uniform and not additive_uniform:
        kind = "multiplicative"
    elif additive_uniform and multiplicative_uniform:
        # Over a short window a small offset also looks like a near-constant
        # ratio; the offset is the more actionable description for A-share
        # cash dividends, so prefer it.
        kind = "additive"
    else:
        kind = "mixed"

    return AdjustmentBasisDrift(
        detected=True,
        compared_rows=compared,
        divergent_rows=len(divergent_dates),
        kind=kind,
        median_delta=median(deltas),
        median_ratio=median(ratios),
        max_abs_delta=max(abs(d) for d in deltas),
        earliest_divergent_date=divergent_dates[0],
        latest_divergent_date=divergent_dates[-1],
    )


# M69 follow-up (2026-09-02 audit): a drift event on its own cannot tell you
# whether the provider re-based the series or whether a *different* provider
# answered this time, on its own basis.  The 47 events recorded up to that
# audit split across four providers (akshare_sina_cn 23 / tickflow_cn 21 /
# ifind_cn 2 / eastmoney_cn 1), so the "true re-basing" share was unknowable
# after the fact.  Recording the stored rows' provider makes the two cases
# separable at write time, which is what the follow-up blocker keys off.
UNKNOWN_PRICE_SOURCE = "unknown"


def classify_drift_source(
    fetch_source: str | None,
    stored_sources: Sequence[str] | None,
) -> bool | None:
    """Is this drift event a cross-provider comparison rather than a re-basing?

    Returns ``True`` when the stored rows did not all come from the provider we
    just fetched from (the comparison straddles two adjustment bases), ``False``
    when stored history and fetch share a single provider (a genuine re-basing
    the operator must clear), and ``None`` when we cannot tell — no fetch source,
    or no provider recorded on any stored row.
    """
    if not stored_sources:
        return None
    known = {str(src) for src in stored_sources if src}
    if not known:
        return None
    if fetch_source is None:
        return None
    return known != {str(fetch_source)}


@dataclass(frozen=True)
class SourceMixingReport:
    """How many symbols hold price history stitched from multiple providers.

    Each provider carries its own adjustment basis, so every source boundary
    inside one symbol's series is a potential seam.  This is deliberately its
    own metric rather than a by-product of drift detection: the drift detector
    only ever sees a symbol when a backfill happens to overlap stored rows, so
    it under-reports splicing by construction.
    """

    total_symbols: int
    single_source_symbols: int
    mixed_symbols: int
    distribution: dict[int, int]
    worst: list[tuple[str, list[str]]]

    @property
    def clean(self) -> bool:
        return self.mixed_symbols == 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "total_symbols": self.total_symbols,
            "single_source_symbols": self.single_source_symbols,
            "mixed_symbols": self.mixed_symbols,
            "distribution": {str(k): v for k, v in sorted(self.distribution.items())},
            "worst": [{"symbol": sym, "sources": srcs} for sym, srcs in self.worst],
        }

    def describe(self) -> str:
        if self.clean:
            return f"{self.total_symbols} symbols, all single-source"
        shape = ", ".join(
            f"{n} sources ×{count}" for n, count in sorted(self.distribution.items()) if n > 1
        )
        return (
            f"{self.mixed_symbols}/{self.total_symbols} symbols hold multi-provider "
            f"price history ({shape})"
        )


def summarize_source_mixing(
    rows: Sequence[tuple[str, str | None]],
    *,
    worst_limit: int = 10,
) -> SourceMixingReport:
    """Summarize per-symbol provider mixing from ``(symbol, source)`` pairs.

    A ``None`` source counts as its own bucket rather than being dropped: rows
    written before provenance was recorded have an unknown basis, and pretending
    they match whatever sits next to them is exactly the assumption that hid the
    seams in the first place.
    """
    by_symbol: dict[str, set[str]] = {}
    for symbol, source in rows:
        by_symbol.setdefault(str(symbol), set()).add(
            UNKNOWN_PRICE_SOURCE if source is None else str(source)
        )
    distribution: dict[int, int] = {}
    for sources in by_symbol.values():
        distribution[len(sources)] = distribution.get(len(sources), 0) + 1
    mixed = sorted(
        ((sym, sorted(srcs)) for sym, srcs in by_symbol.items() if len(srcs) > 1),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return SourceMixingReport(
        total_symbols=len(by_symbol),
        single_source_symbols=sum(1 for srcs in by_symbol.values() if len(srcs) == 1),
        mixed_symbols=len(mixed),
        distribution=distribution,
        worst=mixed[:worst_limit],
    )


def summarize_basis_drift_events(
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Split one day's drift events into "operator must clear" vs "spliced history".

    ``same_source`` events are a genuine re-basing of a series we already hold
    from that same provider: history and new bars now disagree and only
    ``backend.tools.rebase_price_history`` can reconcile them, so they gate the
    day.  ``cross_source`` events merely say two providers disagree, which is
    expected while a symbol's history is spliced — they are reported, not gated,
    because rebasing on whichever provider answered today would just move the
    seam.  ``unknown`` (no provider recorded on the stored rows) gates too: we
    cannot prove it benign, and fail-closed is the house rule.
    """
    same: list[str] = []
    cross: list[str] = []
    unknown: list[str] = []
    for payload in payloads:
        symbol = str(payload.get("symbol") or "")
        flag = payload.get("cross_source")
        if flag is True:
            cross.append(symbol)
        elif flag is False:
            same.append(symbol)
        else:
            unknown.append(symbol)
    uncleared = sorted(set(same) | set(unknown))
    return {
        "status": "available",
        "events": len(payloads),
        "same_source": sorted(set(same)),
        "cross_source": sorted(set(cross)),
        "unknown_source": sorted(set(unknown)),
        "uncleared_symbols": uncleared,
        "uncleared": len(uncleared),
        "clean": not uncleared,
    }


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
