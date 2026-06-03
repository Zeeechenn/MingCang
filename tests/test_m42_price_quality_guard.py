"""Tests for M42 write-time hfq-detection guard in price_quality.py.

These tests exercise ``check_adjustment_basis_jump`` in isolation so the guard
logic can be validated without touching any DB or network.  They also test that
``PriceQualityPolicy`` gained the new ``adjustment_jump_ratio`` field without
breaking existing behaviour.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# PriceQualityPolicy: new field present and backward-compatible
# ---------------------------------------------------------------------------


def test_policy_has_adjustment_jump_ratio_field():
    from backend.data.price_quality import PriceQualityPolicy

    policy = PriceQualityPolicy()
    assert hasattr(policy, "adjustment_jump_ratio")
    # Default must match the module-level HFQ_JUMP_RATIO_THRESHOLD constant.
    from backend.data.price_quality import HFQ_JUMP_RATIO_THRESHOLD
    assert policy.adjustment_jump_ratio == HFQ_JUMP_RATIO_THRESHOLD


def test_policy_custom_jump_ratio():
    from backend.data.price_quality import PriceQualityPolicy

    policy = PriceQualityPolicy(adjustment_jump_ratio=5.0)
    assert policy.adjustment_jump_ratio == 5.0


def test_existing_policy_fields_unchanged():
    """Adding adjustment_jump_ratio must not break existing PriceQualityPolicy fields."""
    from backend.data.price_quality import PriceQualityPolicy

    p = PriceQualityPolicy()
    assert p.recent_window == 20
    assert p.stale_warning_days == 7
    assert p.extreme_price_range_ratio == 20.0
    assert "source" in p.cn_required_provenance


# ---------------------------------------------------------------------------
# check_adjustment_basis_jump: basic pass/reject logic
# ---------------------------------------------------------------------------


def _check(incoming: float, preceding: list[float], threshold: float = 3.0) -> bool:
    from backend.data.price_quality import check_adjustment_basis_jump
    return check_adjustment_basis_jump(incoming, preceding, threshold=threshold)


def test_clean_row_passes():
    """A normal price movement (< threshold) must not be flagged."""
    preceding = [10.0, 10.2, 10.1, 9.9, 10.3, 10.1, 10.4, 10.0, 10.2, 10.1]
    # Close is 1.05× median — well below K=3 threshold.
    assert _check(10.5, preceding) is False


def test_hfq_row_flagged_primary():
    """A close at 193× preceding median must be flagged (mirrors 000001 contamination)."""
    preceding = [10.86] * 10
    assert _check(2098.01, preceding) is True


def test_hfq_row_flagged_moderate():
    """A close at 3.41× preceding median must be flagged (minimum observed contamination)."""
    # 000596 on 2026-05-26: ratio=3.41×
    preceding = [5.0] * 10
    incoming = 5.0 * 3.5  # 3.5× — comfortably above K=3
    assert _check(incoming, preceding) is True


def test_borderline_just_below_threshold_passes():
    """A 2.99× move must NOT be flagged (legitimate rally)."""
    preceding = [10.0] * 10
    assert _check(29.9, preceding) is False


def test_borderline_just_above_threshold_flagged():
    """A 3.01× move must be flagged."""
    preceding = [10.0] * 10
    assert _check(30.1, preceding) is True


def test_custom_threshold_overrides_default():
    """Caller-supplied threshold=5.0 should let a 3.5× move through."""
    preceding = [10.0] * 10
    # 3.5× passes at threshold=5.0 but would fail at default 3.0
    assert _check(35.0, preceding, threshold=5.0) is False


def test_custom_threshold_still_catches_hfq():
    """Caller-supplied threshold=5.0 must still catch a 6× move."""
    preceding = [10.0] * 10
    assert _check(60.0, preceding, threshold=5.0) is True


# ---------------------------------------------------------------------------
# check_adjustment_basis_jump: edge cases — insufficient history
# ---------------------------------------------------------------------------


def test_empty_preceding_passes():
    """No preceding data → cannot flag (guard returns False)."""
    assert _check(9999.0, []) is False


def test_four_preceding_rows_passes():
    """Fewer than 5 usable rows → guard should not fire regardless of ratio."""
    assert _check(9999.0, [10.0, 10.0, 10.0, 10.0]) is False


def test_exactly_five_preceding_rows_can_flag():
    """Exactly 5 usable rows is the minimum required — guard may fire."""
    preceding = [10.0] * 5
    assert _check(9999.0, preceding) is True


def test_zero_values_in_preceding_are_ignored():
    """Zero-valued closes must be excluded from the median calculation."""
    # 4 valid closes + 6 zeros; only 4 usable → guard should not fire.
    preceding = [10.0, 10.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert _check(9999.0, preceding) is False


def test_none_values_in_preceding_are_ignored():
    """None-valued closes are filtered out before median computation."""
    # 5 valid closes out of 10 → guard can fire.
    preceding_with_none = [10.0, None, 10.0, None, 10.0, None, 10.0, None, 10.0, None]
    # Calling via function directly with None in list (type: ignore for test purposes)
    from backend.data.price_quality import check_adjustment_basis_jump
    result = check_adjustment_basis_jump(9999.0, preceding_with_none, threshold=3.0)  # type: ignore[arg-type]
    assert result is True  # 5 usable closes of 10.0; 9999 >> 3× median


# ---------------------------------------------------------------------------
# Integration: guard does not interfere with the read-time evaluate_price_quality
# ---------------------------------------------------------------------------


def test_evaluate_price_quality_still_works_after_m42(test_db):
    """evaluate_price_quality must still function correctly after M42 changes."""
    from datetime import date

    from backend.data.database import Price
    from backend.data.price_quality import evaluate_price_quality

    # Add some Price rows to test_db.
    for i in range(5):
        test_db.add(Price(
            symbol="000001",
            date=f"2026-05-{20 + i:02d}",
            open=10.0, high=11.0, low=9.5, close=10.5, volume=1_000_000,
            source="test_source", fetched_at=None, adjustment="qfq",
        ))
    test_db.commit()

    recent_rows = test_db.query(Price).filter(Price.symbol == "000001").all()
    row = {
        "date": "2026-05-25", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
        "volume": 1_000_000, "source": "test_source", "fetched_at": "2026-05-25T00:00:00",
        "adjustment": "qfq",
    }
    gate = evaluate_price_quality(market="CN", row=row, recent_rows=recent_rows)
    # Should pass or warn (not blocked) for clean data.
    assert gate.status in ("passed", "warning")
    assert "extreme_recent_price_range" not in gate.blockers


def test_evaluate_price_quality_blocks_contaminated_window(test_db):
    """Read-time gate must block when a contaminated row is already in recent_rows."""
    from backend.data.database import Price
    from backend.data.price_quality import evaluate_price_quality

    # Simulate a window where one row is hfq-scale (close=2098) among qfq rows (~10).
    test_db.add(Price(symbol="000001", date="2026-05-24", open=10.0, high=11.0, low=9.5,
                      close=10.5, volume=1_000_000, adjustment=None))
    test_db.add(Price(symbol="000001", date="2026-05-25", open=2000.0, high=2100.0, low=1900.0,
                      close=2098.0, volume=500_000, adjustment=None))
    test_db.commit()

    recent_rows = test_db.query(Price).filter(Price.symbol == "000001").all()
    row = {
        "date": "2026-05-25", "open": 2000.0, "high": 2100.0, "low": 1900.0,
        "close": 2098.0, "volume": 500_000, "source": "test_source",
        "fetched_at": "2026-05-25T00:00:00", "adjustment": None,
    }
    gate = evaluate_price_quality(market="CN", row=row, recent_rows=recent_rows)
    # extreme_recent_price_range should fire (max/min ratio >> 20×).
    assert "extreme_recent_price_range" in gate.blockers
    assert gate.status == "blocked"
