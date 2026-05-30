"""
Backtrader 严肃回测 — 阶段A 地基交付物 #1（阶段B 升级版）

用法：
  PYTHONPATH=. python3 backend/backtest/backtrader_eval.py                 # 新版（阶段B 全开）
  PYTHONPATH=. python3 backend/backtest/backtrader_eval.py --legacy        # 旧版基线（5日强平+1:2 RR+无ADX过滤）
  PYTHONPATH=. python3 backend/backtest/backtrader_eval.py --compare       # 同时跑新旧版做对比
  PYTHONPATH=. python3 backend/backtest/backtrader_eval.py --symbols 300308

策略变量（settings 可调）：
  • risk_reward_ratio   (默认 1.5；旧版 2.0)
  • atr_multiplier      (止损 ATR 倍数，默认 2.0)
  • max_hold_days       (持仓上限，默认 5)
  • trailing_stop_enabled / trailing_atr_mult
  • adx_filter_enabled  (技术分数按 ADX 衰减；震荡市 ×0.5)

A股手续费：买入 0.05% 佣金；卖出 0.05% 佣金 + 0.10% 印花税。
"""
from __future__ import annotations

import argparse
import logging
import warnings

import backtrader as bt
import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.analysis.technical import score_macd, score_rsi, score_trend, score_volume
from backend.config import settings
from backend.data.database import Price, SessionLocal, Stock

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# 回测公开验证口径：A 股交易成本 = 往返 0.20% 手续费/印花税 + 每次成交 0.10% 滑点。
A_SHARE_SLIPPAGE_PERC = 0.001

PUBLIC_VALIDATION_SNAPSHOT = {
    "metric_scope": "single_stock_cross_section_average",
    "universe": ["300308", "688008"],
    "n_symbols": 2,
    "start": "2025-11-01",
    "end": "2026-05-14",
    "settings": {
        "risk_reward_ratio": 2.0,
        "max_hold_days": 5,
        "trailing_stop_enabled": False,
        "adx_filter_enabled": False,
    },
    "costs": {
        "commission_round_trip": 0.002,
        "slippage_per_trade": A_SHARE_SLIPPAGE_PERC,
    },
    "metrics": {
        "avg_sharpe": 2.50,
        "avg_max_drawdown_pct": 15.69,
        "avg_profit_factor": 3.13,
    },
    "command": (
        "PYTHONPATH=. python3 backend/backtest/backtrader_eval.py "
        "--symbols 300308 688008 --start 2025-11-01 --end 2026-05-14 --legacy"
    ),
}

# ── A股手续费 ─────────────────────────────────────────────────────────

class AShareCommission(bt.CommInfoBase):
    """买入：0.05% 佣金；卖出：0.05% 佣金 + 0.10% 印花税"""
    params = (
        ("commission", 0.0005),
        ("stamp_tax", 0.0010),
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec) -> float:
        """Return commission for A-share trades including stamp tax on sells."""
        notional = abs(size) * price
        if size > 0:
            return notional * self.p.commission
        return notional * (self.p.commission + self.p.stamp_tax)


# ── 数据 feed 扩展 ────────────────────────────────────────────────────

class PandasDataExt(bt.feeds.PandasData):
    lines = ("tech_score", "atr14")
    params = (
        ("tech_score", -1),
        ("atr14", -1),
    )


# ── 策略 ──────────────────────────────────────────────────────────────

class TechSignalStrategy(bt.Strategy):
    """
    阶段B 升级策略：
      入场: tech_score > entry_threshold
      初始止损: 买入价 - ATR × atr_mult
      初始止盈: 买入价 + ATR × atr_mult × rr
      Trailing stop（如启用）: 持仓期最高收盘价 - ATR × trailing_atr_mult
      超时强平: 持有 ≥ max_hold_days

    长期标签约束（mock-labels 模式，long_term_label 参数）：
      规避       → 完全不入场
      估值偏高   → 仓位 × 0.5
      观望       → 入场阈值从 entry_threshold 提到 30（综合分截断效果）
      值得持有/None → 无影响
    """
    params = (
        ("entry_threshold", 20),
        ("atr_mult", 2.0),
        ("rr", 1.5),
        ("max_hold_days", 5),
        ("trailing_enabled", True),
        ("trailing_atr_mult", 1.5),
        ("size_pct", 0.95),
        ("long_term_label", None),
    )

    def __init__(self) -> None:
        """Initialize strategy indicators and state variables."""
        self.score = self.datas[0].tech_score
        self.atr = self.datas[0].atr14
        self.entry_bar: int | None = None
        self.stop_price: float | None = None
        self.take_price: float | None = None
        self.entry_atr: float | None = None
        self.highest_close: float | None = None

    def next(self) -> None:
        """Execute strategy logic on each bar: manage open positions or scan for entry."""
        price = self.data.close[0]
        low = self.data.low[0]
        high = self.data.high[0]

        if self.position.size > 0:
            assert self.entry_bar is not None
            assert self.stop_price is not None
            assert self.take_price is not None
            assert self.entry_atr is not None
            assert self.highest_close is not None
            held = len(self) - self.entry_bar
            # trailing stop 提升
            if self.p.trailing_enabled and price > self.highest_close:
                self.highest_close = price
                new_stop = price - self.entry_atr * self.p.trailing_atr_mult
                if new_stop > self.stop_price:
                    self.stop_price = new_stop

            if low <= self.stop_price:
                self.close()
            elif high >= self.take_price:
                self.close()
            elif held >= self.p.max_hold_days:
                self.close()
            return

        score = self.score[0]
        atr = self.atr[0]
        if pd.isna(score) or pd.isna(atr) or atr <= 0:
            return

        # 长期标签约束
        lt = self.p.long_term_label
        size_factor = 1.0
        threshold = self.p.entry_threshold
        if lt == "规避":
            return    # 完全屏蔽
        if lt == "估值偏高":
            size_factor = 0.5
        if lt == "观望":
            threshold = max(threshold, 30.0)

        if score <= threshold:
            return

        cash = self.broker.get_cash()
        size_pct = self.p.size_pct * size_factor
        size = int((cash * size_pct) // price // 100) * 100
        if size <= 0:
            return
        self.buy(size=size)
        self.entry_bar = len(self)
        self.stop_price = price - atr * self.p.atr_mult
        self.take_price = price + atr * self.p.atr_mult * self.p.rr
        self.entry_atr = atr
        self.highest_close = price


# ── 因子预计算 ────────────────────────────────────────────────────────

WARMUP = 80
WEIGHTS = {"trend": 0.4, "rsi": 0.25, "macd": 0.25, "volume": 0.1}


def compute_tech_scores(df_factored: pd.DataFrame, apply_adx_filter: bool = True) -> pd.Series:
    """按日滚动计算技术综合分。阶段B: 可选 ADX 衰减系数。

    M18.2 O(n²) 修复：各 score 函数最多使用最近 20 行（score_volume 需20日均量），
    用 iloc[max(0,i-19):i+1] 替代 iloc[:i+1]，将每轮切片大小固定为 ≤20。
    """
    scores = []
    for i in range(len(df_factored)):
        if i < WARMUP:
            scores.append(float("nan"))
            continue
        # 只取最近 max(WARMUP, 20) 行：score_volume 最长需要 20 行
        lookback = max(WARMUP, 20)
        s = df_factored.iloc[max(0, i - lookback + 1): i + 1]
        raw = (
            score_trend(s) * WEIGHTS["trend"]
            + score_rsi(s) * WEIGHTS["rsi"]
            + score_macd(s) * WEIGHTS["macd"]
            + score_volume(s) * WEIGHTS["volume"]
        )
        score = raw * 100
        if apply_adx_filter and "adx14" in df_factored.columns:
            adx = df_factored["adx14"].iloc[i]
            if not pd.isna(adx):
                if adx < settings.adx_threshold:
                    score *= 0.5
                elif adx < 40:
                    score *= 0.75 + (adx - settings.adx_threshold) / (40 - settings.adx_threshold) * 0.25
        scores.append(round(score, 1))
    return pd.Series(scores, index=df_factored.index)


def load_data(symbol: str, db, as_of_end: str | None = None) -> pd.DataFrame:
    """Load OHLCV price rows from DB into a datetime-indexed DataFrame."""
    q = db.query(Price).filter(Price.symbol == symbol)
    if as_of_end:
        q = q.filter(Price.date <= as_of_end)
    rows = q.order_by(Price.date.asc()).all()
    return pd.DataFrame([
        {
            "datetime": pd.to_datetime(r.date),
            "open": r.open, "high": r.high,
            "low": r.low, "close": r.close,
            "volume": r.volume or 0,
        }
        for r in rows
    ]).set_index("datetime")


# ── 单股回测 ──────────────────────────────────────────────────────────

def run_one(symbol: str, name: str, df_raw: pd.DataFrame, start: str, end: str,
            cfg: dict, long_term_label: str | None = None) -> dict | None:
    """Run a single-stock Backtrader backtest and return summary metrics or None."""
    df_factored = add_all_factors(df_raw)
    df_factored["tech_score"] = compute_tech_scores(df_factored, apply_adx_filter=cfg["adx_filter"])

    mask = (df_factored.index >= start) & (df_factored.index <= end)
    df_bt = df_factored[mask][["open", "high", "low", "close", "volume", "tech_score", "atr14"]].copy()
    if len(df_bt) < 30:
        return None

    cerebro = bt.Cerebro()
    cerebro.broker.set_cash(100_000)
    cerebro.broker.addcommissioninfo(AShareCommission())
    cerebro.broker.set_slippage_perc(A_SHARE_SLIPPAGE_PERC)
    cerebro.adddata(PandasDataExt(dataname=df_bt), name=symbol)
    cerebro.addstrategy(
        TechSignalStrategy,
        rr=cfg["rr"],
        max_hold_days=cfg["max_hold"],
        trailing_enabled=cfg["trailing"],
        trailing_atr_mult=cfg["trailing_mult"],
        long_term_label=long_term_label,
    )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.02)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    initial = cerebro.broker.getvalue()
    cerebro.run()
    final = cerebro.broker.getvalue()
    strat = cerebro.runstrats[0][0]

    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    dd = strat.analyzers.dd.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    total = trades.get("total", {}).get("closed", 0)
    won = trades.get("won", {}).get("total", 0)
    pnl_won = trades.get("won", {}).get("pnl", {}).get("total", 0) or 0
    pnl_lost = abs(trades.get("lost", {}).get("pnl", {}).get("total", 0) or 0)
    # M18.2 盈亏比澄清：此处为"盈利总额 / 亏损总额"（Profit Factor），
    # 不是"平均单笔盈利 / 平均单笔亏损"。两者定义不同，前端列标"盈亏比"指 Profit Factor。
    profit_factor = (pnl_won / pnl_lost) if pnl_lost > 0 else (float("inf") if pnl_won > 0 else 0)

    return {
        "symbol": symbol, "name": name,
        "return_pct": (final / initial - 1) * 100,
        "sharpe": sharpe,
        "max_dd": dd.get("max", {}).get("drawdown", 0),
        "trades": total,
        "won": won,
        "win_rate": (won / total * 100) if total else 0,
        # profit_factor = 盈利总额 / 亏损总额（Profit Factor，非平均盈亏比）
        "profit_factor": profit_factor,
    }


# ── 主循环 ────────────────────────────────────────────────────────────

def run_suite(stocks, db, start, end, cfg, label, mock_labels: dict | None = None) -> dict | None:
    """Run backtest across all stocks and print a comparison table with aggregates."""
    print()
    print("=" * 94)
    print(f"  Backtrader 严肃回测  [{label}]")
    print(f"  区间 {start} ~ {end}  |  RR={cfg['rr']}  hold≤{cfg['max_hold']}d  "
          f"trailing={'ON' if cfg['trailing'] else 'OFF'}  ADX过滤={'ON' if cfg['adx_filter'] else 'OFF'}"
          + (f"  mock-labels=ON({len(mock_labels)}股)" if mock_labels else ""))
    print("=" * 94)
    header_extra = "  长期标签" if mock_labels else ""
    print(f"  {'股票':<14}{'笔数':>5}{'胜率':>9}{'净收益':>10}{'Sharpe':>10}{'最大回撤':>11}{'盈亏比':>10}{header_extra}")
    print("-" * 94)

    agg = []
    for s in stocks:
        df = load_data(s.symbol, db, as_of_end=end)
        if len(df) < WARMUP + 30:
            print(f"  {s.symbol} {s.name}: 数据不足，跳过")
            continue
        lt_label = mock_labels.get(s.symbol) if mock_labels else None
        try:
            r = run_one(s.symbol, s.name, df, start, end, cfg, long_term_label=lt_label)
            if r is None:
                continue
            r["long_term_label"] = lt_label
            agg.append(r)
            sharpe = f"{r['sharpe']:.2f}" if r["sharpe"] is not None else "N/A"
            pf = "∞" if r["profit_factor"] == float("inf") else f"{r['profit_factor']:.2f}"
            tag = f"{r['name'][:4]}({r['symbol']})"
            lt_str = f"  [{lt_label}]" if lt_label else ""
            print(f"  {tag:<14}{r['trades']:>5}{r['win_rate']:>8.1f}%"
                  f"{r['return_pct']:>+9.2f}%{sharpe:>10}{r['max_dd']:>9.2f}%{pf:>10}{lt_str}")
        except Exception as e:
            print(f"  {s.symbol}: 失败 — {e}")

    print("-" * 94)
    if not agg:
        return None

    total_trades = sum(r["trades"] for r in agg)
    total_wins = sum(r["won"] for r in agg)
    avg_ret = sum(r["return_pct"] for r in agg) / len(agg)
    sharpes = [r["sharpe"] for r in agg if r["sharpe"] is not None]
    avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0
    avg_dd = sum(r["max_dd"] for r in agg) / len(agg)
    pfs = [r["profit_factor"] for r in agg if r["profit_factor"] != float("inf")]
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    overall_win = (total_wins / total_trades * 100) if total_trades else 0

    summary = {
        "label": label, "n": len(agg), "trades": total_trades,
        "win_rate": overall_win, "avg_return": avg_ret,
        "avg_sharpe": avg_sharpe, "avg_dd": avg_dd, "avg_pf": avg_pf,
    }

    # 二阶可信度审计
    if len(sharpes) >= 2:
        try:
            from backend.backtest.statistics import (
                expected_max_sharpe,
                ic_significance,
            )
            n = len(sharpes)
            # M18.1 n_trials 语义修复：这里的"试验"是面板中的股票数，
            # 不是参数扫描的方案数。SR_0 仅作参考，含义为"n只不同股票里最优Sharpe期望"。
            sr0 = expected_max_sharpe(sharpes, n_trials=n)
            summary["sr_threshold_panel"] = round(sr0, 3)
            summary["sr_passes_panel"] = avg_sharpe > sr0
            # 面板 Sharpe 的 t 检验（样本均值显著 > 0）
            mean_s = sum(sharpes) / n
            var_s = sum((s - mean_s) ** 2 for s in sharpes) / (n - 1) if n > 1 else 0
            stderr = (var_s ** 0.5) / (n ** 0.5)
            t_stat = (avg_sharpe / stderr) if stderr > 0 else 0.0
            summary["avg_sharpe_t_stat"] = round(t_stat, 2)

            # M18.2 接线：IC 显著性（把面板平均 Sharpe 当成 IC 近似，仅作参考）
            ic_res = ic_significance(avg_sharpe / (252 ** 0.5), n)
            summary["ic_significance"] = ic_res.to_dict()

            print(f"        二阶审计：SR_0(panel N={n})={sr0:.2f}  "
                  f"{'✅ 跨越面板阈值' if avg_sharpe > sr0 else '⚠ 未跨越面板阈值'}  "
                  f"t({n - 1})={t_stat:.2f}  IC近似 p={ic_res.p_value_two_sided:.3f}({ic_res.verdict()})")
        except Exception as e:
            summary["sr_audit_error"] = str(e)

    print(f"\n  汇总  股票数={len(agg)}  总笔数={total_trades}  总体胜率={overall_win:.1f}%")
    print(f"        平均净收益={avg_ret:+.2f}%  平均Sharpe={avg_sharpe:.2f}  平均最大回撤={avg_dd:.2f}%  平均盈亏比={avg_pf:.2f}")
    return summary


def main() -> None:
    """CLI entry point for the Backtrader evaluation suite."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-11-01")
    ap.add_argument("--end", default="2026-05-14")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--legacy", action="store_true", help="使用旧版基线参数（RR=2.0，无 trailing，无 ADX 过滤）")
    ap.add_argument("--compare", action="store_true", help="同时跑新旧版做并排对比")
    ap.add_argument("--mock-labels", type=str, default=None,
                    help="加载手工标注的长期 label JSON 文件，回测时按 label 过滤入场")
    args = ap.parse_args()

    # 加载 mock labels（{symbol: label_str}）
    mock_labels = None
    if args.mock_labels:
        import json as _json
        with open(args.mock_labels) as f:
            raw = _json.load(f)
        mock_labels = {row["symbol"]: row["label"] for row in raw.get("labels", [])}
        print(f"\n📌 加载 {len(mock_labels)} 个手工标注 label: {args.mock_labels}")

    legacy_cfg = dict(rr=2.0, max_hold=5, trailing=False, trailing_mult=1.5, adx_filter=False)
    new_cfg = dict(
        rr=settings.risk_reward_ratio,
        max_hold=settings.max_hold_days,
        trailing=settings.trailing_stop_enabled,
        trailing_mult=settings.trailing_atr_mult,
        adx_filter=settings.adx_filter_enabled,
    )

    db = SessionLocal()
    try:
        q = db.query(Stock).filter(Stock.active, Stock.market == "CN")
        if args.symbols:
            q = q.filter(Stock.symbol.in_(args.symbols))
        stocks = q.all()
        if not stocks:
            print("无活跃A股")
            return

        if args.compare:
            old = run_suite(stocks, db, args.start, args.end, new_cfg, "无长期标签", mock_labels=None)
            new = run_suite(stocks, db, args.start, args.end, new_cfg, "含长期标签",
                            mock_labels=mock_labels) if mock_labels else \
                  run_suite(stocks, db, args.start, args.end, legacy_cfg, "Legacy 基线")
            if old and new:
                print()
                print("=" * 70)
                print("  Legacy vs 阶段B 并排对比")
                print("=" * 70)
                label_a = old["label"] if old else "对照组"
                label_b = new["label"] if new else "实验组"
                print(f"  {'指标':<18}{label_a:>15}{label_b:>15}{'差值':>15}")
                for key, label in [
                    ("trades", "总笔数"), ("win_rate", "总体胜率%"),
                    ("avg_return", "平均净收益%"), ("avg_sharpe", "平均Sharpe"),
                    ("avg_dd", "平均最大回撤%"), ("avg_pf", "平均盈亏比"),
                ]:
                    delta = new[key] - old[key]
                    print(f"  {label:<18}{old[key]:>15.2f}{new[key]:>15.2f}{delta:>+15.2f}")
        else:
            cfg = legacy_cfg if args.legacy else new_cfg
            label = "Legacy 基线" if args.legacy else "阶段B 新版"
            if mock_labels:
                label += " + 长期标签"
            run_suite(stocks, db, args.start, args.end, cfg, label, mock_labels=mock_labels)
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
