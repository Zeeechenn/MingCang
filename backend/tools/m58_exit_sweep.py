"""M58 exit-parameter sweep using MingCang's existing replay conventions.

The large-sample entry stream follows the existing ``backtrader_eval`` technical
entry convention: point-in-time technical score above the strategy threshold,
with execution at the next trading day's open.  The exit simulator is shared by
the large-sample sweep and the test2 replay comparison so the exit rule itself
has one implementation.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import sqlite3
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.backtest.backtrader_eval import compute_tech_scores
from backend.backtest.compare_paths import _max_drawdown
from backend.config import default_sqlite_path
from backend.tools.m58_grid_backtest import regime_from_pool_equal_weight, resolve_effective_end

OUTPUT_JSON = Path("/private/tmp/m58_exit_sweep_report.json")
OUTPUT_MD = Path("/private/tmp/m58_exit_sweep_report.md")
START_DATE = "2021-05-21"
TEST2_START = "2026-05-12"
TEST2_END = "2026-07-02"
MIN_TRADING_DAYS = 1000
ENTRY_THRESHOLD = 20.0
INITIAL_ATR_MULT = 2.0
CURRENT_TRAILING_ATR_MULT = 2.5
RISK_REWARD_RATIO = 1.5
ROUND_TRIP_COST = 0.004
TRAILING_MULTS = (2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5)
PROFIT_MODES = ("none", "drawdown_8", "drawdown_10", "drawdown_15", "half_take_profit_trailing")

ProfitMode = Literal["none", "drawdown_8", "drawdown_10", "drawdown_15", "half_take_profit_trailing"]


@dataclass(frozen=True)
class PriceRow:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    atr14: float | None = None


@dataclass(frozen=True)
class ExitVariant:
    trailing_atr_mult: float
    profit_mode: ProfitMode

    @property
    def key(self) -> str:
        mult = f"{self.trailing_atr_mult:g}".replace(".", "_")
        return f"trailing_{mult}__{self.profit_mode}"

    @property
    def label(self) -> str:
        return f"trailingx{self.trailing_atr_mult:g} / {self.profit_mode}"


@dataclass(frozen=True)
class ExitOutcome:
    exit_index: int
    exit_date: str
    trigger_date: str
    exit_price: float
    line_price: float
    reason: str
    hold_days: int
    gross_return: float
    net_return: float
    line_net_return: float
    slippage_cost: float
    executed_next_open: bool
    deferred_limit_locked_days: int = 0


@dataclass(frozen=True)
class EntryEvent:
    symbol: str
    name: str
    signal_date: str
    entry_index: int
    entry_date: str
    entry_price: float
    entry_atr: float
    regime: str
    tech_score: float


def iter_exit_variants() -> list[ExitVariant]:
    return [ExitVariant(mult, mode) for mult in TRAILING_MULTS for mode in PROFIT_MODES]  # type: ignore[arg-type]


def _is_locked_limit_bar(row: PriceRow) -> bool:
    return row.high == row.low


def _next_executable_open(rows: list[PriceRow], trigger_idx: int) -> tuple[int, int]:
    deferred = 0
    for idx in range(trigger_idx + 1, len(rows)):
        if _is_locked_limit_bar(rows[idx]):
            deferred += 1
            continue
        return idx, deferred
    return len(rows) - 1, deferred


def _gross(entry_price: float, exit_price: float) -> float:
    return exit_price / entry_price - 1.0 if entry_price else 0.0


def _net(gross_return: float) -> float:
    return gross_return - ROUND_TRIP_COST


def _profit_drawdown_pct(mode: ProfitMode) -> float | None:
    if mode == "drawdown_8":
        return 0.08
    if mode == "drawdown_10":
        return 0.10
    if mode == "drawdown_15":
        return 0.15
    return None


def simulate_exit(rows: list[PriceRow], variant: ExitVariant) -> ExitOutcome:
    """Simulate one entry path.

    ``rows[0]`` is the entry execution bar.  Stop/take triggers are detected on
    later bars, but execution is the next non-locked trading day's open.  The
    returned ``line_net_return`` is the counterfactual fill-at-trigger-line
    result used to report gap/slippage cost.
    """
    if len(rows) < 2:
        row = rows[0]
        return ExitOutcome(
            exit_index=0,
            exit_date=row.date,
            trigger_date=row.date,
            exit_price=row.close,
            line_price=row.close,
            reason="end",
            hold_days=0,
            gross_return=0.0,
            net_return=-ROUND_TRIP_COST,
            line_net_return=-ROUND_TRIP_COST,
            slippage_cost=0.0,
            executed_next_open=False,
        )

    entry = rows[0]
    entry_atr = float(entry.atr14 or 0.0)
    if entry_atr <= 0:
        raise ValueError("entry atr14 must be positive")
    initial_stop = entry.open - entry_atr * INITIAL_ATR_MULT
    take_line = entry.open + entry_atr * INITIAL_ATR_MULT * RISK_REWARD_RATIO
    highest_close = entry.close
    stop_line = initial_stop
    half_exit: tuple[int, float, float, int] | None = None  # idx, fill, line, deferred
    drawdown_pct = _profit_drawdown_pct(variant.profit_mode)

    for idx in range(1, len(rows)):
        row = rows[idx]
        if row.close > highest_close:
            highest_close = row.close
        trailing_line = highest_close - entry_atr * variant.trailing_atr_mult
        stop_line = max(initial_stop, trailing_line)

        reason: str | None = None
        line_price: float | None = None

        if row.low <= initial_stop and initial_stop >= stop_line:
            reason = "stop_loss"
            line_price = initial_stop
        elif row.low <= stop_line:
            reason = "trailing_stop"
            line_price = stop_line

        if reason is None and drawdown_pct is not None:
            drawdown_line = highest_close * (1.0 - drawdown_pct)
            if row.low <= drawdown_line:
                reason = f"profit_drawdown_{int(drawdown_pct * 100)}"
                line_price = drawdown_line

        if (
            reason is None
            and variant.profit_mode == "half_take_profit_trailing"
            and half_exit is None
            and row.high >= take_line
        ):
            exec_idx, deferred = _next_executable_open(rows, idx)
            half_exit = (exec_idx, rows[exec_idx].open, take_line, deferred)
            continue

        if reason is not None and line_price is not None:
            exec_idx, deferred = _next_executable_open(rows, idx)
            exit_row = rows[exec_idx]
            if half_exit is not None:
                half_idx, half_fill, half_line, half_deferred = half_exit
                gross_return = 0.5 * _gross(entry.open, half_fill) + 0.5 * _gross(entry.open, exit_row.open)
                line_return = 0.5 * _gross(entry.open, half_line) + 0.5 * _gross(entry.open, line_price)
                reason = f"half_take_profit_then_{reason}"
                trigger_date = row.date
                hold_days = max(half_idx, exec_idx)
                deferred += half_deferred
            else:
                gross_return = _gross(entry.open, exit_row.open)
                line_return = _gross(entry.open, line_price)
                trigger_date = row.date
                hold_days = exec_idx
            net_return = _net(gross_return)
            line_net = _net(line_return)
            return ExitOutcome(
                exit_index=exec_idx,
                exit_date=exit_row.date,
                trigger_date=trigger_date,
                exit_price=exit_row.open,
                line_price=line_price,
                reason=reason,
                hold_days=hold_days,
                gross_return=round(gross_return, 8),
                net_return=round(net_return, 8),
                line_net_return=round(line_net, 8),
                slippage_cost=round(line_net - net_return, 8),
                executed_next_open=exec_idx == idx + 1,
                deferred_limit_locked_days=deferred,
            )

    last_idx = len(rows) - 1
    last = rows[last_idx]
    gross_return = _gross(entry.open, last.close)
    line_return = gross_return
    reason = "end"
    if half_exit is not None:
        half_idx, half_fill, half_line, half_deferred = half_exit
        gross_return = 0.5 * _gross(entry.open, half_fill) + 0.5 * _gross(entry.open, last.close)
        line_return = 0.5 * _gross(entry.open, half_line) + 0.5 * _gross(entry.open, last.close)
        reason = "half_take_profit_then_end"
        last_idx = max(last_idx, half_idx)
    net_return = _net(gross_return)
    line_net = _net(line_return)
    return ExitOutcome(
        exit_index=last_idx,
        exit_date=last.date,
        trigger_date=last.date,
        exit_price=last.close,
        line_price=last.close,
        reason=reason,
        hold_days=last_idx,
        gross_return=round(gross_return, 8),
        net_return=round(net_return, 8),
        line_net_return=round(line_net, 8),
        slippage_cost=round(line_net - net_return, 8),
        executed_next_open=False,
        deferred_limit_locked_days=half_exit[3] if half_exit else 0,
    )


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"database does not exist: {resolved}")
    con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _eligible_symbols(con: sqlite3.Connection, *, min_days: int, limit_symbols: int | None) -> list[dict[str, str]]:
    rows = con.execute(
        """
        SELECT p.symbol, COALESCE(s.name, p.symbol) AS name, COUNT(DISTINCT p.date) AS n
        FROM prices p
        LEFT JOIN stocks s ON s.symbol = p.symbol
        GROUP BY p.symbol
        HAVING n >= ?
        ORDER BY p.symbol
        """,
        (min_days,),
    ).fetchall()
    out = [{"symbol": str(row["symbol"]), "name": str(row["name"])} for row in rows]
    return out[:limit_symbols] if limit_symbols else out


def _load_price_frame(con: sqlite3.Connection, symbols: list[str], *, end: str) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in symbols)
    rows = con.execute(
        f"""
        SELECT symbol, date, open, high, low, close, volume, atr14
        FROM prices
        WHERE symbol IN ({placeholders})
          AND date <= ?
        ORDER BY symbol, date
        """,
        [*symbols, end],
    ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume", "atr14"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close", "atr14"]).copy()


def _price_rows(group: pd.DataFrame) -> list[PriceRow]:
    return [
        PriceRow(
            symbol=str(row.symbol),
            date=str(row.date),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            atr14=float(row.atr14) if pd.notna(row.atr14) else None,
        )
        for row in group.itertuples(index=False)
    ]


def _build_entry_events(prices: pd.DataFrame, *, start: str, end: str, names: dict[str, str]) -> tuple[list[EntryEvent], dict[str, list[PriceRow]], dict[str, int]]:
    regimes = regime_from_pool_equal_weight(prices[["date", "symbol", "close"]])
    regime_by_date = dict(zip(regimes["date"], regimes["regime"], strict=False))
    events: list[EntryEvent] = []
    rows_by_symbol: dict[str, list[PriceRow]] = {}
    skipped = Counter()

    for symbol, group in prices.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        local = group.reset_index(drop=True).copy()
        try:
            local = add_all_factors(local)
            local["tech_score"] = compute_tech_scores(local)
        except Exception:
            skipped["score_failed"] += 1
            continue
        rows = _price_rows(local)
        rows_by_symbol[str(symbol)] = rows
        for idx in range(0, len(local) - 1):
            signal_date = str(local.at[idx, "date"])
            if signal_date < start or signal_date > end:
                continue
            score = float(local.at[idx, "tech_score"])
            if score <= ENTRY_THRESHOLD:
                continue
            entry_idx = idx + 1
            entry_row = rows[entry_idx]
            if _is_locked_limit_bar(entry_row):
                skipped["entry_locked"] += 1
                continue
            entry_atr = entry_row.atr14 or local.at[idx, "atr14"]
            if not entry_atr or float(entry_atr) <= 0:
                skipped["missing_atr"] += 1
                continue
            events.append(
                EntryEvent(
                    symbol=str(symbol),
                    name=names.get(str(symbol), str(symbol)),
                    signal_date=signal_date,
                    entry_index=entry_idx,
                    entry_date=entry_row.date,
                    entry_price=entry_row.open,
                    entry_atr=float(entry_atr),
                    regime=str(regime_by_date.get(signal_date, "unknown")),
                    tech_score=score,
                )
            )
    return events, rows_by_symbol, dict(skipped)


def _max_drawdown_from_levels(levels: list[float]) -> float:
    """Max drawdown (%) computed directly on a real equity *level* series.

    ``compare_paths._max_drawdown`` reconstructs a synthetic equity curve by
    compounding a list of *returns* as if each entry were one sequential,
    fully-capitalized period. That is only correct for a single position
    trading one-at-a-time. Feeding it a list built by averaging every trade
    that happened to close on the same calendar date across the *entire*
    universe (the bug this replaces) fabricates hundreds of fake compounding
    periods out of trades that were actually concurrent, not sequential —
    which is how the old code produced -98%/-99% "max_dd" on stop-loss-gated
    strategies.

    This function instead walks real portfolio equity values (produced by
    ``_simulate_portfolio``), so a drawdown below -100% is structurally
    impossible: equity is a sum of non-negative cash + non-negative reserved
    stakes and can never go negative.
    """
    if not levels:
        return 0.0
    peak = levels[0]
    mdd = 0.0
    for value in levels:
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = (value - peak) / peak
        mdd = min(mdd, drawdown)
    return round(mdd * 100, 2)


def _simulate_portfolio(
    outcomes: list[tuple[EntryEvent, ExitOutcome]],
    *,
    max_positions: int,
) -> dict[str, Any]:
    """Replay one variant's raw signal stream as a single capital-constrained portfolio.

    The raw ``outcomes`` list is every signal across the whole eligible
    universe with tech_score above threshold — far more concurrent entries
    than any real account could hold. This function is what turns that
    unconstrained signal stream into the actual backtested experience:

    - fixed starting capital = 1.0 (percent-of-capital units).
    - at most ``max_positions`` positions open at once; a signal is dropped
      ("skipped_position_cap") if the book is already full, and a symbol
      already held cannot be entered again (mirrors the test2 replay's
      ``held`` set convention).
    - each admitted trade is sized at ``current_total_equity / max_positions``
      at the moment it is admitted, so position sizing compounds with
      realized portfolio performance instead of staying pinned to the
      original starting capital forever.
    - within a day, candidates are prioritized by technical score (same
      ranking convention as the test2 replay's ``composite_for`` sort).
    - equity is marked every time a position closes, producing a real
      compounding equity curve suitable for ``_max_drawdown_from_levels``.
    """
    if not outcomes:
        return {
            "admitted_outcomes": [],
            "skipped_position_cap": 0,
            "net_return_pct": 0.0,
            "line_net_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }

    candidates = sorted(
        outcomes,
        key=lambda pair: (pair[0].entry_date, -pair[0].tech_score, pair[0].symbol),
    )

    cash = 1.0
    line_cash = 1.0
    # heap items: (exit_date, insertion_seq, net_return, line_net_return, stake, symbol)
    open_heap: list[tuple[str, int, float, float, float, str]] = []
    held_symbols: set[str] = set()
    equity_curve: list[float] = [1.0]
    admitted_outcomes: list[tuple[EntryEvent, ExitOutcome]] = []
    skipped_position_cap = 0
    seq = 0
    i = 0
    n = len(candidates)

    def current_equity() -> float:
        return cash + sum(item[4] for item in open_heap)

    while i < n or open_heap:
        next_entry_day = candidates[i][0].entry_date if i < n else None
        next_exit_day = open_heap[0][0] if open_heap else None
        if next_exit_day is not None and (next_entry_day is None or next_exit_day <= next_entry_day):
            exit_date, _, net_return, line_net_return, stake, symbol = heapq.heappop(open_heap)
            cash += stake * (1.0 + net_return)
            line_cash += stake * (1.0 + line_net_return)
            held_symbols.discard(symbol)
            equity_curve.append(current_equity())
            continue

        day = next_entry_day
        while i < n and candidates[i][0].entry_date == day:
            event, outcome = candidates[i]
            i += 1
            if len(open_heap) >= max_positions or event.symbol in held_symbols:
                skipped_position_cap += 1
                continue
            stake = current_equity() / max_positions
            cash -= stake
            seq += 1
            heapq.heappush(
                open_heap,
                (outcome.exit_date, seq, outcome.net_return, outcome.line_net_return, stake, event.symbol),
            )
            held_symbols.add(event.symbol)
            admitted_outcomes.append((event, outcome))

    return {
        "admitted_outcomes": admitted_outcomes,
        "skipped_position_cap": skipped_position_cap,
        "net_return_pct": round((cash - 1.0) * 100.0, 2),
        "line_net_return_pct": round((line_cash - 1.0) * 100.0, 2),
        "max_drawdown_pct": _max_drawdown_from_levels(equity_curve),
    }


def _metrics_for_outcomes(
    variant: ExitVariant,
    outcomes: list[tuple[EntryEvent, ExitOutcome]],
    *,
    max_positions: int,
) -> dict[str, Any]:
    portfolio = _simulate_portfolio(outcomes, max_positions=max_positions)
    admitted: list[tuple[EntryEvent, ExitOutcome]] = portfolio["admitted_outcomes"]
    reasons = Counter(_reason_bucket(outcome.reason) for _, outcome in admitted)
    trades = len(admitted)
    net_return_pct = portfolio["net_return_pct"]
    max_dd = portfolio["max_drawdown_pct"]
    line_net_return_pct = portfolio["line_net_return_pct"]
    ratio = net_return_pct / abs(max_dd) if max_dd < 0 else math.inf
    # Regime breakdown is a secondary diagnostic. It compounds each admitted
    # trade's own net_return sequentially within the regime bucket (the
    # `compare_paths` convention for a single-position trade list), which can
    # still mildly overstate compounding if positions overlap within a
    # regime — but bounded by max_positions concurrency, not by the whole
    # universe's daily exit density like the bug this replaces.
    regime: dict[str, Any] = {}
    for regime_name in ("up", "flat", "down", "unknown"):
        bucket = [(event, outcome) for event, outcome in admitted if event.regime == regime_name]
        if not bucket:
            continue
        bucket_returns = [outcome.net_return for _, outcome in bucket]
        bucket_total = _compound(bucket_returns)
        regime[regime_name] = {
            "trades": len(bucket),
            "net_return_pct": round((bucket_total - 1.0) * 100.0, 2),
            "max_drawdown_pct": _max_drawdown(bucket_returns),
            "avg_hold_days": round(statistics.mean(outcome.hold_days for _, outcome in bucket), 2),
        }
    return {
        "variant": asdict(variant) | {"key": variant.key, "label": variant.label},
        "signal_count": len(outcomes),
        "trades": trades,
        "skipped_position_cap": portfolio["skipped_position_cap"],
        "net_return_pct": net_return_pct,
        "line_net_return_pct": line_net_return_pct,
        "slippage_cost_pct": round(line_net_return_pct - net_return_pct, 2),
        "max_drawdown_pct": max_dd,
        "return_drawdown_ratio": round(ratio, 4) if math.isfinite(ratio) else None,
        "avg_hold_days": round(statistics.mean(outcome.hold_days for _, outcome in admitted), 2) if admitted else 0.0,
        "exit_reason_counts": dict(reasons),
        "exit_reason_pct": {key: round(value / trades * 100.0, 2) for key, value in reasons.items()} if trades else {},
        "drawdown_violation": abs(max_dd) > 20.0,
        "regime": regime,
    }


def _compound(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value
    return total


def _reason_bucket(reason: str) -> str:
    if "half_take_profit" in reason or reason.startswith("profit_drawdown"):
        return "take_profit"
    if "trailing" in reason:
        return "trailing"
    if "stop_loss" in reason:
        return "stop_loss"
    return reason


def run_large_sample_sweep(
    *,
    db_path: Path,
    start: str = START_DATE,
    end: str | None = None,
    include_holdout: bool = False,
    limit_symbols: int | None = None,
) -> dict[str, Any]:
    from paper_trading.test2_ab_models import DEFAULT_MAX_POSITIONS

    max_positions = DEFAULT_MAX_POSITIONS
    effective_end = resolve_effective_end(end, include_holdout=include_holdout)
    con = _connect_readonly(db_path)
    try:
        stocks = _eligible_symbols(con, min_days=MIN_TRADING_DAYS, limit_symbols=limit_symbols)
        prices = _load_price_frame(con, [row["symbol"] for row in stocks], end=effective_end)
    finally:
        con.close()
    if prices.empty:
        raise RuntimeError("no eligible prices for M58 exit sweep")

    names = {row["symbol"]: row["name"] for row in stocks}
    entries, rows_by_symbol, skipped = _build_entry_events(prices, start=start, end=effective_end, names=names)
    variants = iter_exit_variants()
    outcomes_by_variant: dict[str, list[tuple[EntryEvent, ExitOutcome]]] = {variant.key: [] for variant in variants}

    for event in entries:
        rows = rows_by_symbol[event.symbol]
        path = rows[event.entry_index:]
        if path:
            entry = path[0]
            path[0] = PriceRow(
                symbol=entry.symbol,
                date=entry.date,
                open=event.entry_price,
                high=entry.high,
                low=entry.low,
                close=entry.close,
                atr14=event.entry_atr,
            )
        for variant in variants:
            try:
                outcomes_by_variant[variant.key].append((event, simulate_exit(path, variant)))
            except ValueError:
                skipped["exit_missing_atr"] = skipped.get("exit_missing_atr", 0) + 1

    results = [
        _metrics_for_outcomes(variant, outcomes_by_variant[variant.key], max_positions=max_positions)
        for variant in variants
    ]
    results.sort(key=lambda row: (row["return_drawdown_ratio"] if row["return_drawdown_ratio"] is not None else -math.inf, row["net_return_pct"]), reverse=True)
    baseline_key = ExitVariant(CURRENT_TRAILING_ATR_MULT, "none").key
    return {
        "meta": {
            "schema_version": "m58_exit_sweep.v2",
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start": start,
            "requested_end": end,
            "effective_end": effective_end,
            "holdout_locked": True,
            "include_holdout": include_holdout,
            "min_trading_days": MIN_TRADING_DAYS,
            "max_positions": max_positions,
            "position_sizing": "current_total_equity / max_positions, resized at each admission (compounding)",
            "eligible_symbol_count": len(stocks),
            "evaluated_symbol_count": int(prices["symbol"].nunique()),
            "entry_threshold": ENTRY_THRESHOLD,
            "initial_atr_mult": INITIAL_ATR_MULT,
            "cost_round_trip": ROUND_TRIP_COST,
            "baseline_variant": baseline_key,
        },
        "trial_count": len(variants),
        "skipped": skipped,
        "entry_count": len(entries),
        "results": results,
    }


def run_test2_comparison(
    large_sample_report: dict[str, Any],
    *,
    db_path: Path,
    universe_path: Path,
    start: str = TEST2_START,
    end: str = TEST2_END,
    variants: list[ExitVariant] | None = None,
) -> dict[str, Any]:
    from paper_trading.test2_ab_data import load_prices, load_sectors, load_signals, load_universe
    from paper_trading.test2_ab_models import DEFAULT_MAX_POSITIONS, FRAMEWORKS
    from paper_trading.test2_ab_runner import _by_date, _next_fillable_date
    from paper_trading.test2_ab_stats import result_summary

    universe = load_universe(universe_path)
    sectors = load_sectors(universe_path)
    signals = load_signals(db_path, universe, start=start, end=end)
    prices = load_prices(db_path, universe, start=start, end=end)
    by_date = _by_date(signals)
    price_dates: dict[str, list[str]] = {}
    for symbol, price_date in prices:
        if symbol in universe:
            price_dates.setdefault(symbol, []).append(price_date)
    for dates in price_dates.values():
        dates.sort()

    baseline = ExitVariant(CURRENT_TRAILING_ATR_MULT, "none")
    if variants is not None:
        # Explicit grid requested by the caller (e.g. the full trailing x
        # profit-mode matrix) — always keep baseline present for reference.
        selected: list[ExitVariant] = list(dict.fromkeys([baseline, *variants]))
    else:
        ranked = large_sample_report["results"]
        selected = [baseline]
        for row in ranked:
            variant = ExitVariant(float(row["variant"]["trailing_atr_mult"]), row["variant"]["profit_mode"])
            if variant not in selected:
                selected.append(variant)
            if len(selected) >= 4:
                break

    results: dict[str, Any] = {}
    for variant in selected:
        replay_result = _replay_test2_with_variant(
            variant,
            by_date=by_date,
            prices=prices,
            price_dates=price_dates,
            universe=set(universe),
            sectors=sectors,
            max_positions=DEFAULT_MAX_POSITIONS,
        )
        arm_rows = {}
        for key, result in replay_result.items():
            arm_rows[key] = {
                "framework": result.framework.label,
                "summary": result_summary(result, prices),
                "closed_trades": [asdict(trade) for trade in result.closed_trades],
                "open_holdings": [asdict(holding) for holding in result.open_holdings],
            }
        results[variant.key] = {"variant": asdict(variant) | {"key": variant.key, "label": variant.label}, "arms": arm_rows}

    baseline_rows = results[baseline.key]["arms"]
    for key, payload in results.items():
        if key == baseline.key:
            payload["trade_differences_vs_baseline"] = []
            continue
        payload["trade_differences_vs_baseline"] = _trade_differences(baseline_rows, payload["arms"])

    return {
        "window": {"start": start, "end": end, "universe_count": len(universe)},
        "baseline_variant": baseline.key,
        "selected_variant_keys": [variant.key for variant in selected],
        "results": results,
    }


def _replay_test2_with_variant(
    variant: ExitVariant,
    *,
    by_date: dict[str, list[Any]],
    prices: dict[tuple[str, str], Any],
    price_dates: dict[str, list[str]],
    universe: set[str],
    sectors: dict[str, str],
    max_positions: int,
) -> dict[str, Any]:
    from paper_trading.test2_ab_models import FRAMEWORKS, MAX_PER_SECTOR, FrameworkResult, Holding, Trade, composite_for
    from paper_trading.test2_ab_runner import _next_fillable_date
    from paper_trading.test2_ab_stats import pct

    results = {key: FrameworkResult(framework=framework) for key, framework in FRAMEWORKS.items()}
    scheduled: dict[tuple[str, str, str, str], ExitOutcome | None] = {}

    def schedule(holding: Holding, framework_key: str) -> ExitOutcome | None:
        key = (framework_key, holding.symbol, holding.entry_signal_date, holding.entry_date)
        if key in scheduled:
            return scheduled[key]
        dates = [d for d in price_dates.get(holding.symbol, []) if d >= holding.entry_date]
        rows = []
        for d in dates:
            bar = prices.get((holding.symbol, d))
            if bar:
                rows.append(PriceRow(bar.symbol, bar.date, bar.open, bar.high, bar.low, bar.close, None))
        if not rows:
            scheduled[key] = None
            return None
        rows[0] = PriceRow(rows[0].symbol, rows[0].date, holding.entry_price, rows[0].high, rows[0].low, rows[0].close, None)
        # test2 Signal carries absolute stop/take but not ATR.  Recover the
        # current initial-stop ATR distance so the same exit function is used.
        if holding.stop_loss is None:
            scheduled[key] = None
            return None
        entry_atr = max((holding.entry_price - float(holding.stop_loss)) / INITIAL_ATR_MULT, 0.0001)
        rows[0] = PriceRow(rows[0].symbol, rows[0].date, rows[0].open, rows[0].high, rows[0].low, rows[0].close, entry_atr)
        outcome = simulate_exit(rows, variant)
        if outcome.reason == "end":
            scheduled[key] = None
            return None
        scheduled[key] = outcome
        return outcome

    for signal_date in sorted(by_date):
        price_date = signal_date[:10]
        day_signals = [signal for signal in by_date[signal_date] if signal.symbol in universe]
        for framework_key, result in results.items():
            still_open = []
            for holding in result.open_holdings:
                outcome = schedule(holding, framework_key)
                if outcome and outcome.exit_date <= price_date:
                    gross = pct(outcome.exit_price, holding.entry_price)
                    result.closed_trades.append(
                        Trade(
                            symbol=holding.symbol,
                            name=holding.name,
                            entry_signal_date=holding.entry_signal_date,
                            entry_date=holding.entry_date,
                            entry_price=holding.entry_price,
                            exit_date=outcome.exit_date,
                            exit_price=outcome.exit_price,
                            exit_reason=outcome.reason,
                            gross_return_pct=gross,
                            net_return_pct=round(gross - ROUND_TRIP_COST * 100.0, 2),
                        )
                    )
                else:
                    still_open.append(holding)
            result.open_holdings = still_open

            held = {holding.symbol for holding in result.open_holdings}
            sector_count: dict[str, int] = {}
            for holding in result.open_holdings:
                sec = sectors.get(holding.symbol, "unclassified")
                sector_count[sec] = sector_count.get(sec, 0) + 1
            framework = result.framework
            candidates = [
                signal
                for signal in day_signals
                if signal.symbol not in held and composite_for(signal, framework) > framework.entry_threshold
            ]
            candidates.sort(key=lambda item: composite_for(item, framework), reverse=True)
            for signal in candidates:
                if len(result.open_holdings) >= max_positions:
                    break
                sec = sectors.get(signal.symbol, "unclassified")
                if sector_count.get(sec, 0) >= MAX_PER_SECTOR:
                    continue
                entry_date = _next_fillable_date(signal.symbol, signal.date, price_dates, prices)
                if entry_date is None:
                    continue
                bar = prices.get((signal.symbol, entry_date))
                if bar is None:
                    continue
                holding = Holding(
                    symbol=signal.symbol,
                    name=signal.name,
                    entry_signal_date=signal.date,
                    entry_date=entry_date,
                    entry_price=bar.open,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )
                result.open_holdings.append(holding)
                held.add(signal.symbol)
                sector_count[sec] = sector_count.get(sec, 0) + 1
                result.daily_entries.setdefault(signal.date, []).append(signal.symbol)
    return results


def _trade_differences(baseline_arms: dict[str, Any], candidate_arms: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm_key, candidate in candidate_arms.items():
        baseline_trades = {
            (trade["symbol"], trade["entry_signal_date"], trade["entry_date"]): trade
            for trade in baseline_arms.get(arm_key, {}).get("closed_trades", [])
        }
        candidate_trades = {
            (trade["symbol"], trade["entry_signal_date"], trade["entry_date"]): trade
            for trade in candidate.get("closed_trades", [])
        }
        for key in sorted(set(baseline_trades) | set(candidate_trades)):
            base = baseline_trades.get(key)
            cand = candidate_trades.get(key)
            if base == cand:
                continue
            rows.append(
                {
                    "arm": arm_key,
                    "symbol": key[0],
                    "entry_signal_date": key[1],
                    "entry_date": key[2],
                    "baseline_exit": _exit_brief(base),
                    "candidate_exit": _exit_brief(cand),
                    "delta_net_pct": round((cand or {}).get("net_return_pct", 0.0) - (base or {}).get("net_return_pct", 0.0), 2),
                    "classification": _diff_class(base, cand),
                }
            )
    return rows


def _exit_brief(trade: dict[str, Any] | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "exit_date": trade["exit_date"],
        "exit_price": trade["exit_price"],
        "exit_reason": trade["exit_reason"],
        "net_return_pct": trade["net_return_pct"],
    }


def _diff_class(base: dict[str, Any] | None, cand: dict[str, Any] | None) -> str:
    if base is None:
        return "candidate_exited_extra"
    if cand is None:
        return "candidate_held_longer"
    if cand["exit_date"] > base["exit_date"]:
        return "candidate_held_longer"
    if cand["exit_date"] < base["exit_date"]:
        return "candidate_exited_earlier"
    return "same_date_different_price_or_reason"


def write_report(report: dict[str, Any], *, json_path: Path = OUTPUT_JSON, md_path: Path = OUTPUT_MD) -> tuple[Path, Path]:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M58 Exit Sweep Report",
        "",
        "## A. Large-Sample Exit Sweep",
        "",
        f"- window: {report['large_sample']['meta']['start']} ~ {report['large_sample']['meta']['effective_end']}",
        f"- holdout_locked: {report['large_sample']['meta']['holdout_locked']}",
        f"- eligible_symbol_count: {report['large_sample']['meta']['eligible_symbol_count']}",
        f"- entry_count: {report['large_sample']['entry_count']}",
        f"- trial_count: {report['large_sample']['trial_count']}",
        f"- max_positions: {report['large_sample']['meta'].get('max_positions')}",
        f"- position_sizing: {report['large_sample']['meta'].get('position_sizing')}",
        "",
        "| rank | variant | net_return | max_dd | ret/dd | trades | skip_cap | avg_hold | stop% | take% | trailing% | violation |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(report["large_sample"]["results"], 1):
        pct = row.get("exit_reason_pct", {})
        lines.append(
            f"| {idx} | {row['variant']['label']} | {row['net_return_pct']:+.2f}% | "
            f"{row['max_drawdown_pct']:+.2f}% | {row['return_drawdown_ratio']} | "
            f"{row['trades']} | {row.get('skipped_position_cap', 0)} | "
            f"{row['avg_hold_days']:.2f} | {pct.get('stop_loss', 0.0):.2f}% | "
            f"{pct.get('take_profit', 0.0):.2f}% | {pct.get('trailing', 0.0):.2f}% | "
            f"{'YES' if row['drawdown_violation'] else 'no'} |"
        )
    lines.extend(["", "## B. Test2 Replay Comparison", ""])
    test2 = report.get("test2_comparison", {})
    lines.append(f"- window: {test2.get('window', {}).get('start')} ~ {test2.get('window', {}).get('end')}")
    lines.append("")
    lines.append("| variant | arm | weighted_total_pct | closed | open |")
    lines.append("|---|---|---:|---:|---:|")
    for variant_key, payload in test2.get("results", {}).items():
        for arm_key, arm in payload["arms"].items():
            summary = arm["summary"]
            lines.append(
                f"| {variant_key} | {arm_key} | {summary['weighted_total_pct']:+.2f}% | "
                f"{summary['closed']} | {summary['open']} |"
            )
    lines.append("")
    lines.append("### Trade Differences")
    for variant_key, payload in test2.get("results", {}).items():
        diffs = payload.get("trade_differences_vs_baseline", [])
        if not diffs:
            continue
        lines.append("")
        lines.append(f"#### {variant_key}")
        lines.append("| arm | symbol | entry | baseline | candidate | delta_net | class |")
        lines.append("|---|---|---|---|---|---:|---|")
        for diff in diffs:
            lines.append(
                f"| {diff['arm']} | {diff['symbol']} | {diff['entry_date']} | "
                f"{diff['baseline_exit']} | {diff['candidate_exit']} | "
                f"{diff['delta_net_pct']:+.2f}% | {diff['classification']} |"
            )
    return "\n".join(lines) + "\n"


def build_report(
    *,
    db_path: Path,
    start: str,
    end: str | None,
    include_holdout: bool,
    limit_symbols: int | None,
    skip_test2: bool = False,
    test2_variants: list[ExitVariant] | None = None,
) -> dict[str, Any]:
    large = run_large_sample_sweep(
        db_path=db_path,
        start=start,
        end=end,
        include_holdout=include_holdout,
        limit_symbols=limit_symbols,
    )
    report: dict[str, Any] = {"large_sample": large}
    if not skip_test2:
        from paper_trading.test2_ab_data import DEFAULT_UNIVERSE

        report["test2_comparison"] = run_test2_comparison(
            large, db_path=db_path, universe_path=DEFAULT_UNIVERSE, variants=test2_variants
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M58 exit-parameter sweep")
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end")
    parser.add_argument("--include-holdout", action="store_true")
    parser.add_argument("--limit-symbols", type=int)
    parser.add_argument("--skip-test2", action="store_true")
    parser.add_argument(
        "--full-test2-grid",
        action="store_true",
        help="Replay all trailing_mult x {none, drawdown_10} variants (14 total) on test2, not just the top-3.",
    )
    parser.add_argument("--json-out", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--md-out", type=Path, default=OUTPUT_MD)
    args = parser.parse_args(argv)

    test2_variants = None
    if args.full_test2_grid:
        test2_variants = [ExitVariant(mult, mode) for mult in TRAILING_MULTS for mode in ("none", "drawdown_10")]

    report = build_report(
        db_path=args.db_path,
        start=args.start,
        end=args.end,
        include_holdout=args.include_holdout,
        limit_symbols=args.limit_symbols,
        skip_test2=args.skip_test2,
        test2_variants=test2_variants,
    )
    json_path, md_path = write_report(report, json_path=args.json_out, md_path=args.md_out)
    summary = {
        "json": str(json_path),
        "md": str(md_path),
        "trial_count": report["large_sample"]["trial_count"],
        "top5": report["large_sample"]["results"][:5],
        "test2": {
            key: {
                arm_key: arm["summary"]["weighted_total_pct"]
                for arm_key, arm in payload["arms"].items()
            }
            for key, payload in report.get("test2_comparison", {}).get("results", {}).items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
