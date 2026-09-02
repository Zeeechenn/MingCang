"""Deterministic portfolio-NAV replay for independent P0-R evidence.

This module does not replace the existing test2 percentage-sum replay. It adds
an isolated cash account, lot-sized fills, next-session execution, T+1 exits,
conservative daily-bar stop matching, and auditable transaction costs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SignalIntent:
    symbol: str
    date: str
    score: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class ReplayCostModel:
    commission_buy: float
    commission_sell: float
    tax_buy: float
    tax_sell: float
    regulatory_buy: float
    regulatory_sell: float
    slippage_buy: float
    slippage_sell: float
    minimum_commission: float = 5.0
    version: str = "p0r-cn-v1"

    @classmethod
    def for_market(cls, market: str = "CN") -> ReplayCostModel:
        from backend.data.market_profiles import get_market_profile

        profile = get_market_profile(market)
        costs = profile.costs
        return cls(
            commission_buy=costs.commission_buy,
            commission_sell=costs.commission_sell,
            tax_buy=costs.tax_buy,
            tax_sell=costs.tax_sell,
            regulatory_buy=costs.regulatory_buy,
            regulatory_sell=costs.regulatory_sell,
            slippage_buy=costs.slippage_buy,
            slippage_sell=costs.slippage_sell,
            minimum_commission=5.0 if profile.market == "CN" else 0.0,
            version=f"p0r-{costs.version}",
        )

    def fees(self, side: str, notional: float) -> dict[str, float]:
        commission_rate = self.commission_buy if side == "buy" else self.commission_sell
        tax_rate = self.tax_buy if side == "buy" else self.tax_sell
        regulatory_rate = self.regulatory_buy if side == "buy" else self.regulatory_sell
        commission = notional * commission_rate
        if commission_rate > 0:
            commission = max(commission, self.minimum_commission)
        tax = notional * tax_rate
        regulatory = notional * regulatory_rate
        return {
            "commission": commission,
            "tax": tax,
            "regulatory": regulatory,
            "total": commission + tax + regulatory,
        }


@dataclass(frozen=True)
class ReplayConfig:
    initial_cash: float = 1_000_000.0
    entry_threshold: float = 25.0
    reversal_threshold: float = -15.0
    reversal_min_hold_sessions: int = 2
    target_position_weight: float = 0.15
    max_sector_weight: float = 0.30
    max_total_weight: float = 0.80
    max_positions: int = 3
    lot_size: int = 100
    entry_ttl_sessions: int = 1


@dataclass
class _PendingEntry:
    signal: SignalIntent
    waited_sessions: int = 0


@dataclass
class _Position:
    symbol: str
    sector: str
    shares: int
    entry_signal_date: str
    entry_date: str
    entry_reference_price: float
    entry_price: float
    entry_notional: float
    entry_fees: float
    stop_loss: float | None
    take_profit: float | None
    held_sessions: int = 0


def _validate_bar(bar: DailyBar) -> None:
    values = (bar.open, bar.high, bar.low, bar.close)
    if min(values) <= 0:
        raise ValueError(f"{bar.symbol} {bar.date}: OHLC must be positive")
    if bar.high < max(bar.open, bar.low, bar.close):
        raise ValueError(f"{bar.symbol} {bar.date}: high is invalid")
    if bar.low > min(bar.open, bar.high, bar.close):
        raise ValueError(f"{bar.symbol} {bar.date}: low is invalid")


def _locked(bar: DailyBar) -> bool:
    return bar.high == bar.low


def _drawdown_pct(curve: list[dict[str, Any]]) -> float:
    peak = 0.0
    maximum = 0.0
    for point in curve:
        nav = float(point["nav"])
        peak = max(peak, nav)
        if peak > 0:
            maximum = max(maximum, (peak - nav) / peak)
    return maximum * 100.0


def _open_equity(
    positions: dict[str, _Position],
    bars_for_day: dict[str, DailyBar],
    last_close: dict[str, float],
) -> float:
    return sum(
        position.shares
        * (
            bars_for_day[position.symbol].open
            if position.symbol in bars_for_day
            else last_close.get(position.symbol, position.entry_price)
        )
        for position in positions.values()
    )


def run_nav_replay(
    signals: list[SignalIntent],
    bars: list[DailyBar],
    *,
    sectors: dict[str, str] | None = None,
    config: ReplayConfig | None = None,
    costs: ReplayCostModel | None = None,
) -> dict[str, Any]:
    """Replay one cash account and return a fully serialisable evidence payload."""
    config = config or ReplayConfig()
    costs = costs or ReplayCostModel.for_market("CN")
    sectors = sectors or {}
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if config.lot_size < 1 or config.entry_ttl_sessions < 1:
        raise ValueError("lot_size and entry_ttl_sessions must be positive")

    bars_by_date: dict[str, dict[str, DailyBar]] = {}
    seen_bars: set[tuple[str, str]] = set()
    for input_bar in bars:
        _validate_bar(input_bar)
        key = (input_bar.symbol, input_bar.date)
        if key in seen_bars:
            raise ValueError(f"duplicate price bar: {key}")
        seen_bars.add(key)
        bars_by_date.setdefault(input_bar.date, {})[input_bar.symbol] = input_bar
    signals_by_date: dict[str, list[SignalIntent]] = {}
    for input_signal in signals:
        signals_by_date.setdefault(input_signal.date[:10], []).append(input_signal)

    cash = float(config.initial_cash)
    positions: dict[str, _Position] = {}
    pending_entries: list[_PendingEntry] = []
    pending_exits: dict[str, str] = {}
    last_close: dict[str, float] = {}
    fills: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []

    def sell(symbol: str, day: str, reference_price: float, reason: str) -> None:
        nonlocal cash
        position = positions.pop(symbol)
        execution_price = reference_price * (1.0 - costs.slippage_sell)
        notional = position.shares * execution_price
        fees = costs.fees("sell", notional)
        slippage = position.shares * max(0.0, reference_price - execution_price)
        cash += notional - fees["total"]
        gross_pnl = notional - position.entry_notional
        net_pnl = notional - fees["total"] - position.entry_notional - position.entry_fees
        fills.append({
            "date": day,
            "symbol": symbol,
            "side": "sell",
            "reason": reason,
            "shares": position.shares,
            "reference_price": round(reference_price, 6),
            "execution_price": round(execution_price, 6),
            "notional": round(notional, 2),
            "fees": {key: round(value, 6) for key, value in fees.items()},
            "slippage_amount": round(slippage, 6),
        })
        trades.append({
            "symbol": symbol,
            "sector": position.sector,
            "entry_signal_date": position.entry_signal_date,
            "entry_date": position.entry_date,
            "exit_date": day,
            "exit_reason": reason,
            "shares": position.shares,
            "gross_pnl": round(gross_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "net_return_pct": round(
                net_pnl / (position.entry_notional + position.entry_fees) * 100.0, 4
            ),
            "total_fees": round(position.entry_fees + fees["total"], 6),
            "total_slippage": round(
                position.shares
                * max(0.0, position.entry_price - position.entry_reference_price)
                + slippage,
                6,
            ),
        })

    def buy(order: _PendingEntry, day: str, bar: DailyBar) -> bool:
        nonlocal cash
        signal = order.signal
        open_equity = _open_equity(positions, bars_by_date[day], last_close)
        nav_at_open = cash + open_equity
        execution_price = bar.open * (1.0 + costs.slippage_buy)
        target = nav_at_open * config.target_position_weight
        shares = int(target // execution_price // config.lot_size) * config.lot_size
        sector = sectors.get(signal.symbol, "未分类")
        sector_value = sum(
            position.shares
            * (
                bars_by_date[day][position.symbol].open
                if position.symbol in bars_by_date[day]
                else last_close.get(position.symbol, position.entry_price)
            )
            for position in positions.values()
            if position.sector == sector
        )
        total_value = open_equity
        max_by_sector = max(0.0, nav_at_open * config.max_sector_weight - sector_value)
        max_by_total = max(0.0, nav_at_open * config.max_total_weight - total_value)
        shares = min(
            shares,
            int(max_by_sector // execution_price // config.lot_size) * config.lot_size,
            int(max_by_total // execution_price // config.lot_size) * config.lot_size,
        )
        while shares > 0:
            notional = shares * execution_price
            fees = costs.fees("buy", notional)
            if notional + fees["total"] <= cash:
                break
            shares -= config.lot_size
        if shares <= 0:
            rejected.append({
                "signal_date": signal.date,
                "date": day,
                "symbol": signal.symbol,
                "reason": "cash_or_exposure_cap",
            })
            return False
        notional = shares * execution_price
        fees = costs.fees("buy", notional)
        slippage = shares * max(0.0, execution_price - bar.open)
        cash -= notional + fees["total"]
        positions[signal.symbol] = _Position(
            symbol=signal.symbol,
            sector=sector,
            shares=shares,
            entry_signal_date=signal.date,
            entry_date=day,
            entry_reference_price=bar.open,
            entry_price=execution_price,
            entry_notional=notional,
            entry_fees=fees["total"],
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        fills.append({
            "date": day,
            "symbol": signal.symbol,
            "side": "buy",
            "reason": "next_session_open",
            "shares": shares,
            "reference_price": round(bar.open, 6),
            "execution_price": round(execution_price, 6),
            "notional": round(notional, 2),
            "fees": {key: round(value, 6) for key, value in fees.items()},
            "slippage_amount": round(slippage, 6),
        })
        return True

    for day in sorted(bars_by_date):
        day_bars = bars_by_date[day]

        for symbol, reason in list(pending_exits.items()):
            position = positions.get(symbol)
            exit_bar = day_bars.get(symbol)
            if position is None:
                pending_exits.pop(symbol, None)
            elif day <= position.entry_date or exit_bar is None or _locked(exit_bar):
                continue
            else:
                sell(symbol, day, exit_bar.open, reason)
                pending_exits.pop(symbol, None)

        remaining_entries: list[_PendingEntry] = []
        pending_entries.sort(key=lambda item: (-item.signal.score, item.signal.date, item.signal.symbol))
        for order in pending_entries:
            signal = order.signal
            if day <= signal.date[:10]:
                remaining_entries.append(order)
                continue
            entry_bar = day_bars.get(signal.symbol)
            if entry_bar is None:
                remaining_entries.append(order)
                continue
            order.waited_sessions += 1
            if signal.symbol in positions:
                rejected.append({
                    "signal_date": signal.date,
                    "date": day,
                    "symbol": signal.symbol,
                    "reason": "already_held",
                })
                continue
            if len(positions) >= config.max_positions:
                rejected.append({
                    "signal_date": signal.date,
                    "date": day,
                    "symbol": signal.symbol,
                    "reason": "max_positions",
                })
                continue
            if _locked(entry_bar):
                if order.waited_sessions >= config.entry_ttl_sessions:
                    rejected.append({
                        "signal_date": signal.date,
                        "date": day,
                        "symbol": signal.symbol,
                        "reason": "one_price_locked",
                    })
                else:
                    remaining_entries.append(order)
                continue
            buy(order, day, entry_bar)
        pending_entries = remaining_entries

        for symbol, position in list(positions.items()):
            if symbol in pending_exits or day <= position.entry_date:
                continue
            position_bar = day_bars.get(symbol)
            if position_bar is None:
                continue
            stop_hit = position.stop_loss is not None and position_bar.low <= position.stop_loss
            target_hit = (
                position.take_profit is not None and position_bar.high >= position.take_profit
            )
            if not stop_hit and not target_hit:
                continue
            if stop_hit:
                assert position.stop_loss is not None
                reason = "stop_loss_conservative" if target_hit else "stop_loss"
                reference = min(position_bar.open, float(position.stop_loss))
            else:
                assert position.take_profit is not None
                reason = "take_profit"
                reference = max(position_bar.open, float(position.take_profit))
            if _locked(position_bar):
                pending_exits[symbol] = f"{reason}_deferred_locked"
            else:
                sell(symbol, day, reference, reason)

        for symbol, position in positions.items():
            if symbol in day_bars and day > position.entry_date:
                position.held_sessions += 1
        for symbol, bar in day_bars.items():
            last_close[symbol] = bar.close

        marked = sum(
            position.shares * last_close.get(symbol, position.entry_price)
            for symbol, position in positions.items()
        )
        nav = cash + marked
        curve.append({
            "date": day,
            "cash": round(cash, 2),
            "market_value": round(marked, 2),
            "nav": round(nav, 2),
            "positions": len(positions),
        })

        day_signals = signals_by_date.get(day, [])
        latest_for_symbol = {signal.symbol: signal for signal in day_signals}
        for symbol, position in positions.items():
            current_signal = latest_for_symbol.get(symbol)
            if (
                current_signal is not None
                and current_signal.score < config.reversal_threshold
                and position.held_sessions >= config.reversal_min_hold_sessions
            ):
                pending_exits.setdefault(symbol, "signal_reversal_next_open")

        pending_symbols = {item.signal.symbol for item in pending_entries}
        candidates = sorted(
            (
                signal
                for signal in day_signals
                if signal.score >= config.entry_threshold
                and signal.symbol not in positions
                and signal.symbol not in pending_symbols
            ),
            key=lambda item: (-item.score, item.symbol),
        )
        pending_entries.extend(_PendingEntry(signal) for signal in candidates)

    ending_nav = curve[-1]["nav"] if curve else config.initial_cash
    total_fees = sum(float(fill["fees"]["total"]) for fill in fills)
    total_slippage = sum(float(fill["slippage_amount"]) for fill in fills)
    realized_net = sum(float(trade["net_pnl"]) for trade in trades)
    unrealized = sum(
        position.shares * last_close.get(symbol, position.entry_price)
        - position.entry_notional
        - position.entry_fees
        for symbol, position in positions.items()
    )
    loss_by_reason: dict[str, float] = {}
    for trade in trades:
        if float(trade["net_pnl"]) < 0:
            reason = str(trade["exit_reason"])
            loss_by_reason[reason] = loss_by_reason.get(reason, 0.0) + float(trade["net_pnl"])

    return {
        "schema_version": "p0r_nav_replay.v1",
        "engine": "independent_cash_nav",
        "config": asdict(config),
        "cost_model": asdict(costs),
        "summary": {
            "initial_nav": round(config.initial_cash, 2),
            "ending_nav": round(float(ending_nav), 2),
            "total_return_pct": round(
                (float(ending_nav) / config.initial_cash - 1.0) * 100.0, 4
            ),
            "max_drawdown_pct": round(_drawdown_pct(curve), 4),
            "realized_net_pnl": round(realized_net, 2),
            "unrealized_pnl_before_exit_cost": round(unrealized, 2),
            "total_fees": round(total_fees, 6),
            "total_slippage": round(total_slippage, 6),
            "closed_trades": len(trades),
            "open_positions": len(positions),
            "fill_count": len(fills),
        },
        "loss_attribution": {
            key: round(value, 2) for key, value in sorted(loss_by_reason.items())
        },
        "equity_curve": curve,
        "fills": fills,
        "trades": trades,
        "open_positions": [asdict(item) for item in positions.values()],
        "pending_exits": dict(sorted(pending_exits.items())),
        "rejections": rejected,
        "assumptions": [
            "signals are observed at close and entries are eligible from the next symbol session",
            "one-price locked bars do not fill",
            "A-share positions cannot exit on their entry date",
            "if stop and take-profit both touch in one daily bar, stop is matched first",
            "gap-through stops fill at open; costs and slippage are applied per side",
            "this is research evidence only and never submits or records an order",
        ],
    }
