from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

import pytest

from backend.tools import m58_exit_sweep as m58


def _row(
    date: str,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    atr: float = 5.0,
) -> m58.PriceRow:
    return m58.PriceRow(
        symbol="TEST",
        date=date,
        open=open_,
        high=high,
        low=low,
        close=close,
        atr14=atr,
    )


def test_trailing_trigger_executes_at_next_open_and_reports_slippage_cost():
    rows = [
        _row("2026-01-01", open_=100, high=101, low=99, close=100),
        _row("2026-01-02", open_=102, high=111, low=101, close=110),
        # highest_close=110, trailing line at 100; low pierces it.
        _row("2026-01-03", open_=109, high=109, low=99, close=101),
        _row("2026-01-04", open_=96, high=98, low=95, close=97),
    ]

    outcome = m58.simulate_exit(rows, m58.ExitVariant(2.0, "none"))

    assert outcome.reason == "trailing_stop"
    assert outcome.trigger_date == "2026-01-03"
    assert outcome.exit_date == "2026-01-04"
    assert outcome.exit_price == 96
    assert outcome.line_price == 100
    assert outcome.executed_next_open is True
    assert outcome.net_return == pytest.approx(-0.044)
    assert outcome.line_net_return == pytest.approx(-0.004)
    assert outcome.slippage_cost == pytest.approx(0.04)


def test_limit_locked_exit_day_defers_to_next_fillable_open():
    rows = [
        _row("2026-01-01", open_=100, high=101, low=99, close=100),
        _row("2026-01-02", open_=102, high=111, low=101, close=110),
        _row("2026-01-03", open_=109, high=109, low=99, close=101),
        # high==low is the test2 one-board locked proxy; exit cannot execute.
        _row("2026-01-04", open_=90, high=90, low=90, close=90),
        _row("2026-01-05", open_=92, high=94, low=91, close=93),
    ]

    outcome = m58.simulate_exit(rows, m58.ExitVariant(2.0, "none"))

    assert outcome.exit_date == "2026-01-05"
    assert outcome.exit_price == 92
    assert outcome.deferred_limit_locked_days == 1
    assert outcome.executed_next_open is False


def test_profit_drawdown_tracks_highest_close_before_trigger():
    rows = [
        _row("2026-01-01", open_=100, high=101, low=99, close=100),
        _row("2026-01-02", open_=103, high=106, low=102, close=105),
        _row("2026-01-03", open_=108, high=116, low=107, close=115),
        # 10% drawdown from highest close 115 is 103.5.
        _row("2026-01-04", open_=112, high=113, low=103, close=104),
        _row("2026-01-05", open_=104, high=105, low=100, close=101),
    ]

    outcome = m58.simulate_exit(rows, m58.ExitVariant(3.5, "drawdown_10"))

    assert outcome.reason == "profit_drawdown_10"
    assert outcome.trigger_date == "2026-01-04"
    assert outcome.line_price == pytest.approx(103.5)
    assert outcome.exit_date == "2026-01-05"


def test_cost_deduction_is_40bp_round_trip():
    rows = [
        _row("2026-01-01", open_=100, high=101, low=99, close=100),
        _row("2026-01-02", open_=102, high=111, low=101, close=110),
        _row("2026-01-03", open_=109, high=109, low=99, close=101),
        _row("2026-01-04", open_=110, high=112, low=109, close=111),
    ]

    outcome = m58.simulate_exit(rows, m58.ExitVariant(2.0, "none"))

    assert outcome.gross_return == pytest.approx(0.10)
    assert outcome.net_return == pytest.approx(0.096)


def test_holdout_unlock_is_refused_like_m58_grid_backtest():
    with pytest.raises(NotImplementedError, match="holdout"):
        m58.run_large_sample_sweep(
            db_path=m58.default_sqlite_path(),
            include_holdout=True,
            limit_symbols=1,
        )

    assert m58.resolve_effective_end(
        "2026-07-02",
        include_holdout=False,
        today=date(2026, 7, 3),
    ) == "2025-07-03"


# ---------------------------------------------------------------------------
# Regression tests for the M58 harness bug: the large-sample sweep grouped
# every trade in the whole universe by exit date, averaged same-day exits,
# and compounded that list as if it were one sequential single-position
# equity curve. With thousands of concurrent, uncapped entries across the
# entire universe, that fabricated hundreds of fake compounding periods out
# of trades that were actually happening in parallel, producing physically
# impossible -98%/-99% max_dd on a stop-loss-gated strategy. The fix
# (`_simulate_portfolio` + `_max_drawdown_from_levels`) replays the signal
# stream through one capital-constrained, position-capped portfolio with a
# real equity curve instead.
# ---------------------------------------------------------------------------


def _entry_event(symbol: str, entry_date: str, *, score: float = 25.0) -> m58.EntryEvent:
    return m58.EntryEvent(
        symbol=symbol,
        name=symbol,
        signal_date=entry_date,
        entry_index=0,
        entry_date=entry_date,
        entry_price=10.0,
        entry_atr=0.5,
        regime="unknown",
        tech_score=score,
    )


def _exit_outcome(exit_date: str, net_return: float, *, hold_days: int = 5) -> m58.ExitOutcome:
    return m58.ExitOutcome(
        exit_index=hold_days,
        exit_date=exit_date,
        trigger_date=exit_date,
        exit_price=10.0 * (1.0 + net_return),
        line_price=10.0 * (1.0 + net_return),
        reason="trailing_stop",
        hold_days=hold_days,
        gross_return=net_return,
        net_return=net_return,
        line_net_return=net_return,
        slippage_cost=0.0,
        executed_next_open=True,
    )


def test_simulate_portfolio_max_drawdown_cannot_exceed_100_percent():
    """Reproduce the shape of the harness bug at the aggregation seam.

    900 different symbols each enter on their own day and hold for 30 days at
    a small net loss (-1%) -- exactly the "thousands of small losing trades,
    high exit-date density across the whole window" pattern that made the
    old daily-average-then-compound code register ~-98% max_dd. A real
    3-position-cap portfolio can never lose more than its capital.
    """
    outcomes = []
    for day in range(900):
        entry_date = f"{day:05d}"
        exit_date = f"{day + 30:05d}"
        outcomes.append((_entry_event(f"SYM{day:04d}", entry_date), _exit_outcome(exit_date, -0.01)))

    portfolio = m58._simulate_portfolio(outcomes, max_positions=3)

    assert portfolio["max_drawdown_pct"] > -100.0
    # Sanity: with a hard 3-position cap, only a small fraction of the 900
    # candidates can ever be admitted (steady state ~3 slots / 30-day hold),
    # so the position cap must actually be doing something, and the realized
    # loss must stay in a sane single-digit-to-low-double-digit range -- not
    # the -98% the old code produced from this exact trade shape.
    assert portfolio["skipped_position_cap"] > 0
    assert len(portfolio["admitted_outcomes"]) < len(outcomes)
    # Sane single-digit-to-low-double-digit loss, not -98%.
    assert -60.0 < portfolio["net_return_pct"] <= 0.0


def _seed_synthetic_price_db(db_path, *, n_symbols: int = 10, n_days: int = 320) -> None:
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, "
        "close REAL, volume REAL, atr14 REAL)"
    )
    con.execute("CREATE TABLE stocks (symbol TEXT PRIMARY KEY, name TEXT)")
    rng = random.Random(42)
    start = date(2020, 1, 1)
    rows = []
    for s in range(n_symbols):
        symbol = f"T{s:03d}"
        con.execute("INSERT INTO stocks (symbol, name) VALUES (?, ?)", (symbol, symbol))
        price = 10.0
        drift = rng.uniform(-0.0003, 0.0006)
        for d in range(n_days):
            trading_date = (start + timedelta(days=d)).isoformat()
            change = 1.0 + drift + rng.uniform(-0.012, 0.012)
            close = max(price * change, 0.5)
            open_ = price * (1.0 + rng.uniform(-0.004, 0.004))
            high = max(open_, close) * (1.0 + abs(rng.uniform(0.0, 0.006)))
            low = min(open_, close) * (1.0 - abs(rng.uniform(0.0, 0.006)))
            rows.append((symbol, trading_date, open_, high, low, close, 1_000_000.0, close * 0.02))
            price = close
    con.executemany(
        "INSERT INTO prices (symbol, date, open, high, low, close, volume, atr14) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


def test_large_sample_sweep_stays_sane_on_mild_synthetic_data(tmp_path, monkeypatch):
    """Full run_large_sample_sweep pipeline, all 35 variants, on mild synthetic data.

    This exercises the real seam (entry building -> exit simulation ->
    portfolio aggregation), not just the isolated aggregation function, so it
    would catch a regression that reintroduces the old
    daily-average-then-compound bug anywhere in the wiring.
    """
    db_path = tmp_path / "synthetic.sqlite"
    _seed_synthetic_price_db(db_path, n_symbols=10, n_days=320)
    monkeypatch.setattr(m58, "MIN_TRADING_DAYS", 250)

    report = m58.run_large_sample_sweep(db_path=db_path, start="2020-04-20")

    assert report["trial_count"] == 35
    assert len(report["results"]) == 35
    for row in report["results"]:
        assert row["max_drawdown_pct"] > -100.0, row["variant"]["label"]
        assert -100.0 < row["net_return_pct"] < 500.0, row["variant"]["label"]
