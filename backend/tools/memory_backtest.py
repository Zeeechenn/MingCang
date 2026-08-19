"""Point-in-time A/B replay for outcome-backed stock memory.

This is a research evaluator, not production signal authority.  It compares the
unchanged test2 replay with a conservative memory veto that can only reject a
new entry when same-symbol, fully matured historical entry outcomes were weak.
It never lets a reconstructed outcome influence an earlier signal date.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from backend.backtest.signal_batch_selector import select_complete_signal_batches
from backend.backtest.test2_models import (
    FRAMEWORKS,
    POSITION_PCT,
    Framework,
    FrameworkResult,
    PriceBar,
    Signal,
    broad_sector,
    composite_for,
)
from backend.backtest.test2_replay import (
    equal_weight_buy_hold,
    latest_bar,
    pct,
    replay,
    result_summary,
)
from backend.config import default_sqlite_path
from backend.decision.signal_policy import is_entry_signal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test2_universe.json"
DEFAULT_OUTPUT = Path("/private/tmp/mingcang-memory-backtest.json")
BENCHMARK = "sh000300"
MIN_PRICE_COVERAGE = 0.80
MAX_MEMORY_SAMPLES = 200

GuardMode = Literal["dual_negative", "mean_negative", "hit_below_half"]


@dataclass(frozen=True)
class GuardSpec:
    key: str
    min_samples: int
    mode: GuardMode


@dataclass(frozen=True)
class OutcomeSample:
    symbol: str
    decision_date: str
    available_date: str
    excess_10d_pct: float
    judgment_id: int


@dataclass(frozen=True)
class Calibration:
    symbol: str
    as_of: str
    sample_count: int
    mean_excess_10d_pct: float | None
    hit_rate: float | None
    worst_excess_10d_pct: float | None


PRIMARY_GUARD = GuardSpec("dual_negative_n5", 5, "dual_negative")
SENSITIVITY_GUARDS = (
    GuardSpec("dual_negative_n3", 3, "dual_negative"),
    GuardSpec("dual_negative_n8", 8, "dual_negative"),
    GuardSpec("mean_negative_n5", 5, "mean_negative"),
    GuardSpec("hit_below_half_n5", 5, "hit_below_half"),
)


def calibration_as_of(
    samples: list[OutcomeSample],
    *,
    symbol: str,
    as_of: str,
) -> Calibration:
    """Build the same compact entry calibration using only already-known rows."""
    eligible = [sample for sample in samples if sample.symbol == symbol and sample.available_date < as_of]
    eligible.sort(key=lambda sample: (sample.available_date, sample.judgment_id), reverse=True)
    values = [sample.excess_10d_pct for sample in eligible[:MAX_MEMORY_SAMPLES]]
    return Calibration(
        symbol=symbol,
        as_of=as_of,
        sample_count=len(values),
        mean_excess_10d_pct=round(fmean(values), 4) if values else None,
        hit_rate=round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        worst_excess_10d_pct=round(min(values), 4) if values else None,
    )


def guard_blocks(calibration: Calibration, spec: GuardSpec = PRIMARY_GUARD) -> bool:
    """Apply a predeclared downside-only memory guard; positive memory never forces entry."""
    if calibration.sample_count < spec.min_samples:
        return False
    mean_negative = bool(
        calibration.mean_excess_10d_pct is not None
        and calibration.mean_excess_10d_pct < 0
    )
    hit_below_half = bool(calibration.hit_rate is not None and calibration.hit_rate < 0.5)
    if spec.mode == "dual_negative":
        return mean_negative and hit_below_half
    if spec.mode == "mean_negative":
        return mean_negative
    return hit_below_half


class MemoryGuard:
    def __init__(self, samples: list[OutcomeSample], spec: GuardSpec) -> None:
        self.samples = samples
        self.spec = spec
        self.decisions: dict[tuple[str, str], dict[str, Any]] = {}

    def __call__(self, signal: Signal, framework: Framework) -> bool:
        calibration = calibration_as_of(
            self.samples,
            symbol=signal.symbol,
            as_of=signal.date[:10],
        )
        blocked = guard_blocks(calibration, self.spec)
        self.decisions[(signal.symbol, signal.date[:10])] = {
            **asdict(calibration),
            "guard": self.spec.key,
            "blocked": blocked,
            "composite_score": composite_for(signal, framework),
        }
        return not blocked


def _connect_ro(db_path: str | Path) -> sqlite3.Connection:
    resolved = Path(db_path).resolve()
    con = sqlite3.connect(f"file:{resolved}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_universe(path: str | Path) -> tuple[dict[str, str], dict[str, str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    sectors: dict[str, str] = {}
    for item in payload.get("stocks", []):
        symbol = str(item["symbol"])
        names[symbol] = str(item.get("name") or symbol)
        sectors[symbol] = broad_sector(str(item.get("sector") or ""))
    if not names:
        raise ValueError("universe is empty")
    return names, sectors


def _placeholders(values: dict[str, str]) -> str:
    return ",".join("?" for _ in values)


def _close_confirmed_end(
    con: sqlite3.Connection,
    universe: dict[str, str],
    requested_end: str,
) -> tuple[str, dict[str, Any]]:
    required = max(1, math.ceil(len(universe) * MIN_PRICE_COVERAGE))
    row = con.execute(
        f"""
        SELECT date, COUNT(DISTINCT symbol) AS covered
        FROM prices
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND date <= ?
        GROUP BY date
        HAVING COUNT(DISTINCT symbol) >= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (*universe.keys(), requested_end, required),
    ).fetchone()
    if row is None:
        raise ValueError("no close-confirmed date met the universe coverage gate")
    return str(row["date"]), {
        "requested_end": requested_end,
        "selected_end": str(row["date"]),
        "covered_symbols": int(row["covered"]),
        "required_symbols": required,
        "universe_size": len(universe),
        "minimum_ratio": MIN_PRICE_COVERAGE,
    }


def _load_prices(
    con: sqlite3.Connection,
    universe: dict[str, str],
    start: str,
    end: str,
) -> dict[tuple[str, str], PriceBar]:
    rows = con.execute(
        f"""
        SELECT symbol, date, open, high, low, close
        FROM prices
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND date BETWEEN ? AND ?
        ORDER BY date, symbol
        """,
        (*universe.keys(), start, end),
    ).fetchall()
    return {
        (str(row["symbol"]), str(row["date"])): PriceBar(
            symbol=str(row["symbol"]),
            date=str(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
        if all(row[key] is not None for key in ("open", "high", "low", "close"))
    }


def _load_canonical_signals(
    con: sqlite3.Connection,
    universe: dict[str, str],
    start: str,
    end: str,
) -> tuple[list[Signal], dict[str, int]]:
    selector = select_complete_signal_batches(
        con,
        universe_symbols=set(universe),
        start=start,
        end=end,
    )
    selected_pairs = {
        (str(item["signal_date"]), str(item["batch_key"]))
        for item in selector["selected_batches"]
    }
    if not selected_pairs:
        return [], {key: value for key, value in selector.items() if key != "selected_batches"}
    params = (*universe.keys(), start, end)
    rows = con.execute(
        f"""
        SELECT id, symbol, date AS batch_key,
               substr(COALESCE(data_timestamp, date), 1, 10) AS signal_date,
               quant_score, technical_score, sentiment_score,
               stop_loss, take_profit
        FROM signals
        WHERE COALESCE(market, 'CN') = 'CN'
          AND symbol IN ({_placeholders(universe)})
          AND substr(COALESCE(data_timestamp, date), 1, 10) BETWEEN ? AND ?
        ORDER BY signal_date, symbol, id DESC
        """,
        params,
    ).fetchall()
    latest_by_symbol_day: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        pair = (str(row["signal_date"]), str(row["batch_key"]))
        if pair not in selected_pairs:
            continue
        key = (str(row["symbol"]), str(row["signal_date"]))
        latest_by_symbol_day.setdefault(key, row)
    signals = [
        Signal(
            symbol=str(row["symbol"]),
            name=universe[str(row["symbol"])],
            date=str(row["signal_date"]),
            quant=float(row["quant_score"] or 0.0),
            tech=float(row["technical_score"] or 0.0),
            sent=float(row["sentiment_score"] or 0.0),
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
        )
        for row in sorted(latest_by_symbol_day.values(), key=lambda item: (item["signal_date"], item["symbol"]))
    ]
    return signals, {
        **{key: value for key, value in selector.items() if key != "selected_batches"},
        "canonical_symbol_days": len(signals),
    }


def _load_entry_outcome_samples(
    con: sqlite3.Connection,
    universe: dict[str, str],
    prices: dict[tuple[str, str], PriceBar],
    end: str,
) -> tuple[list[OutcomeSample], dict[str, Any]]:
    rows = con.execute(
        f"""
        SELECT id, symbol, evidence_json, created_at
        FROM stock_memory_items
        WHERE memory_type = 'judgment'
          AND symbol IN ({_placeholders(universe)})
        ORDER BY id DESC
        """,
        tuple(universe.keys()),
    ).fetchall()
    benchmark_rows = con.execute(
        """
        SELECT date, close FROM index_prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date
        """,
        (BENCHMARK, end),
    ).fetchall()
    benchmark = {
        str(row["date"]): float(row["close"])
        for row in benchmark_rows
        if row["close"] is not None
    }
    bars_by_symbol: dict[str, list[PriceBar]] = defaultdict(list)
    for (symbol, _), bar in prices.items():
        bars_by_symbol[symbol].append(bar)
    for bars in bars_by_symbol.values():
        bars.sort(key=lambda bar: bar.date)

    seen: set[tuple[str, str]] = set()
    samples: list[OutcomeSample] = []
    entry_rows = 0
    skipped: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        try:
            evidence = json.loads(row["evidence_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            skipped["invalid_json"] += 1
            continue
        recommendation = str(evidence.get("recommendation") or "")
        if not is_entry_signal(recommendation, include_legacy=True):
            continue
        entry_rows += 1
        symbol = str(row["symbol"])
        decision_date = str(evidence.get("date") or "")[:10]
        observation_key = (symbol, decision_date)
        if len(decision_date) != 10:
            skipped["invalid_date"] += 1
            continue
        if observation_key in seen:
            skipped["duplicate_symbol_day"] += 1
            continue
        seen.add(observation_key)
        bars = bars_by_symbol.get(symbol, [])
        base_index = next(
            (index for index, bar in enumerate(bars) if bar.date == decision_date),
            None,
        )
        if base_index is None or base_index + 10 >= len(bars):
            skipped["incomplete_10d"] += 1
            continue
        base_bar = bars[base_index]
        target_bar = bars[base_index + 10]
        benchmark_base = benchmark.get(base_bar.date)
        benchmark_target = benchmark.get(target_bar.date)
        if not benchmark_base or benchmark_target is None or not base_bar.close:
            skipped["missing_benchmark"] += 1
            continue
        stock_return = (target_bar.close / base_bar.close - 1.0) * 100.0
        benchmark_return = (benchmark_target / benchmark_base - 1.0) * 100.0
        created_date = str(row["created_at"] or decision_date)[:10]
        available_date = max(target_bar.date, created_date)
        samples.append(OutcomeSample(
            symbol=symbol,
            decision_date=decision_date,
            available_date=available_date,
            excess_10d_pct=round(stock_return - benchmark_return, 4),
            judgment_id=int(row["id"]),
        ))
    samples.sort(key=lambda sample: (sample.available_date, sample.symbol, sample.judgment_id))
    return samples, {
        "raw_entry_judgment_rows": entry_rows,
        "unique_entry_symbol_days": len(seen),
        "reconstructed_complete_samples": len(samples),
        "first_available_date": min((sample.available_date for sample in samples), default=None),
        "last_available_date": max((sample.available_date for sample in samples), default=None),
        "skipped": dict(skipped),
    }


def _max_drawdown_pct(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
    *,
    start: str,
    end: str,
) -> float:
    dates = sorted({date for _, date in prices if start <= date <= end})
    peak = 100.0
    worst = 0.0
    all_closed = result.closed_trades
    for date in dates:
        contribution = sum(
            trade.net_return_pct * POSITION_PCT
            for trade in all_closed
            if trade.exit_date <= date
        )
        for trade in all_closed:
            if not (trade.entry_date <= date < trade.exit_date):
                continue
            bar = prices.get((trade.symbol, date))
            if bar is not None:
                contribution += pct(bar.close, trade.entry_price) * POSITION_PCT
        for holding in result.open_holdings:
            if holding.entry_date > date:
                continue
            bar = prices.get((holding.symbol, date))
            if bar is not None:
                contribution += pct(bar.close, holding.entry_price) * POSITION_PCT
        level = 100.0 + contribution
        peak = max(peak, level)
        if peak:
            worst = min(worst, (level / peak - 1.0) * 100.0)
    return round(worst, 2)


def _trade_metrics(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    closed_returns = [trade.net_return_pct for trade in result.closed_trades]
    stop_trades = [trade for trade in result.closed_trades if trade.exit_reason == "stop_loss"]
    contributions: defaultdict[str, float] = defaultdict(float)
    for trade in result.closed_trades:
        contributions[trade.symbol] += trade.net_return_pct * POSITION_PCT
    for holding in result.open_holdings:
        bar = latest_bar(holding.symbol, prices)
        if bar is not None:
            contributions[holding.symbol] += pct(bar.close, holding.entry_price) * POSITION_PCT
    absolute_total = sum(abs(value) for value in contributions.values())
    largest = max(contributions.items(), key=lambda item: abs(item[1]), default=(None, 0.0))
    return {
        "closed_trades": len(closed_returns),
        "open_trades": len(result.open_holdings),
        "closed_win_rate": (
            round(sum(value > 0 for value in closed_returns) / len(closed_returns), 4)
            if closed_returns else None
        ),
        "average_closed_net_pct": round(fmean(closed_returns), 2) if closed_returns else None,
        "stop_loss_count": len(stop_trades),
        "stop_loss_rate_of_closed": (
            round(len(stop_trades) / len(closed_returns), 4) if closed_returns else None
        ),
        "max_drawdown_pct": _max_drawdown_pct(result, prices, start=start, end=end),
        "largest_symbol_contribution": {
            "symbol": largest[0],
            "weighted_contribution_pct": round(largest[1], 2) if largest[0] else None,
            "absolute_share_pct": (
                round(abs(largest[1]) / absolute_total * 100.0, 2)
                if largest[0] and absolute_total else None
            ),
        },
    }


def _entry_pairs(result: FrameworkResult) -> set[tuple[str, str]]:
    return {
        (symbol, signal_date[:10])
        for signal_date, symbols in result.daily_entries.items()
        for symbol in symbols
    }


def _entry_outcome(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
    pair: tuple[str, str],
) -> dict[str, Any] | None:
    symbol, signal_date = pair
    trade = next(
        (
            item for item in result.closed_trades
            if item.symbol == symbol and item.entry_signal_date[:10] == signal_date
        ),
        None,
    )
    if trade is not None:
        return {
            "symbol": symbol,
            "signal_date": signal_date,
            "status": "closed",
            "exit_reason": trade.exit_reason,
            "net_return_pct": trade.net_return_pct,
            "weighted_contribution_pct": round(trade.net_return_pct * POSITION_PCT, 2),
        }
    holding = next(
        (
            item for item in result.open_holdings
            if item.symbol == symbol and item.entry_signal_date[:10] == signal_date
        ),
        None,
    )
    if holding is None:
        return None
    bar = latest_bar(symbol, prices)
    if bar is None:
        return None
    value = pct(bar.close, holding.entry_price)
    return {
        "symbol": symbol,
        "signal_date": signal_date,
        "status": "open",
        "exit_reason": None,
        "net_return_pct": value,
        "weighted_contribution_pct": round(value * POSITION_PCT, 2),
    }


def _compare_results(
    baseline: FrameworkResult,
    memory: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
    decisions: dict[tuple[str, str], dict[str, Any]],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    baseline_summary = result_summary(baseline, prices)
    memory_summary = result_summary(memory, prices)
    baseline_metrics = _trade_metrics(baseline, prices, start=start, end=end)
    memory_metrics = _trade_metrics(memory, prices, start=start, end=end)
    baseline_entries = _entry_pairs(baseline)
    memory_entries = _entry_pairs(memory)
    removed_pairs = sorted(baseline_entries - memory_entries)
    added_pairs = sorted(memory_entries - baseline_entries)
    removed = [
        {**(outcome or {}), "memory": decisions.get(pair)}
        for pair in removed_pairs
        if (outcome := _entry_outcome(baseline, prices, pair)) is not None
    ]
    directly_vetoed = [
        item
        for item in removed
        if isinstance(item.get("memory"), dict) and item["memory"].get("blocked") is True
    ]
    path_displaced = [item for item in removed if item not in directly_vetoed]
    added = [
        outcome
        for pair in added_pairs
        if (outcome := _entry_outcome(memory, prices, pair)) is not None
    ]
    return {
        "baseline": {"summary": baseline_summary, "metrics": baseline_metrics},
        "memory": {"summary": memory_summary, "metrics": memory_metrics},
        "delta": {
            "weighted_total_pct_points": round(
                float(memory_summary["weighted_total_pct"])
                - float(baseline_summary["weighted_total_pct"]),
                2,
            ),
            "max_drawdown_pct_points": round(
                float(memory_metrics["max_drawdown_pct"])
                - float(baseline_metrics["max_drawdown_pct"]),
                2,
            ),
            "stop_loss_count": int(memory_metrics["stop_loss_count"])
            - int(baseline_metrics["stop_loss_count"]),
            "closed_win_rate_points": (
                round(
                    (float(memory_metrics["closed_win_rate"]) - float(baseline_metrics["closed_win_rate"])) * 100,
                    2,
                )
                if memory_metrics["closed_win_rate"] is not None
                and baseline_metrics["closed_win_rate"] is not None
                else None
            ),
        },
        "entry_attribution": {
            "removed_count": len(removed),
            "direct_memory_veto_count": len(directly_vetoed),
            "path_displaced_count": len(path_displaced),
            "added_substitute_count": len(added),
            "direct_veto_saved_stop_losses": sum(
                item.get("exit_reason") == "stop_loss" for item in directly_vetoed
            ),
            "direct_veto_missed_positive_outcomes": sum(
                float(item.get("net_return_pct", 0)) > 0 for item in directly_vetoed
            ),
            "directly_vetoed_entries": directly_vetoed,
            "path_displaced_entries": path_displaced,
            "added_substitute_entries": added,
        },
    }


def build_report(
    *,
    db_path: str | Path,
    universe_path: str | Path = DEFAULT_UNIVERSE,
    start: str = "2026-06-08",
    requested_end: str = "9999-12-31",
) -> dict[str, Any]:
    universe, sectors = _load_universe(universe_path)
    with _connect_ro(db_path) as con:
        end, close_gate = _close_confirmed_end(con, universe, requested_end)
        if start > end:
            raise ValueError(f"start {start} is after close-confirmed end {end}")
        earliest_judgment = con.execute(
            """
            SELECT MIN(substr(json_extract(evidence_json, '$.date'), 1, 10))
            FROM stock_memory_items WHERE memory_type = 'judgment'
            """
        ).fetchone()[0]
        memory_start = str(earliest_judgment or start)
        prices = _load_prices(con, universe, min(memory_start, start), end)
        signals, signal_health = _load_canonical_signals(con, universe, start, end)
        samples, sample_health = _load_entry_outcome_samples(con, universe, prices, end)
        last_signal_date = max((signal.date for signal in signals), default=None)
        actual_outcomes = con.execute(
            """
            SELECT COUNT(*) AS n,
                   MIN(substr(created_at, 1, 10)) AS first_created,
                   SUM(
                       CASE WHEN substr(created_at, 1, 10) < :last_signal_date
                            THEN 1 ELSE 0 END
                   ) AS available_before_last_signal
            FROM stock_memory_items
            WHERE memory_type = 'outcome' AND status = 'validated'
              AND substr(created_at, 1, 10) <= :end
            """,
            {"end": end, "last_signal_date": last_signal_date or start},
        ).fetchone()

    universe_symbols = set(universe)
    guard_specs = (PRIMARY_GUARD, *SENSITIVITY_GUARDS)
    framework_reports: dict[str, Any] = {}
    for framework_key, framework in FRAMEWORKS.items():
        baseline = replay(
            signals,
            prices,
            universe_symbols,
            frameworks={framework_key: framework},
            sectors=sectors,
            process_all_price_dates=True,
        )[framework_key]
        guard_reports: dict[str, Any] = {}
        for spec in guard_specs:
            guard = MemoryGuard(samples, spec)
            memory = replay(
                signals,
                prices,
                universe_symbols,
                frameworks={framework_key: framework},
                sectors=sectors,
                entry_filter=guard,
                process_all_price_dates=True,
            )[framework_key]
            guard_reports[spec.key] = _compare_results(
                baseline,
                memory,
                prices,
                guard.decisions,
                start=start,
                end=end,
            )
        framework_reports[framework_key] = {
            "label": framework.label,
            "guards": guard_reports,
        }

    return {
        "schema_version": "memory-point-in-time-ab.v1",
        "research_only": True,
        "scope": {
            "db_path": str(Path(db_path).resolve()),
            "universe_path": str(Path(universe_path).resolve()),
            "start": start,
            "end": end,
            "position_pct": POSITION_PCT,
            "close_gate": close_gate,
        },
        "operational_truth": {
            "validated_outcomes_actually_available_by_end": int(actual_outcomes["n"]),
            "first_actual_outcome_created": actual_outcomes["first_created"],
            "last_evaluated_signal_date": last_signal_date,
            "validated_outcomes_created_before_last_signal": int(
                actual_outcomes["available_before_last_signal"] or 0
            ),
            "as_operated_memory_effect": (
                "none"
                if int(actual_outcomes["available_before_last_signal"] or 0) == 0
                else "possible_not_replayed_by_counterfactual_arm"
            ),
            "same_day_availability_policy": (
                "outcomes created on the same calendar day as a signal are not assumed available"
            ),
            "counterfactual_arm": (
                "assumes the repaired daily outcome loop had run historically; "
                "each sample becomes usable only after its 10th later trading session"
            ),
        },
        "data_health": {
            "signals": signal_health,
            "memory_samples": sample_health,
        },
        "leakage_controls": [
            "latest signal rerun canonicalized once per symbol-day",
            "memory judgments canonicalized once per symbol-day",
            "10-session outcome must mature strictly before the evaluated signal date",
            "positive memory never creates an entry; the overlay can only veto",
            "stops and take-profits remain the original persisted signal values",
            "stops are evaluated on every available trading session",
        ],
        "primary_guard": asdict(PRIMARY_GUARD),
        "same_pool_equal_weight_buy_hold": equal_weight_buy_hold(
            prices,
            set(universe),
            start,
            end,
        ),
        "frameworks": framework_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time memory A/B replay")
    parser.add_argument("--db", type=Path, default=default_sqlite_path())
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--start", default="2026-06-08")
    parser.add_argument("--end", default="9999-12-31")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    report = build_report(
        db_path=args.db,
        universe_path=args.universe,
        start=args.start,
        requested_end=args.end,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "output": str(args.output.resolve()),
        "window": report["scope"],
        "operational_truth": report["operational_truth"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
