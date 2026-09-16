"""Explicit warmup candidate; default One Loop behavior remains unchanged."""

import math
from datetime import date, datetime

import pandas as pd
import pytest

from backend.analysis.factors import calc_atr
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


def call(db, frame, **kwargs):
    return persistence.backfill_if_needed(
        "600001",
        "CN",
        db,
        refresh_today=True,
        expected_latest="2026-09-15",
        fetch_daily_fn=lambda *a, days, **k: frame.tail(days),
        **kwargs,
    )


def prices(db):
    return [
        (p.date, p.close, p.atr14, p.source) for p in db.query(Price).order_by(Price.date).all()
    ]


def test_short_refresh_reproduces_drift_but_opt_in_warmup_stabilizes_same_write_dates(market_case):
    db, frame = market_case
    before = prices(db)
    default_count = call(db, frame)
    default_after = prices(db)
    default_atr = default_after[-1][2]
    desired = float(calc_atr(frame).iloc[-1])
    assert abs(default_atr - desired) > 0.01  # Actual existing refresh path reproduced.
    fixed_count = call(db, frame, strict_basis_write_guard=True, factor_warmup_rows=240)
    fixed_after = prices(db)
    assert fixed_count == default_count
    assert fixed_after[-1][2] == pytest.approx(desired, abs=1e-7)
    assert [(r[0], r[1]) for r in fixed_after] == [(r[0], r[1]) for r in default_after]
    assert [r for r in fixed_after if r[0] < "2026-09-11"] == [
        r for r in before if r[0] < "2026-09-11"
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
def test_strict_warmup_failures_precede_price_mutation(market_case, failure):
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
        call(db, frame, strict_basis_write_guard=True, factor_warmup_rows=240)
    assert prices(db) == before


def test_warmup_requires_explicit_strict_guard(market_case):
    db, frame = market_case
    with pytest.raises(ValueError, match="strict_basis_write_guard"):
        call(db, frame, factor_warmup_rows=240)
