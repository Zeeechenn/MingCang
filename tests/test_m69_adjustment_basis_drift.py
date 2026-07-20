"""Tests for the M69 adjustment-basis drift detector in price_quality.py.

These exercise ``detect_adjustment_basis_drift`` in isolation (no DB, no
network).  The detector is complementary to the M42/M58 ratio guard: it catches
small whole-series re-basings (cash dividends) that the 3x ratio guard is blind
to, by comparing same-date closes between a fresh fetch and what is stored.

The headline regression case is 600900 长江电力 on 2026-07-15: the provider
re-based the series by 0.79 on ex-dividend, the stored pre-ex rows kept the old
basis, and the resulting seam silently corrupted P&L (+6.58% reported vs +9.77%
actual), the take-profit comparison, and ATR14 (0.6343 vs a clean 0.5936).
"""
from __future__ import annotations

import pytest

from backend.data.price_quality import (
    BASIS_DRIFT_MIN_COMPARED,
    AdjustmentBasisDrift,
    detect_adjustment_basis_drift,
)

# Real 600900 data. Stored rows up to 07-14 are on the pre-ex basis (0.79 high);
# 07-15 onward already match the provider.
_STORED_600900 = {
    "2026-07-08": 27.83, "2026-07-09": 27.77, "2026-07-10": 28.03,
    "2026-07-13": 28.42, "2026-07-14": 28.55,
    "2026-07-15": 27.89, "2026-07-16": 27.45,
}
_FETCHED_600900 = {
    "2026-07-08": 27.04, "2026-07-09": 26.98, "2026-07-10": 27.24,
    "2026-07-13": 27.63, "2026-07-14": 27.76,
    "2026-07-15": 27.89, "2026-07-16": 27.45,
}


def test_detects_real_600900_dividend_rebasing():
    drift = detect_adjustment_basis_drift(_FETCHED_600900, _STORED_600900)

    assert drift.detected
    assert drift.kind == "additive"
    assert drift.divergent_rows == 5
    assert drift.compared_rows == 7
    assert drift.median_delta == pytest.approx(-0.79, abs=0.01)
    # Only the pre-ex rows are implicated; the post-ex rows already agree.
    assert drift.earliest_divergent_date == "2026-07-08"
    assert drift.latest_divergent_date == "2026-07-14"


def test_m42_ratio_guard_is_blind_to_this_case():
    """Documents *why* M69 exists: the existing guard cannot see a 2.8% shift."""
    from backend.data.price_quality import check_adjustment_basis_jump

    preceding = [27.83, 27.77, 28.03, 28.42, 28.55, 27.89, 27.45]
    # The first post-ex bar looks perfectly ordinary to a ratio-based guard.
    assert check_adjustment_basis_jump(27.89, preceding) is False


def test_clean_series_reports_no_drift():
    drift = detect_adjustment_basis_drift(_FETCHED_600900, _FETCHED_600900)
    assert not drift.detected
    assert drift.kind == "none"
    assert drift.divergent_rows == 0


def test_pure_incremental_backfill_has_no_overlap():
    """Normal append-only path must never trip the detector."""
    drift = detect_adjustment_basis_drift(
        {"2026-07-17": 27.99, "2026-07-20": 28.98},
        {"2026-07-16": 27.45},
    )
    assert not drift.detected
    assert drift.compared_rows == 0


def test_float_noise_is_not_drift():
    stored = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0}
    fetched = {"a": 10.000001, "b": 19.999998, "c": 30.000002, "d": 39.999999}
    assert not detect_adjustment_basis_drift(fetched, stored).detected


def test_detects_multiplicative_rebasing():
    """A split / adjustment-mode change shows up as a uniform ratio."""
    stored = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0}
    fetched = {"a": 5.0, "b": 10.0, "c": 15.0, "d": 20.0}
    drift = detect_adjustment_basis_drift(fetched, stored)

    assert drift.detected
    assert drift.kind == "multiplicative"
    assert drift.median_ratio == pytest.approx(0.5)


def test_single_corrected_bar_is_not_called_a_rebasing():
    """One divergent row makes 'uniform' vacuous — must not claim a dividend."""
    stored = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0}
    fetched = {"a": 10.0, "b": 20.0, "c": 33.0, "d": 40.0}
    drift = detect_adjustment_basis_drift(fetched, stored)

    assert drift.detected
    assert drift.kind == "mixed"
    assert "non-uniform" in drift.describe()


def test_insufficient_overlap_is_inconclusive():
    stored = {"a": 9.0, "b": 9.0}
    fetched = {"a": 1.0, "b": 2.0}
    drift = detect_adjustment_basis_drift(fetched, stored)

    assert len(stored) < BASIS_DRIFT_MIN_COMPARED
    assert not drift.detected
    assert drift.compared_rows == 2


def test_non_positive_stored_close_is_skipped():
    stored = {"a": 0.0, "b": 20.0, "c": 30.0, "d": 40.0}
    fetched = {"a": 5.0, "b": 20.0, "c": 30.0, "d": 40.0}
    assert not detect_adjustment_basis_drift(fetched, stored).detected


def test_payload_and_describe_are_serialisable():
    drift = detect_adjustment_basis_drift(_FETCHED_600900, _STORED_600900)
    payload = drift.to_payload()

    assert payload["detected"] is True
    assert payload["kind"] == "additive"
    assert isinstance(drift.describe(), str)
    assert isinstance(drift, AdjustmentBasisDrift)


def test_clean_drift_describe_is_explicit():
    drift = detect_adjustment_basis_drift(_FETCHED_600900, _FETCHED_600900)
    assert drift.describe() == "no adjustment-basis drift"
