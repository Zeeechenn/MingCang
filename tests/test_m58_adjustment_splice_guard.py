"""Tests for M58 — symmetric down-splice extension of the write-time guard.

Background: Phase 1a audit found symbols with adjustment-basis-splice
contamination presenting as a *downward* single-day price jump (ratios as low
as ~0.047x observed in production data), which the M42-era
``check_adjustment_basis_jump`` never caught because it only checked the
up-direction (``close > threshold * median``).  This file exercises the M58
down-direction extension in isolation, plus the A-share limit-down boundary
that motivated using a narrower window for the down-check than the up-check.
"""
from __future__ import annotations

from statistics import median

from backend.data.price_quality import (
    DOWN_SPLICE_WINDOW,
    HFQ_JUMP_RATIO_THRESHOLD,
    check_adjustment_basis_jump,
)


def _check(incoming: float, preceding: list[float], threshold: float = 3.0) -> bool:
    return check_adjustment_basis_jump(incoming, preceding, threshold=threshold)


# ---------------------------------------------------------------------------
# Up-direction (M42) must still work unchanged after the M58 edit.
# ---------------------------------------------------------------------------


def test_up_splice_still_flagged_after_m58_change():
    """M42's original up-jump detection must be unaffected by the M58 edit."""
    preceding = [10.86] * 10
    assert _check(2098.01, preceding) is True


def test_up_splice_borderline_unaffected():
    preceding = [10.0] * 10
    assert _check(29.9, preceding) is False  # 2.99x, just below threshold
    assert _check(30.1, preceding) is True  # 3.01x, just above threshold


# ---------------------------------------------------------------------------
# Down-direction (M58): real production contamination ratios.
# ---------------------------------------------------------------------------


def test_down_splice_flagged_extreme():
    """002130-style contamination: 0.047x preceding median must be flagged."""
    preceding = [460.085] * 10
    incoming = 21.99  # ratio ≈ 0.0478
    assert _check(incoming, preceding) is True


def test_down_splice_flagged_moderate():
    """600522-style contamination: 0.125x must be flagged."""
    preceding = [338.7] * 10
    incoming = 42.19  # ratio ≈ 0.1246
    assert _check(incoming, preceding) is True


def test_down_splice_borderline_just_below_threshold_flagged():
    """A close at exactly 1/3.01 of median (just past the 1/3 cutoff) is flagged."""
    preceding = [10.0] * 10
    assert _check(10.0 / 3.01, preceding) is True


def test_down_splice_borderline_just_above_threshold_passes():
    """A close at just above 1/2.99 of median (just short of the cutoff) passes."""
    preceding = [10.0] * 10
    assert _check(10.0 / 2.99, preceding) is False


def test_down_splice_exactly_one_third_passes():
    """Exactly incoming == median/threshold must NOT be flagged (strict <)."""
    preceding = [30.0] * 10
    assert _check(10.0, preceding) is False


def test_custom_threshold_affects_down_direction_too():
    """A caller-supplied threshold=5.0 tightens the down-check symmetrically."""
    preceding = [10.0] * 10
    # 1/4 = 0.25 -> flagged at threshold=3 (0.25 < 0.333) but NOT at threshold=5
    # (0.25 > 0.2), demonstrating the threshold parameter now governs both
    # directions.
    assert _check(2.5, preceding, threshold=3.0) is True
    assert _check(2.5, preceding, threshold=5.0) is False


# ---------------------------------------------------------------------------
# Normal volatility must pass in both directions.
# ---------------------------------------------------------------------------


def test_normal_daily_volatility_passes_both_directions():
    preceding = [10.0, 10.2, 9.8, 10.1, 9.9, 10.3, 10.0, 9.7, 10.2, 10.1]
    med = median(preceding)
    # +5% and -5% moves must both pass.
    assert _check(med * 1.05, preceding) is False
    assert _check(med * 0.95, preceding) is False


def test_single_real_limit_down_day_passes():
    """A single genuine -10% (main board) or -20% (ChiNext/STAR) day must pass."""
    preceding = [10.0] * 10
    assert _check(9.0, preceding) is False  # -10% main-board limit
    assert _check(8.0, preceding) is False  # -20% ChiNext/STAR limit


# ---------------------------------------------------------------------------
# A-share consecutive limit-down boundary: the critical false-positive risk
# this guard must NOT trigger on.
# ---------------------------------------------------------------------------


def _decline_sequence(days: int, factor: float = 0.8, start: float = 100.0) -> list[float]:
    """Build a pure consecutive-limit-down price sequence, oldest -> newest."""
    seq = [start]
    for _ in range(days):
        seq.append(seq[-1] * factor)
    return seq


def test_five_day_20pct_limit_down_streak_not_flagged():
    """5 consecutive -20% (ChiNext/STAR board) limit-down days is real
    trading, not a splice — must NOT be flagged.

    Worked math (see DOWN_SPLICE_WINDOW comment in price_quality.py):
    comparing the 6th consecutive -20% close against the median of the
    preceding 5 (already-declined) closes gives ratio = 0.8**3 = 0.512,
    comfortably above the 1/3 = 0.333 cutoff.
    """
    seq = _decline_sequence(6, factor=0.8, start=100.0)
    preceding = seq[:-1]  # 6 closes: the 5-window down-check uses the last 5
    incoming = seq[-1]
    ratio = incoming / median(preceding[-DOWN_SPLICE_WINDOW:])
    assert abs(ratio - 0.512) < 1e-9
    assert check_adjustment_basis_jump(incoming, preceding) is False


def test_ten_day_20pct_limit_down_streak_not_flagged_by_actual_guard():
    """Even a 10-day continuous -20% streak must not be flagged by the real
    guard, because the down-check intentionally uses only the closest
    DOWN_SPLICE_WINDOW (5) preceding closes — NOT the full window a caller
    may pass in (up to 10).

    This is the case that *would* misfire if the down-check reused the same
    window as the up-check; see test_naive_full_window_down_check_would_misfire
    below for the demonstration of why that design was rejected.
    """
    seq = _decline_sequence(10, factor=0.8, start=100.0)
    preceding = seq[:-1]  # 10 preceding closes
    incoming = seq[-1]
    assert check_adjustment_basis_jump(incoming, preceding) is False


def test_naive_full_window_down_check_would_misfire_at_window_nine_or_ten():
    """Documents *why* DOWN_SPLICE_WINDOW=5 was chosen instead of reusing the
    full up-to-10 window: a naive symmetric check using the *entire*
    preceding-closes window would false-positive on a real 9-10 day
    consecutive -20%-board limit-down streak.

    This test does not exercise check_adjustment_basis_jump (which is
    already safe) — it directly demonstrates the arithmetic that motivated
    the narrower down-check window, so the safety margin stays documented
    and testable rather than just asserted in a comment.
    """
    for window, expect_unsafe in ((5, False), (8, False), (9, True), (10, True)):
        seq = _decline_sequence(window, factor=0.8, start=100.0)
        preceding = seq[:-1]
        incoming = seq[-1]
        naive_ratio = incoming / median(preceding)  # uses the FULL window, not capped at 5
        is_below_third = naive_ratio < (1.0 / HFQ_JUMP_RATIO_THRESHOLD)
        assert is_below_third is expect_unsafe, (
            f"window={window} naive_ratio={naive_ratio:.4f} "
            f"expected unsafe={expect_unsafe}"
        )


def test_ten_day_10pct_main_board_limit_down_streak_never_unsafe():
    """A main-board (-10%/day) consecutive limit-down streak decays much more
    slowly than a ChiNext/STAR (-20%/day) streak and stays far above the 1/3
    cutoff even at a 10-row naive window — sanity check that the risk is
    specific to the 20%-board case, not general to any consecutive decline.
    """
    seq = _decline_sequence(10, factor=0.9, start=100.0)
    preceding = seq[:-1]
    incoming = seq[-1]
    naive_ratio = incoming / median(preceding)
    assert naive_ratio > (1.0 / HFQ_JUMP_RATIO_THRESHOLD)
    assert check_adjustment_basis_jump(incoming, preceding) is False


# ---------------------------------------------------------------------------
# Edge cases mirrored from the up-direction (M42) suite.
# ---------------------------------------------------------------------------


def test_down_check_respects_min_preceding_five():
    """Fewer than 5 usable preceding closes -> guard never fires (either direction)."""
    assert check_adjustment_basis_jump(0.001, [10.0, 10.0, 10.0, 10.0]) is False


def test_down_check_ignores_zero_and_none_values():
    preceding = [10.0, 10.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    # Only 4 usable -> below min_preceding=5 -> must not fire even though
    # 0.001 is far below any real median.
    assert check_adjustment_basis_jump(0.001, preceding) is False
