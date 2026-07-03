from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.analysis.technical import technical_score
from backend.backtest.costs import A_SHARE_ROUND_TRIP_COST
from backend.tools import m58_grid_backtest as m58


def test_cross_sectional_zscore_and_rank_normalization():
    panel = pd.DataFrame(
        {
            "date": ["2024-01-02"] * 3,
            "symbol": ["a", "b", "c"],
            "T": [1.0, 2.0, 3.0],
            "M": [5.0, 5.0, 5.0],
        }
    )

    z = m58.normalize_families(panel, ["T", "M"], method="zscore")
    assert z["T"].round(6).tolist() == [-1.0, 0.0, 1.0]
    assert z["M"].tolist() == [0.0, 0.0, 0.0]

    ranked = m58.normalize_families(panel, ["T"], method="rank")
    assert ranked["T"].round(6).tolist() == [0.0, 0.5, 1.0]


def test_weight_grid_for_two_families_has_spec_count_and_zero_weights():
    grid = m58.enumerate_weight_grid(["T", "M"])

    assert len(grid) == 11
    assert {"name": "weight:T=1.0", "weights": {"T": 1.0, "M": 0.0}, "kind": "weighted"} in grid
    assert {"name": "weight:M=1.0", "weights": {"T": 0.0, "M": 1.0}, "kind": "weighted"} in grid
    assert any(row["weights"] == {"T": 0.4, "M": 0.6} for row in grid)


def test_rule_scores_apply_gating_and_serial_logic():
    panel = pd.DataFrame(
        {
            "date": ["2024-01-02"] * 5,
            "symbol": list("abcde"),
            "T": [5, 4, 3, 2, 1],
            "M": [1, 2, 3, 4, 5],
        }
    )

    gated = m58.apply_rule_score(panel, "gate_T_exclude_M_bottom20")
    assert gated.loc[gated["symbol"] == "a", "score"].iloc[0] < -1e8
    assert gated.loc[gated["symbol"] == "b", "score"].iloc[0] == 4

    serial = m58.apply_rule_score(panel, "serial_M_top50_then_T")
    assert serial.loc[serial["symbol"] == "a", "score"].iloc[0] < -1e8
    assert serial.loc[serial["symbol"] == "e", "score"].iloc[0] == 1


def test_holdout_exclusion_clamps_default_end_and_refuses_unlock():
    assert m58.resolve_effective_end(None, today=date(2026, 7, 3)) == "2025-07-03"
    assert m58.resolve_effective_end("2026-01-01", today=date(2026, 7, 3)) == "2025-07-03"
    assert m58.resolve_effective_end("2024-06-30", today=date(2026, 7, 3)) == "2024-06-30"

    with pytest.raises(NotImplementedError, match="holdout 只能由 leader 显式解锁"):
        m58.resolve_effective_end("2026-01-01", include_holdout=True, today=date(2026, 7, 3))


def test_forward_five_day_return_uses_t_plus_1_entry_t_plus_6_exit_and_cost():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=7, freq="D").strftime("%Y-%m-%d"),
            "symbol": ["a"] * 7,
            "close": [10.0, 100.0, 101.0, 102.0, 103.0, 104.0, 110.0],
        }
    )

    out = m58.attach_forward_returns(df)

    assert out.loc[0, "forward_5d_net_return"] == pytest.approx(0.10 - A_SHARE_ROUND_TRIP_COST)
    assert pd.isna(out.loc[1, "forward_5d_net_return"])


def test_technical_score_series_matches_production_score_for_a_day():
    rows = []
    close = 10.0
    for i in range(90):
        close += 0.1 if i < 45 else (-0.05 if i < 65 else 0.2)
        rows.append(
            {
                "date": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": close - 0.05,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": 1000 + i * 10,
            }
        )
    df = pd.DataFrame(rows)

    series_scores = m58.compute_technical_scores(df, symbol="600000")
    expected = technical_score(df.iloc[:75], symbol="600000")["score"]

    assert series_scores.iloc[74] == expected


def test_pool_equal_weight_regime_fallback_labels_dates():
    panel = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01", "2024-03-01", "2024-03-01"],
            "symbol": ["a", "b"] * 3,
            "close": [10, 20, 12, 24, 11, 22],
        }
    )

    regimes = m58.regime_from_pool_equal_weight(panel, short_window=1, long_window=2, flat_band=0.01)

    assert set(regimes.columns) == {"date", "regime"}
    assert regimes["regime"].tolist() == ["unknown", "up", "down"]
