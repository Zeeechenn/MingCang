"""Tracked deterministic replay core for test2-compatible shadow arms.

Personal universes, ledgers and reports remain under ``paper_trading/`` and
outside version control.  This module only holds the stable mechanical replay
contract so evaluation tools do not copy or mutate the private A/B state.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from backend.backtest.test2_models import (
    COMMISSION_ROUND_TRIP_PCT,
    DEFAULT_MAX_POSITIONS,
    MAX_PER_SECTOR,
    POSITION_PCT,
    SIGNAL_REVERSAL_MIN_HOLD_DAYS,
    SIGNAL_REVERSAL_THRESHOLD,
    Framework,
    FrameworkResult,
    Holding,
    PriceBar,
    Signal,
    Trade,
    composite_for,
)


def _by_date(signals: Iterable[Signal]) -> dict[str, list[Signal]]:
    grouped: dict[str, list[Signal]] = {}
    for signal in signals:
        grouped.setdefault(signal.date, []).append(signal)
    return grouped


def _next_fillable_date(
    symbol: str,
    signal_date: str,
    price_dates: dict[str, list[str]],
    prices: dict[tuple[str, str], PriceBar],
) -> str | None:
    """Return the first next-session open that is not a one-price locked bar."""
    for price_date in price_dates.get(symbol, []):
        if price_date <= signal_date[:10]:
            continue
        bar = prices.get((symbol, price_date))
        if bar is not None and not is_limit_locked(bar):
            return price_date
    return None


def is_limit_locked(bar: PriceBar) -> bool:
    return bar.high == bar.low


def pct(exit_price: float, entry_price: float) -> float:
    return round((exit_price - entry_price) / entry_price * 100.0, 2)


def latest_bar(symbol: str, prices: dict[tuple[str, str], PriceBar]) -> PriceBar | None:
    return max(
        (bar for (bar_symbol, _), bar in prices.items() if bar_symbol == symbol),
        key=lambda item: item.date,
        default=None,
    )


def _holding_days(holding: Holding, price_date: str) -> int:
    return (dt.date.fromisoformat(price_date) - dt.date.fromisoformat(holding.entry_date)).days


def _close_trade(holding: Holding, bar: PriceBar, reason: str, exit_price: float) -> Trade:
    gross = pct(exit_price, holding.entry_price)
    return Trade(
        symbol=holding.symbol,
        name=holding.name,
        entry_signal_date=holding.entry_signal_date,
        entry_date=holding.entry_date,
        entry_price=holding.entry_price,
        exit_date=bar.date,
        exit_price=exit_price,
        exit_reason=reason,
        gross_return_pct=gross,
        net_return_pct=round(gross - COMMISSION_ROUND_TRIP_PCT, 2),
    )


def _exit_reason(
    holding: Holding,
    bar: PriceBar,
    signal: Signal | None,
    framework: Framework,
) -> tuple[str, float] | None:
    if holding.stop_loss is not None and bar.low <= holding.stop_loss:
        return "stop_loss", float(holding.stop_loss)
    if holding.take_profit is not None and bar.high >= holding.take_profit:
        return "take_profit", float(holding.take_profit)
    if (
        signal is not None
        and _holding_days(holding, bar.date) >= SIGNAL_REVERSAL_MIN_HOLD_DAYS
        and composite_for(signal, framework) < SIGNAL_REVERSAL_THRESHOLD
    ):
        return "signal_reversal", bar.close
    return None


def replay(
    signals: list[Signal],
    prices: dict[tuple[str, str], PriceBar],
    universe: set[str],
    *,
    frameworks: dict[str, Framework],
    max_positions: int = DEFAULT_MAX_POSITIONS,
    sectors: dict[str, str] | None = None,
) -> dict[str, FrameworkResult]:
    """Replay close signals with next-fillable-open execution and test2 limits."""
    sectors = sectors or {}
    filtered = [signal for signal in signals if signal.symbol in universe]
    signals_by_date = _by_date(filtered)
    signals_by_symbol_date = {(item.symbol, item.date): item for item in filtered}
    price_dates: dict[str, list[str]] = {}
    for symbol, price_date in prices:
        if symbol in universe:
            price_dates.setdefault(symbol, []).append(price_date)
    for dates in price_dates.values():
        dates.sort()

    results = {
        key: FrameworkResult(framework=framework)
        for key, framework in frameworks.items()
    }
    for signal_date in sorted(signals_by_date):
        day_signals = signals_by_date[signal_date]
        price_date = signal_date[:10]
        for result in results.values():
            still_open: list[Holding] = []
            for holding in result.open_holdings:
                bar = prices.get((holding.symbol, price_date))
                signal = signals_by_symbol_date.get((holding.symbol, signal_date))
                exit_item = (
                    _exit_reason(holding, bar, signal, result.framework)
                    if bar is not None and bar.date >= holding.entry_date
                    else None
                )
                if exit_item is None:
                    still_open.append(holding)
                    continue
                assert bar is not None
                reason, exit_price = exit_item
                result.closed_trades.append(_close_trade(holding, bar, reason, exit_price))
            result.open_holdings = still_open

            held = {holding.symbol for holding in result.open_holdings}
            sector_count: dict[str, int] = {}
            for holding in result.open_holdings:
                sector = sectors.get(holding.symbol, "未分类")
                sector_count[sector] = sector_count.get(sector, 0) + 1
            candidates = [
                signal
                for signal in day_signals
                if signal.symbol not in held
                and composite_for(signal, result.framework) > result.framework.entry_threshold
            ]
            candidates.sort(
                key=lambda item: composite_for(item, result.framework),
                reverse=True,
            )
            for signal in candidates:
                if len(result.open_holdings) >= max_positions:
                    break
                sector = sectors.get(signal.symbol, "未分类")
                if sector_count.get(sector, 0) >= MAX_PER_SECTOR:
                    continue
                entry_date = _next_fillable_date(
                    signal.symbol,
                    signal.date,
                    price_dates,
                    prices,
                )
                if entry_date is None:
                    continue
                bar = prices.get((signal.symbol, entry_date))
                if bar is None:
                    continue
                result.open_holdings.append(
                    Holding(
                        symbol=signal.symbol,
                        name=signal.name,
                        entry_signal_date=signal.date,
                        entry_date=entry_date,
                        entry_price=bar.open,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                    )
                )
                held.add(signal.symbol)
                sector_count[sector] = sector_count.get(sector, 0) + 1
                result.daily_entries.setdefault(signal.date, []).append(signal.symbol)
    return results


def result_summary(
    result: FrameworkResult,
    prices: dict[tuple[str, str], PriceBar],
) -> dict[str, float | int]:
    realized = sum(trade.net_return_pct for trade in result.closed_trades)
    floating = 0.0
    for holding in result.open_holdings:
        latest = latest_bar(holding.symbol, prices)
        if latest is not None:
            floating += pct(latest.close, holding.entry_price)
    return {
        "closed": len(result.closed_trades),
        "open": len(result.open_holdings),
        "realized_net_pct": round(realized, 2),
        "floating_pct": round(floating, 2),
        "total_stock_pct": round(realized + floating, 2),
        "weighted_realized_pct": round(realized * POSITION_PCT, 2),
        "weighted_floating_pct": round(floating * POSITION_PCT, 2),
        "weighted_total_pct": round((realized + floating) * POSITION_PCT, 2),
    }


def holding_state(
    holding: Holding,
    prices: dict[tuple[str, str], PriceBar],
) -> dict[str, object]:
    latest = latest_bar(holding.symbol, prices)
    floating = pct(latest.close, holding.entry_price) if latest is not None else None
    return {
        **holding.__dict__,
        "latest_date": latest.date if latest is not None else None,
        "latest_close": latest.close if latest is not None else None,
        "floating_pct": floating,
        "weighted_floating_pct": (
            round(floating * POSITION_PCT, 2) if floating is not None else None
        ),
    }


def equal_weight_buy_hold(
    prices: dict[tuple[str, str], PriceBar],
    universe: set[str],
    start: str,
    end: str,
) -> dict[str, float | int]:
    per_symbol: dict[str, float] = {}
    for symbol in universe:
        bars = sorted(
            (
                bar
                for (bar_symbol, price_date), bar in prices.items()
                if bar_symbol == symbol and start <= price_date <= end
            ),
            key=lambda item: item.date,
        )
        entry = next((bar for bar in bars if not is_limit_locked(bar)), None)
        if entry is not None and bars:
            per_symbol[symbol] = pct(bars[-1].close, entry.open)
    return {
        "return_pct": (
            round(sum(per_symbol.values()) / len(per_symbol), 2)
            if per_symbol
            else 0.0
        ),
        "n": len(per_symbol),
    }
