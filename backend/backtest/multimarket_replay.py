"""Close-confirmed, next-open M67 gray replay for CN/HK/US comparisons."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from math import prod

import pandas as pd

from backend.data.market_profiles import get_market_profile, normalize_market


@dataclass(frozen=True)
class ReplayRule:
    market: str
    momentum_lookback: int
    entry_momentum: float
    max_hold_bars: int
    require_volume_confirmation: bool
    version: str


_RULES = {
    "CN": ReplayRule("CN", 20, 0.03, 20, False, "cn-m67-replay-v1"),
    "HK": ReplayRule("HK", 20, 0.04, 15, True, "hk-m67-replay-v1"),
    "US": ReplayRule("US", 20, 0.05, 10, False, "us-m67-replay-v1"),
}


def replay_rule(market: str) -> ReplayRule:
    return _RULES[normalize_market(market)]


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 1.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return round(worst * 100, 2)


def _round_trip_rate(market: str, entry_price: float, shares: float = 100.0) -> float:
    notional = max(entry_price * shares, 1.0)
    estimated = get_market_profile(market).costs.estimate_round_trip(
        notional=notional,
        shares=shares,
    )
    return float(estimated["rate"])


def replay_frame(frame: pd.DataFrame, *, market: str) -> dict:
    """Replay a versioned market rule with signals at close and fills next open."""
    market = normalize_market(market)
    rule = replay_rule(market)
    df = frame.sort_index().copy()
    required = {"open", "close", "volume"}
    if len(df) < 80 or not required.issubset(df.columns):
        return {"status": "insufficient_data", "rows": len(df), "market": market, "rule": asdict(rule)}
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["momentum"] = df["close"] / df["close"].shift(rule.momentum_lookback) - 1
    df["volume_ratio"] = df["volume"] / df["volume"].rolling(20).mean()

    trade_returns: list[float] = []
    equity = [1.0]
    entry_price: float | None = None
    entry_index: int | None = None
    entry_date: str | None = None
    trades: list[dict] = []

    for index in range(60, len(df) - 1):
        row = df.iloc[index]
        next_row = df.iloc[index + 1]
        if entry_price is None:
            volume_ok = not rule.require_volume_confirmation or float(row["volume_ratio"] or 0) >= 1.0
            should_enter = bool(
                row["close"] > row["ma20"] > row["ma60"]
                and row["momentum"] >= rule.entry_momentum
                and volume_ok
            )
            if should_enter and float(next_row["open"] or 0) > 0:
                entry_price = float(next_row["open"])
                entry_index = index + 1
                entry_date = str(df.index[index + 1])
            continue

        held = index - int(entry_index or index)
        if market == "US":
            should_exit = bool(row["close"] < row["ma20"] or row["momentum"] < 0 or held >= rule.max_hold_bars)
        elif market == "HK":
            should_exit = bool(row["close"] < row["ma20"] or held >= rule.max_hold_bars)
        else:
            should_exit = bool(row["close"] <= row["ma20"] or held >= rule.max_hold_bars)
        exit_price = float(next_row["open"] or 0)
        if should_exit and exit_price > 0:
            cost_rate = _round_trip_rate(market, entry_price)
            net_return = exit_price / entry_price - 1 - cost_rate
            trade_returns.append(net_return)
            equity.append(equity[-1] * (1 + net_return))
            trades.append({
                "entry_date": entry_date,
                "exit_date": str(df.index[index + 1]),
                "entry": round(entry_price, 4),
                "exit": round(exit_price, 4),
                "net_return_pct": round(net_return * 100, 2),
                "cost_rate_pct": round(cost_rate * 100, 4),
                "held_bars": held,
            })
            entry_price = None
            entry_index = None
            entry_date = None

    if entry_price is not None:
        exit_price = float(df.iloc[-1]["close"])
        cost_rate = _round_trip_rate(market, entry_price)
        net_return = exit_price / entry_price - 1 - cost_rate
        trade_returns.append(net_return)
        equity.append(equity[-1] * (1 + net_return))
        trades.append({
            "entry_date": entry_date,
            "exit_date": str(df.index[-1]),
            "entry": round(entry_price, 4),
            "exit": round(exit_price, 4),
            "net_return_pct": round(net_return * 100, 2),
            "cost_rate_pct": round(cost_rate * 100, 4),
            "held_bars": len(df) - 1 - int(entry_index or len(df) - 1),
        })

    baseline_entry = float(df.iloc[60]["open"])
    baseline_exit = float(df.iloc[-1]["close"])
    baseline_cost = _round_trip_rate(market, baseline_entry)
    baseline_return = baseline_exit / baseline_entry - 1 - baseline_cost
    strategy_return = prod(1 + value for value in trade_returns) - 1 if trade_returns else 0.0
    return {
        "status": "ok",
        "market": market,
        "rows": len(df),
        "first_date": str(df.index[0]),
        "last_date": str(df.index[-1]),
        "rule": asdict(rule),
        "cost_model_version": get_market_profile(market).costs.version,
        "trades": len(trades),
        "win_rate_pct": round(sum(value > 0 for value in trade_returns) / len(trade_returns) * 100, 2) if trade_returns else None,
        "strategy_return_pct": round(strategy_return * 100, 2),
        "buy_hold_return_pct": round(baseline_return * 100, 2),
        "excess_vs_buy_hold_pct": round((strategy_return - baseline_return) * 100, 2),
        "max_drawdown_pct": _max_drawdown(equity),
        "trade_log": trades,
    }


def run_market_replay(db, asset_keys: list[str], *, as_of: str | None = None) -> dict:
    """Run equal-weight same-pool replay using only rows at or before as_of."""
    from backend.data.database import Price, Stock

    cutoff = as_of or date.today().isoformat()
    results: list[dict] = []
    for key in asset_keys:
        stock = db.query(Stock).filter(Stock.asset_key == key).first()
        if stock is None:
            results.append({"asset_key": key, "status": "stock_not_found"})
            continue
        rows = (
            db.query(Price)
            .filter(Price.asset_key == key, Price.date <= cutoff)
            .order_by(Price.date.asc())
            .all()
        )
        frame = pd.DataFrame([{
            "date": row.date,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        } for row in rows])
        if not frame.empty:
            frame = frame.set_index("date")
        result = replay_frame(frame, market=stock.market)
        result.update({"asset_key": key, "symbol": stock.symbol, "name": stock.name})
        results.append(result)

    ok = [row for row in results if row.get("status") == "ok"]
    strategy_values = [float(row["strategy_return_pct"]) for row in ok]
    baseline_values = [float(row["buy_hold_return_pct"]) for row in ok]
    absolute_contributions = [abs(value) for value in strategy_values]
    total_absolute = sum(absolute_contributions)
    return {
        "as_of": cutoff,
        "universe": asset_keys,
        "same_pool_equal_weight": True,
        "symbols_ok": len(ok),
        "symbols_total": len(asset_keys),
        "strategy_equal_weight_return_pct": round(sum(strategy_values) / len(strategy_values), 2) if ok else None,
        "buy_hold_equal_weight_return_pct": round(sum(baseline_values) / len(baseline_values), 2) if ok else None,
        "max_single_stock_contribution_pct": round(max(absolute_contributions) / total_absolute * 100, 2) if total_absolute else 0.0,
        "results": results,
    }
