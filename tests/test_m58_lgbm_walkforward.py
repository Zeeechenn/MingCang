from __future__ import annotations

import pandas as pd

from backend.data.qlib_data import PRODUCTION_FEATURE_COLS
from backend.tools import m58_lgbm_walkforward as wf


def _synthetic_dates(n: int) -> list[str]:
    return pd.date_range("2021-01-04", periods=n, freq="B").strftime("%Y-%m-%d").tolist()


def test_price_only_feature_cols_excludes_fundamental_and_market_cols():
    assert set(wf.PRICE_ONLY_FEATURE_COLS).issubset(set(PRODUCTION_FEATURE_COLS))
    assert set(wf.PRICE_ONLY_FEATURE_COLS).isdisjoint(wf.NON_PRICE_PRODUCTION_COLS)
    # sanity: fundamental/market cols really are excluded, not accidentally kept
    for col in ("roe", "revenue_yoy", "net_profit_yoy", "gross_margin", "asset_turnover", "log_market_cap", "margin_balance"):
        assert col not in wf.PRICE_ONLY_FEATURE_COLS


def test_schedule_empty_when_insufficient_history():
    dates = _synthetic_dates(100)  # far short of train_window(250)+label_lookahead(6)
    blocks = wf.build_walkforward_schedule(dates, train_window=250, retrain_every=60, label_lookahead=6)
    assert blocks == []


def test_schedule_first_block_respects_train_window_and_label_lookahead():
    dates = _synthetic_dates(400)
    blocks = wf.build_walkforward_schedule(dates, train_window=250, retrain_every=60, label_lookahead=6)
    assert blocks, "expected at least one walk-forward block"

    first = blocks[0]
    # cutoff = train_window + label_lookahead - 1 (0-based)
    assert first.cutoff_idx == 250 + 6 - 1
    assert first.cutoff_date == dates[first.cutoff_idx]
    # training window never exceeds the configured size
    assert len(first.train_dates) <= 250
    # every training date's forward label (date_idx + label_lookahead) resolves
    # on or before the cutoff -- no lookahead into unresolved future labels.
    last_train_idx = dates.index(first.train_dates[-1])
    assert last_train_idx + 6 <= first.cutoff_idx
    # serving starts strictly after the cutoff
    first_serve_idx = dates.index(first.serve_dates[0])
    assert first_serve_idx == first.cutoff_idx + 1


def test_schedule_blocks_have_no_lookahead_and_no_serve_overlap():
    dates = _synthetic_dates(900)
    blocks = wf.build_walkforward_schedule(dates, train_window=250, retrain_every=60, label_lookahead=6)
    assert len(blocks) >= 5

    seen_serve_dates: set[str] = set()
    for block in blocks:
        # no-lookahead invariant for every block, not just the first
        if block.train_dates:
            last_train_idx = dates.index(block.train_dates[-1])
            assert last_train_idx + 6 <= block.cutoff_idx
        first_serve_idx = dates.index(block.serve_dates[0]) if block.serve_dates else None
        if first_serve_idx is not None:
            assert first_serve_idx > block.cutoff_idx

        # no overlap in training window itself (monotonic, size-bounded)
        assert len(block.train_dates) <= 250
        assert len(set(block.train_dates)) == len(block.train_dates)

        # serve windows across blocks must never overlap: each date served once
        overlap = seen_serve_dates.intersection(block.serve_dates)
        assert not overlap, f"serve window overlap detected: {overlap}"
        seen_serve_dates.update(block.serve_dates)

    # cutoffs strictly increasing by retrain_every
    cutoffs = [b.cutoff_idx for b in blocks]
    assert cutoffs == sorted(cutoffs)
    assert all(b - a == 60 for a, b in zip(cutoffs, cutoffs[1:], strict=False))


def test_schedule_train_and_serve_windows_are_disjoint_within_block():
    dates = _synthetic_dates(500)
    blocks = wf.build_walkforward_schedule(dates, train_window=250, retrain_every=60, label_lookahead=6)
    for block in blocks:
        assert set(block.train_dates).isdisjoint(block.serve_dates)


def test_judge_gate_requires_ic_icir_and_non_negative_three_bucket_regimes():
    passing = {
        "selection": {
            "ic": 0.05,
            "icir": 0.5,
            "regime": {
                "up": {"mean_excess": 0.01},
                "down": {"mean_excess": 0.001},
                "flat": {"mean_excess": 0.002},
            },
        }
    }
    gate = wf.judge_gate(passing)
    assert gate["passed"] is True
    assert gate["verdict"] == "过门"

    failing_ic = {
        "selection": {
            "ic": 0.01,
            "icir": 0.5,
            "regime": {"up": {"mean_excess": 0.01}, "down": {"mean_excess": 0.01}, "flat": {"mean_excess": 0.01}},
        }
    }
    assert wf.judge_gate(failing_ic)["passed"] is False

    negative_bucket = {
        "selection": {
            "ic": 0.05,
            "icir": 0.5,
            "regime": {
                "up": {"mean_excess": 0.01},
                "down": {"mean_excess": -0.001},
                "flat": {"mean_excess": 0.002},
            },
        }
    }
    gate2 = wf.judge_gate(negative_bucket)
    assert gate2["passed"] is False
    assert "down" in gate2["negative_buckets"]

    no_regime_data = {"selection": {"ic": 0.05, "icir": 0.5, "regime": {}}}
    assert wf.judge_gate(no_regime_data)["passed"] is False

    # "unknown" is a warm-up residual bucket, not one of the three real
    # regimes -- a negative "unknown" alone must not fail the three-bucket
    # gate check as long as up/down/flat are all non-negative.
    unknown_negative_but_three_buckets_ok = {
        "selection": {
            "ic": 0.05,
            "icir": 0.5,
            "regime": {
                "up": {"mean_excess": 0.01},
                "down": {"mean_excess": 0.001},
                "flat": {"mean_excess": 0.002},
                "unknown": {"mean_excess": -0.0001},
            },
        }
    }
    gate3 = wf.judge_gate(unknown_negative_but_three_buckets_ok)
    assert gate3["passed"] is True
    assert "unknown" not in gate3["negative_buckets"]
