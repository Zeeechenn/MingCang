"""
Portfolio-level technical backtest.

This module intentionally stays technical-only: it reads prices and active CN
stocks, computes the same rolling technical score used by backtrader_eval, and
runs one broker account across many data feeds. It does not read Signal rows,
call qlib, call LLM/news code, or write to the database.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import backtrader as bt
import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.backtest.backtrader_eval import (
    A_SHARE_SLIPPAGE_PERC,
    AShareCommission,
    PandasDataExt,
    compute_tech_scores,
    load_data,
)
from backend.config import settings
from backend.data.database import SessionLocal, Stock

LEGACY_PORTFOLIO_CFG = {
    "entry_threshold": 20.0,
    "rr": 2.0,
    "atr_mult": 2.0,
    "max_hold": 5,
    "trailing": False,
    "trailing_mult": 1.5,
    "adx_filter": False,
}

PORTFOLIO_VALIDATION_SNAPSHOT = {
    "metric_scope": "portfolio_equity_curve",
    "universe_rule": "active CN stocks with window price bars >= min_window_bars",
    "start": "2023-01-01",
    "end": "2026-05-14",
    "min_window_bars": 720,
    "expected_n_symbols_at_creation": 92,
    "cash": 1_000_000,
    "settings": {
        "entry_threshold": 20.0,
        "risk_reward_ratio": 2.0,
        "max_hold_days": 5,
        "trailing_stop_enabled": False,
        "adx_filter_enabled": False,
        "max_position_per_stock": 0.15,
        "max_position_per_sector": 0.30,
        "max_total_equity_pct": 0.80,
    },
    "costs": {
        "commission_round_trip": 0.002,
        "slippage_per_trade": A_SHARE_SLIPPAGE_PERC,
    },
    "caveats": [
        "survivorship-biased current universe",
        "technical-only",
        "not a production full-stack backtest",
    ],
    "metrics": None,
    "command": (
        "PYTHONPATH=. python3 backend/backtest/portfolio_eval.py "
        "--start 2023-01-01 --end 2026-05-14 --legacy --min-window-bars 720"
    ),
}


@dataclass(frozen=True)
class FeedMeta:
    symbol: str
    name: str
    industry: str
    bars: int


class PortfolioValueAnalyzer(bt.Analyzer):
    """Capture portfolio value after each Backtrader bar."""

    def start(self) -> None:
        self.values: list[dict[str, Any]] = []

    def next(self) -> None:
        self.values.append({
            "date": self.strategy.datetime.date(0).isoformat(),
            "value": float(self.strategy.broker.getvalue()),
            "cash": float(self.strategy.broker.get_cash()),
        })

    def get_analysis(self) -> list[dict[str, Any]]:
        return self.values


class PortfolioTechStrategy(bt.Strategy):
    """Single-account multi-feed technical strategy with 15/30/80 caps."""

    params = (
        ("entry_threshold", 20.0),
        ("atr_mult", 2.0),
        ("rr", 2.0),
        ("max_hold_days", 5),
        ("trailing_enabled", False),
        ("trailing_atr_mult", 1.5),
        ("symbol_industries", {}),
        ("max_position_per_stock", 0.15),
        ("max_position_per_sector", 0.30),
        ("max_total_equity_pct", 0.80),
    )

    def __init__(self) -> None:
        self.state: dict[Any, dict[str, float | int]] = {}
        self.pending: set[Any] = set()
        self.max_single_exposure = 0.0
        self.max_sector_exposure = 0.0
        self.max_total_exposure = 0.0
        self.max_decision_single_exposure = 0.0
        self.max_decision_sector_exposure = 0.0
        self.max_decision_total_exposure = 0.0

    def notify_order(self, order) -> None:
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.pending.discard(order.data)

    def next(self) -> None:
        for data in self.datas:
            if self.getposition(data).size > 0:
                self._manage_exit(data)

        self._record_exposures()

        equity = float(self.broker.getvalue())
        if equity <= 0:
            return

        candidates = []
        for data in self.datas:
            if data in self.pending or self.getposition(data).size > 0:
                continue
            score = float(data.tech_score[0])
            atr = float(data.atr14[0])
            price = float(data.close[0])
            if math.isnan(score) or math.isnan(atr) or atr <= 0 or price <= 0:
                continue
            if score <= self.p.entry_threshold:
                continue
            candidates.append(data)

        candidates.sort(key=lambda data: float(data.tech_score[0]), reverse=True)
        planned_total = self._total_value()
        planned_sector_values = self._sector_values()
        for data in candidates:
            equity = float(self.broker.getvalue())
            if planned_total >= self.p.max_total_equity_pct * equity:
                break

            price = float(data.close[0])
            sector = self.p.symbol_industries.get(data._name, "未分类")
            target_value = min(
                self.p.max_position_per_stock * equity,
                self.p.max_total_equity_pct * equity - planned_total,
                self.p.max_position_per_sector * equity - planned_sector_values.get(sector, 0.0),
            )
            size = int(target_value // price // 100) * 100
            if size <= 0:
                continue

            order = self.buy(data=data, size=size)
            if order:
                self.pending.add(data)
                atr = float(data.atr14[0])
                self.state[data] = {
                    "entry_bar": self._bar_index(),
                    "stop_price": price - atr * self.p.atr_mult,
                    "take_price": price + atr * self.p.atr_mult * self.p.rr,
                    "entry_atr": atr,
                    "highest_close": price,
                }
                order_value = size * price
                planned_total += order_value
                planned_sector_values[sector] = planned_sector_values.get(sector, 0.0) + order_value
                self.max_decision_single_exposure = max(
                    self.max_decision_single_exposure,
                    order_value / equity,
                )
                self.max_decision_sector_exposure = max(
                    self.max_decision_sector_exposure,
                    planned_sector_values[sector] / equity,
                )
                self.max_decision_total_exposure = max(
                    self.max_decision_total_exposure,
                    planned_total / equity,
                )

        self._record_exposures()

    def _manage_exit(self, data) -> None:
        st = self.state.get(data)
        if not st:
            return

        price = float(data.close[0])
        low = float(data.low[0])
        high = float(data.high[0])
        held = self._bar_index() - int(st["entry_bar"])

        if self.p.trailing_enabled and price > float(st["highest_close"]):
            st["highest_close"] = price
            new_stop = price - float(st["entry_atr"]) * self.p.trailing_atr_mult
            if new_stop > float(st["stop_price"]):
                st["stop_price"] = new_stop

        if low <= float(st["stop_price"]) or high >= float(st["take_price"]) or held >= self.p.max_hold_days:
            order = self.close(data=data)
            if order:
                self.pending.add(data)
            self.state.pop(data, None)

    def _position_value(self, data) -> float:
        return float(self.getposition(data).size) * float(data.close[0])

    def _bar_index(self) -> int:
        try:
            return len(self)
        except TypeError:
            return 0

    def _total_value(self) -> float:
        return sum(max(0.0, self._position_value(data)) for data in self.datas)

    def _sector_value(self, target_data) -> float:
        target_sector = self.p.symbol_industries.get(target_data._name, "未分类")
        return self._sector_values().get(target_sector, 0.0)

    def _sector_values(self) -> dict[str, float]:
        sector_values: dict[str, float] = {}
        for data in self.datas:
            sector = self.p.symbol_industries.get(data._name, "未分类")
            sector_values[sector] = sector_values.get(sector, 0.0) + max(0.0, self._position_value(data))
        return sector_values

    def _record_exposures(self) -> None:
        equity = float(self.broker.getvalue())
        if equity <= 0:
            return
        sector_values: dict[str, float] = {}
        total = 0.0
        for data in self.datas:
            value = max(0.0, self._position_value(data))
            if value <= 0:
                continue
            total += value
            sector = self.p.symbol_industries.get(data._name, "未分类")
            sector_values[sector] = sector_values.get(sector, 0.0) + value
            self.max_single_exposure = max(self.max_single_exposure, value / equity)
        self.max_total_exposure = max(self.max_total_exposure, total / equity)
        for value in sector_values.values():
            self.max_sector_exposure = max(self.max_sector_exposure, value / equity)


def annualized_sharpe_from_daily_returns(returns: list[float], risk_free_rate: float = 0.02) -> float | None:
    if len(returns) < 2:
        return None
    mean_return = sum(returns) / len(returns)
    variance = sum((ret - mean_return) ** 2 for ret in returns) / len(returns)
    stdev = math.sqrt(variance)
    if stdev <= 0:
        return None
    daily_rf = risk_free_rate / 252
    return (mean_return - daily_rf) / stdev * math.sqrt(252)


def max_drawdown_pct(values: list[float]) -> float:
    peak = None
    max_dd = 0.0
    for value in values:
        peak = value if peak is None else max(peak, value)
        if peak and peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd * 100


def cagr_pct(start_value: float, end_value: float, start: str, end: str) -> float:
    days = max((pd.to_datetime(end) - pd.to_datetime(start)).days, 1)
    years = days / 365.25
    return ((end_value / start_value) ** (1 / years) - 1) * 100 if start_value > 0 else 0.0


def equity_metrics(equity_curve: list[dict[str, Any]], initial_cash: float, start: str, end: str) -> dict[str, Any]:
    values = [float(row["value"]) for row in equity_curve]
    if not values:
        values = [initial_cash]
    daily_returns = [
        (values[i] / values[i - 1] - 1)
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]
    final_value = values[-1]
    return {
        "initial_value": round(initial_cash, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round((final_value / initial_cash - 1) * 100, 2),
        "cagr_pct": round(cagr_pct(initial_cash, final_value, start, end), 2),
        "sharpe": round(annualized_sharpe_from_daily_returns(daily_returns), 2)
        if annualized_sharpe_from_daily_returns(daily_returns) is not None else None,
        "max_drawdown_pct": round(max_drawdown_pct(values), 2),
        "daily_return_count": len(daily_returns),
    }


def prepare_feed(stock, db, start: str, end: str, cfg: dict[str, Any], min_window_bars: int) -> tuple[pd.DataFrame, FeedMeta] | None:
    try:
        df_raw = load_data(stock.symbol, db, as_of_end=end)
    except KeyError:
        return None
    if df_raw.empty:
        return None
    df_factored = add_all_factors(df_raw)
    df_factored["tech_score"] = compute_tech_scores(df_factored, apply_adx_filter=cfg["adx_filter"])
    mask = (df_factored.index >= start) & (df_factored.index <= end)
    df_bt = df_factored[mask][["open", "high", "low", "close", "volume", "tech_score", "atr14"]].copy()
    if len(df_bt) < min_window_bars:
        return None
    meta = FeedMeta(
        symbol=stock.symbol,
        name=stock.name,
        industry=getattr(stock, "industry", None) or "未分类",
        bars=len(df_bt),
    )
    return df_bt, meta


def load_active_cn_stocks(db, symbols: list[str] | None = None) -> list[Any]:
    q = db.query(Stock).filter(Stock.active, Stock.market == "CN")
    if symbols:
        q = q.filter(Stock.symbol.in_(symbols))
    return q.order_by(Stock.symbol.asc()).all()


def run_portfolio_backtest(
    stocks,
    db,
    *,
    start: str,
    end: str,
    cfg: dict[str, Any],
    cash: float,
    min_window_bars: int,
) -> dict[str, Any]:
    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(cash)
    cerebro.broker.addcommissioninfo(AShareCommission())
    cerebro.broker.set_slippage_perc(A_SHARE_SLIPPAGE_PERC)

    included: list[FeedMeta] = []
    excluded: list[dict[str, Any]] = []
    for stock in stocks:
        prepared = prepare_feed(stock, db, start, end, cfg, min_window_bars)
        if prepared is None:
            excluded.append({"symbol": stock.symbol, "reason": f"window_bars < {min_window_bars}"})
            continue
        df_bt, meta = prepared
        included.append(meta)
        cerebro.adddata(PandasDataExt(dataname=df_bt), name=meta.symbol)

    if not included:
        raise ValueError("no symbols passed the portfolio backtest universe filter")

    symbol_industries = {meta.symbol: meta.industry for meta in included}
    cerebro.addstrategy(
        PortfolioTechStrategy,
        entry_threshold=cfg["entry_threshold"],
        atr_mult=cfg["atr_mult"],
        rr=cfg["rr"],
        max_hold_days=cfg["max_hold"],
        trailing_enabled=cfg["trailing"],
        trailing_atr_mult=cfg["trailing_mult"],
        symbol_industries=symbol_industries,
        max_position_per_stock=settings.max_position_per_stock,
        max_position_per_sector=settings.max_position_per_sector,
        max_total_equity_pct=settings.max_total_equity_pct,
    )
    cerebro.addanalyzer(PortfolioValueAnalyzer, _name="values")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    cerebro.run()
    strat = cerebro.runstrats[0][0]
    equity_curve = strat.analyzers.values.get_analysis()
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)
    won = trade_analysis.get("won", {}).get("total", 0)

    metrics = equity_metrics(equity_curve, cash, start, end)
    metrics.update({
        "trades": total_trades,
        "won": won,
        "win_rate_pct": round(won / total_trades * 100, 2) if total_trades else 0.0,
        "max_decision_single_exposure_pct": round(strat.max_decision_single_exposure * 100, 2),
        "max_decision_sector_exposure_pct": round(strat.max_decision_sector_exposure * 100, 2),
        "max_decision_total_exposure_pct": round(strat.max_decision_total_exposure * 100, 2),
        "max_mark_to_market_single_exposure_pct": round(strat.max_single_exposure * 100, 2),
        "max_mark_to_market_sector_exposure_pct": round(strat.max_sector_exposure * 100, 2),
        "max_mark_to_market_total_exposure_pct": round(strat.max_total_exposure * 100, 2),
    })

    return {
        "metric_scope": "portfolio_equity_curve",
        "start": start,
        "end": end,
        "cash": cash,
        "min_window_bars": min_window_bars,
        "n_symbols": len(included),
        "included_symbols": [meta.symbol for meta in included],
        "excluded": excluded,
        "industries": symbol_industries,
        "settings": {
            "entry_threshold": cfg["entry_threshold"],
            "risk_reward_ratio": cfg["rr"],
            "max_hold_days": cfg["max_hold"],
            "trailing_stop_enabled": cfg["trailing"],
            "adx_filter_enabled": cfg["adx_filter"],
            "max_position_per_stock": settings.max_position_per_stock,
            "max_position_per_sector": settings.max_position_per_sector,
            "max_total_equity_pct": settings.max_total_equity_pct,
        },
        "costs": {
            "commission_round_trip": 0.002,
            "slippage_per_trade": A_SHARE_SLIPPAGE_PERC,
        },
        "caveats": PORTFOLIO_VALIDATION_SNAPSHOT["caveats"],
        "metrics": metrics,
        "equity_curve": equity_curve,
    }


def write_equity_csv(path: str | Path, equity_curve: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "value", "cash"])
        writer.writeheader()
        writer.writerows(equity_curve)


def print_table(result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    print()
    print("=" * 96)
    print("  Portfolio technical backtest [single broker / multi-feed]")
    print(f"  {result['start']} ~ {result['end']} | N={result['n_symbols']} | cash={result['cash']:,.0f}")
    print("  Caveats: survivorship-biased current universe; technical-only; not a production full-stack backtest")
    print("=" * 96)
    print(f"  Total return: {metrics['total_return_pct']:+.2f}%")
    print(f"  CAGR:         {metrics['cagr_pct']:+.2f}%")
    print(f"  Sharpe:       {metrics['sharpe'] if metrics['sharpe'] is not None else 'N/A'}")
    print(f"  Max DD:       {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Trades:       {metrics['trades']} | win rate {metrics['win_rate_pct']:.1f}%")
    print(f"  Decision exposure: single {metrics['max_decision_single_exposure_pct']:.2f}% | "
          f"sector {metrics['max_decision_sector_exposure_pct']:.2f}% | "
          f"total {metrics['max_decision_total_exposure_pct']:.2f}%")
    print(f"  Mark-to-market max: single {metrics['max_mark_to_market_single_exposure_pct']:.2f}% | "
          f"sector {metrics['max_mark_to_market_sector_exposure_pct']:.2f}% | "
          f"total {metrics['max_mark_to_market_total_exposure_pct']:.2f}%")
    if result["excluded"]:
        excluded = ", ".join(row["symbol"] for row in result["excluded"][:8])
        suffix = "..." if len(result["excluded"]) > 8 else ""
        print(f"  Excluded:     {len(result['excluded'])} ({excluded}{suffix})")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-05-14")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--cash", type=float, default=1_000_000)
    ap.add_argument("--min-window-bars", type=int, default=720)
    ap.add_argument("--legacy", action="store_true", help="Use legacy-compatible technical settings")
    ap.add_argument("--format", choices=("table", "json"), default="table")
    ap.add_argument("--equity-csv", default=None)
    args = ap.parse_args()

    cfg = dict(LEGACY_PORTFOLIO_CFG)
    if not args.legacy:
        cfg.update({
            "rr": settings.risk_reward_ratio,
            "max_hold": settings.max_hold_days,
            "trailing": settings.trailing_stop_enabled,
            "trailing_mult": settings.trailing_atr_mult,
            "adx_filter": settings.adx_filter_enabled,
        })

    db = SessionLocal()
    try:
        stocks = load_active_cn_stocks(db, args.symbols)
        result = run_portfolio_backtest(
            stocks,
            db,
            start=args.start,
            end=args.end,
            cfg=cfg,
            cash=args.cash,
            min_window_bars=args.min_window_bars,
        )
    finally:
        db.close()

    if args.equity_csv:
        write_equity_csv(args.equity_csv, result["equity_curve"])

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)


if __name__ == "__main__":
    main()
