"""Explicit warmup candidate; default One Loop behavior remains unchanged."""

import math
from datetime import date, datetime

import pandas as pd
import pytest

from backend.analysis.factors import calc_atr
from backend.data import market
from backend.data import market_persistence as persistence
from backend.data.database import Price


@pytest.fixture
def market_case(test_db, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 16)

    monkeypatch.setattr(persistence, "date", FixedDate)
    days = pd.bdate_range(end="2026-09-15", periods=320).strftime("%Y-%m-%d")
    frame = pd.DataFrame(
        [
            {
                "open": 100 + math.sin(i),
                "close": 100 + math.sin(i),
                "high": 102 + math.sin(i) + (i % 7) * 0.5,
                "low": 98 + math.sin(i) - (i % 3) * 0.4,
                "volume": 1000,
            }
            for i in range(320)
        ],
        index=days,
    )
    frame.attrs.update(source="test_provider", adjustment="qfq", fetched_at=datetime(2026, 9, 16))
    for day, row in frame.iloc[:-1].iterrows():
        test_db.add(
            Price(
                symbol="600001",
                asset_key="CN:600001",
                market="CN",
                currency="CNY",
                date=day,
                **row.to_dict(),
                atr14=1,
                source="test_provider",
                adjustment="qfq",
            )
        )
    test_db.commit()
    return test_db, frame


def call(db, frame, monkeypatch, **kwargs):
    def fetch_daily(symbol, market_name, days=365, expected_latest=None):
        assert symbol == "600001"
        assert market_name == "CN"
        if expected_latest is not None:
            assert expected_latest == "2026-09-15"
        return frame.tail(days)

    monkeypatch.setattr(market, "fetch_daily", fetch_daily)
    return market.backfill_if_needed(
        "600001",
        "CN",
        db,
        refresh_today=True,
        expected_latest="2026-09-15",
        **kwargs,
    )


def prices(db):
    return [
        (p.date, p.close, p.atr14, p.source) for p in db.query(Price).order_by(Price.date).all()
    ]


def test_short_refresh_reproduces_drift_but_opt_in_warmup_stabilizes_same_write_dates(
    market_case, monkeypatch
):
    db, frame = market_case
    before = prices(db)
    default_count = call(db, frame, monkeypatch)
    default_after = prices(db)
    default_atr = default_after[-1][2]
    desired = float(calc_atr(frame).iloc[-1])
    assert abs(default_atr - desired) > 0.01  # Actual existing refresh path reproduced.
    fixed_count = call(
        db, frame, monkeypatch, strict_basis_write_guard=True, factor_warmup_rows=240
    )
    fixed_after = prices(db)
    assert fixed_count == default_count
    assert fixed_after[-1][2] == pytest.approx(desired, abs=1e-7)
    assert [(r[0], r[1]) for r in fixed_after] == [(r[0], r[1]) for r in default_after]
    assert [r for r in fixed_after if r[0] < "2026-09-10"] == [
        r for r in before if r[0] < "2026-09-10"
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "too_short",
        "duplicate",
        "reversed",
        "mixed_source",
        "missing_source",
        "nonfinite",
        "future",
        "bad_ohlc",
        "stale",
        "invalid_date",
    ],
)
def test_strict_warmup_failures_precede_price_mutation(market_case, monkeypatch, failure):
    db, original = market_case
    frame = original.copy()
    if failure == "too_short":
        frame = frame.tail(12)
    elif failure == "duplicate":
        frame = pd.concat([frame, frame.tail(1)])
    elif failure == "reversed":
        frame = frame.iloc[::-1]
    elif failure == "mixed_source":
        frame.attrs["source"] = "other_provider"
    elif failure == "missing_source":
        frame.attrs["source"] = None
    elif failure == "nonfinite":
        frame.iloc[0, frame.columns.get_loc("high")] = float("nan")
    elif failure == "bad_ohlc":
        frame.iloc[0, frame.columns.get_loc("high")] = 1
    elif failure == "stale":
        frame = frame.iloc[:-1]
    elif failure == "invalid_date":
        frame.index = ["2020-01-40", *frame.index[1:]]
    else:
        frame.index = [*frame.index[:-1], "2026-09-17"]
    before = prices(db)
    with pytest.raises(persistence.PriceBasisWriteBlocked):
        call(db, frame, monkeypatch, strict_basis_write_guard=True, factor_warmup_rows=240)
    assert prices(db) == before


def test_warmup_requires_explicit_strict_guard(market_case, monkeypatch):
    db, frame = market_case
    before = prices(db)
    with pytest.raises(ValueError, match="strict_basis_write_guard"):
        call(db, frame, monkeypatch, factor_warmup_rows=240)
    assert prices(db) == before


def test_warmup_requires_existing_history_before_provider_call(test_db, monkeypatch):
    provider_calls = []

    def fail_if_called(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("warmup must not seed a new symbol through the refresh path")

    monkeypatch.setattr(market, "fetch_daily", fail_if_called)

    with pytest.raises(persistence.PriceBasisWriteBlocked, match="requires existing history"):
        market.backfill_if_needed(
            "600001",
            "CN",
            test_db,
            refresh_today=True,
            expected_latest="2026-09-15",
            strict_basis_write_guard=True,
            factor_warmup_rows=240,
        )

    assert provider_calls == []
    assert prices(test_db) == []


def test_provider_failure_leaves_prices_unchanged(market_case, monkeypatch):
    db, _frame = market_case
    before = prices(db)

    def fail_provider(*args, **kwargs):
        raise RuntimeError("fixture provider failure")

    monkeypatch.setattr(market, "fetch_daily", fail_provider)
    with pytest.raises(RuntimeError, match="fixture provider failure"):
        market.backfill_if_needed(
            "600001",
            "CN",
            db,
            refresh_today=True,
            expected_latest="2026-09-15",
            strict_basis_write_guard=True,
            factor_warmup_rows=240,
        )

    assert prices(db) == before


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("source", "legacy_provider", "stored_sources_mixed"),
        ("source", "   ", "stored_source_missing"),
        ("adjustment", "forward_additive", "stored_adjustments_mixed"),
    ],
)
def test_mixed_stored_provenance_blocks_before_provider(
    market_case, monkeypatch, field, value, reason
):
    db, _frame = market_case
    legacy_row = Price(
        symbol="600001",
        asset_key="CN:600001",
        market="CN",
        currency="CNY",
        date="2020-01-02",
        open=100,
        high=102,
        low=98,
        close=100,
        volume=1000,
        source="test_provider",
        adjustment="qfq",
    )
    setattr(legacy_row, field, value)
    db.add(legacy_row)
    db.commit()
    before = prices(db)
    provider_calls = []

    def fail_if_called(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("mixed stored provenance must fail before provider")

    monkeypatch.setattr(market, "fetch_daily", fail_if_called)
    with pytest.raises(persistence.PriceBasisWriteBlocked, match=reason):
        market.backfill_if_needed(
            "600001",
            "CN",
            db,
            refresh_today=True,
            expected_latest="2026-09-15",
            strict_basis_write_guard=True,
            factor_warmup_rows=240,
        )

    assert provider_calls == []
    assert prices(db) == before


def test_empty_provider_result_is_explicitly_blocked_for_strict_warmup(market_case, monkeypatch):
    db, _frame = market_case
    before = prices(db)
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    empty.attrs.update(source="test_provider", adjustment="qfq")
    monkeypatch.setattr(market, "fetch_daily", lambda *args, **kwargs: empty)

    with pytest.raises(persistence.PriceBasisWriteBlocked, match="provider returned no rows"):
        market.backfill_if_needed(
            "600001",
            "CN",
            db,
            refresh_today=True,
            expected_latest="2026-09-15",
            strict_basis_write_guard=True,
            factor_warmup_rows=240,
        )

    assert prices(db) == before


@pytest.mark.parametrize("partial", [False, True])
def test_strict_warmup_jump_rejection_is_atomic(market_case, monkeypatch, partial):
    db, frame = market_case
    before = prices(db)
    rejected_date = "2026-09-14"

    def reject(close, _preceding):
        if not partial:
            return True
        return close == pytest.approx(float(frame.loc[rejected_date, "close"]))

    monkeypatch.setattr("backend.data.price_quality.check_adjustment_basis_jump", reject)
    with pytest.raises(persistence.PriceBasisWriteBlocked, match="no prices were written"):
        call(db, frame, monkeypatch, strict_basis_write_guard=True, factor_warmup_rows=240)

    assert prices(db) == before


def test_expected_latest_anchors_refresh_window_to_requested_cutoff(market_case, monkeypatch):
    db, frame = market_case
    candidate = frame.copy()
    candidate.loc["2026-09-10", "close"] += 1.0
    before = {row.date: row.close for row in db.query(Price).all()}
    call(db, candidate, monkeypatch)
    after = {row.date: row.close for row in db.query(Price).all()}

    # expected_latest=09-15 gives a 09-10 refresh boundary. date.today() is 09-16,
    # so anchoring to wall-clock time would incorrectly leave the 09-10 bar stale.
    assert after["2026-09-10"] == before["2026-09-10"] + 1.0


def test_expected_latest_before_stored_latest_fails_before_mutation(market_case, monkeypatch):
    db, frame = market_case
    latest = db.query(Price).order_by(Price.date.desc()).first()
    latest.date = "2026-09-16"
    db.commit()
    before = prices(db)

    with pytest.raises(persistence.PriceBasisWriteBlocked, match="precedes newest stored price"):
        call(db, frame, monkeypatch)

    assert prices(db) == before


def test_fully_rejected_refresh_keeps_existing_rows(market_case, monkeypatch):
    db, frame = market_case
    before = prices(db)
    monkeypatch.setattr(
        "backend.data.price_quality.check_adjustment_basis_jump",
        lambda *_args, **_kwargs: True,
    )

    assert call(db, frame, monkeypatch) == 0
    assert prices(db) == before


def test_partially_rejected_refresh_preserves_rejected_date(market_case, monkeypatch):
    db, frame = market_case
    rejected_date = "2026-09-14"
    old_close = db.query(Price).filter(Price.date == rejected_date).one().close
    monkeypatch.setattr(
        "backend.data.price_quality.check_adjustment_basis_jump",
        lambda close, _preceding: close == pytest.approx(float(frame.loc[rejected_date, "close"])),
    )

    count = call(db, frame, monkeypatch)

    assert count > 0
    assert db.query(Price).filter(Price.date == rejected_date).one().close == old_close


def test_refresh_transaction_rolls_back_delete_when_insert_fails(market_case, monkeypatch):
    db, frame = market_case
    before = prices(db)

    def fail_insert(_records):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(db, "bulk_save_objects", fail_insert)
    with pytest.raises(RuntimeError, match="simulated insert failure"):
        call(db, frame, monkeypatch)

    assert prices(db) == before
