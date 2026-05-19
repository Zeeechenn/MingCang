"""测试2 量化权重归因分析（与生产代码解耦的离线分析脚本）

目标：在测试2 中期/末期复盘节点回答"量化权重是不是该归零"。

工作边界（请勿越界）：
- 仅分析测试2（2026-05-18 起，25 只股票池），不分析测试1 或生产其他股票
- 25 股票池、测试1/测试2 权重、阈值在本文件 hard-code，**不 import backend.config**
  → 生产代码修改 weights/threshold/股票池 不会影响本分析
- DB 只读 SELECT，不写任何表
- 输出独立 markdown 文件 paper_trading/quant_attribution_{run_date}.md
  → 不修改 test2.md / results.md / PROJECT.md / STATUS.md

用法：
    python3 paper_trading/quant_attribution.py                  # 默认 as-of=今天
    python3 paper_trading/quant_attribution.py --as-of 2026-06-15
    python3 paper_trading/quant_attribution.py --db ./stock-sage.db --start 2026-05-18

输出：
    paper_trading/quant_attribution_YYYY-MM-DD.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# Pinned constants（生产代码改这些值都不影响本分析）
# ────────────────────────────────────────────────────────────────────────────

TEST2_START = "2026-05-18"
TEST2_END = "2026-07-18"

# 25 股票池（test2.md 原始回测池 7 + 分享报告导入池 20，去重后 25）
TEST2_UNIVERSE: tuple[str, ...] = (
    "600547", "688008", "603993", "300308", "603986", "601088", "300394",
    "002371", "600584", "600900", "601689", "300274", "600160", "600036",
    "000858", "300124", "601899", "601318", "688111", "600406", "603259",
    "300750", "002050", "000568", "002475",
)

# 测试1 框架（带量化权重）
T1_W_QUANT = 0.45
T1_W_TECH = 0.40
T1_W_SENT = 0.15
T1_ENTRY_THRESHOLD = 20.0

# 测试2 框架（量化归零）
T2_W_QUANT = 0.0
T2_W_TECH = 0.60
T2_W_SENT = 0.40
T2_ENTRY_THRESHOLD = 25.0

# 仓位管理（测试2 规则）
MAX_CONCURRENT_POSITIONS = 3
POSITION_SIZE_PCT = 0.15

# 反事实信号反转出场阈值（测试2 规则：持仓 >2 日且综合分 < -15）
EXIT_SIGNAL_THRESHOLD = -15.0
EXIT_MIN_HOLD_DAYS = 2

# 手续费（单边）
COMMISSION_BUY = 0.0005
COMMISSION_SELL_AND_TAX = 0.0015  # 0.05% 佣金 + 0.10% 印花税

# ────────────────────────────────────────────────────────────────────────────
# Data structures
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class Signal:
    symbol: str
    date: str
    quant: float
    tech: float
    sent: float
    composite_db: float  # 数据库存储的实际综合分（测试2 框架算出）
    stop_loss: float | None
    take_profit: float | None
    recommendation: str | None
    rule_version: str | None

    def composite_under_test1(self) -> float:
        """用测试1 权重重算综合分。
        匹配 backend/decision/aggregator.py 的简单线性形式（不含 regime filter）。
        与 paper_trading/test1.md 入场日历史值精确一致。
        """
        c = T1_W_QUANT * self.quant + T1_W_TECH * self.tech + T1_W_SENT * self.sent
        return round(max(-100.0, min(100.0, c)), 1)

    def composite_under_test2_check(self) -> float:
        """用测试2 权重重算（用于校验 DB 存储值是否含 regime filter 等额外调整）。"""
        c = T2_W_QUANT * self.quant + T2_W_TECH * self.tech + T2_W_SENT * self.sent
        return round(max(-100.0, min(100.0, c)), 1)


# ────────────────────────────────────────────────────────────────────────────
# DB access（只读）
# ────────────────────────────────────────────────────────────────────────────


def load_signals(db_path: str, start: str, end: str) -> list[Signal]:
    """拉取测试2 股票池在 [start, end] 窗口内的所有信号。只读。"""
    placeholders = ",".join(["?"] * len(TEST2_UNIVERSE))
    sql = f"""
        SELECT symbol, date, quant_score, technical_score, sentiment_score,
               composite_score, stop_loss, take_profit, recommendation, rule_version
        FROM signals
        WHERE symbol IN ({placeholders})
          AND date >= ? AND date <= ?
        ORDER BY date, symbol
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(sql, (*TEST2_UNIVERSE, start, end)).fetchall()
    finally:
        con.close()

    out: list[Signal] = []
    for r in rows:
        out.append(Signal(
            symbol=r[0], date=r[1],
            quant=float(r[2] or 0), tech=float(r[3] or 0), sent=float(r[4] or 0),
            composite_db=float(r[5] or 0),
            stop_loss=r[6], take_profit=r[7],
            recommendation=r[8], rule_version=r[9],
        ))
    return out


def load_prices(db_path: str, start: str, end: str) -> dict[tuple[str, str], dict]:
    """拉取 OHLC，用于反事实回放止损/止盈。返回 {(symbol, date): {...}}。只读。"""
    placeholders = ",".join(["?"] * len(TEST2_UNIVERSE))
    sql = f"""
        SELECT symbol, date, open, high, low, close, atr14
        FROM prices
        WHERE symbol IN ({placeholders})
          AND date >= ? AND date <= ?
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(sql, (*TEST2_UNIVERSE, start, end)).fetchall()
    finally:
        con.close()

    return {
        (r[0], r[1]): {"open": r[2], "high": r[3], "low": r[4], "close": r[5], "atr14": r[6]}
        for r in rows
    }


# ────────────────────────────────────────────────────────────────────────────
# Analysis
# ────────────────────────────────────────────────────────────────────────────


def compare_daily_entries(signals: list[Signal]) -> dict[str, dict]:
    """按日聚合：列出两套框架下分别会进场的股票。

    返回 {date: {"t1_entries": [...], "t2_entries": [...],
                  "t1_only": [...], "t2_only": [...], "both": [...]}}
    """
    by_date: dict[str, list[Signal]] = {}
    for s in signals:
        by_date.setdefault(s.date, []).append(s)

    result = {}
    for date, sigs in sorted(by_date.items()):
        t1 = {s.symbol for s in sigs if s.composite_under_test1() > T1_ENTRY_THRESHOLD}
        t2 = {s.symbol for s in sigs if s.composite_db > T2_ENTRY_THRESHOLD}
        result[date] = {
            "t1_entries": sorted(t1),
            "t2_entries": sorted(t2),
            "t1_only": sorted(t1 - t2),  # 测试1 进、测试2 不进
            "t2_only": sorted(t2 - t1),  # 测试2 进、测试1 不进
            "both": sorted(t1 & t2),
        }
    return result


def quant_score_correlation(signals: list[Signal], prices: dict, fwd_days: int = 5) -> dict:
    """量化分 vs 后续 N 个交易日真实收益的 Spearman 相关性。

    回答：量化分是否有预测力？（如果 ρ > 0.1 且样本足够，量化层有信号；接近 0 则确实可归零）
    """
    by_symbol_dates: dict[str, list[str]] = {}
    for s in signals:
        by_symbol_dates.setdefault(s.symbol, []).append(s.date)
    for sym in by_symbol_dates:
        by_symbol_dates[sym].sort()

    pairs: list[tuple[float, float]] = []  # (quant_score, fwd_return%)
    for s in signals:
        sym_dates = by_symbol_dates[s.symbol]
        try:
            i = sym_dates.index(s.date)
        except ValueError:
            continue
        if i + fwd_days >= len(sym_dates):
            continue
        d0 = s.date
        d1 = sym_dates[i + fwd_days]
        p0 = prices.get((s.symbol, d0))
        p1 = prices.get((s.symbol, d1))
        if not p0 or not p1 or not p0.get("close") or not p1.get("close"):
            continue
        ret = (p1["close"] - p0["close"]) / p0["close"] * 100
        pairs.append((s.quant, ret))

    if len(pairs) < 5:
        return {"n": len(pairs), "spearman_rho": None, "note": "样本不足"}

    # Spearman = Pearson of ranks
    def rank(xs):
        sorted_xs = sorted(enumerate(xs), key=lambda t: t[1])
        ranks = [0.0] * len(xs)
        for r, (i, _) in enumerate(sorted_xs):
            ranks[i] = float(r + 1)
        return ranks

    xs, ys = zip(*pairs)
    rx, ry = rank(xs), rank(ys)
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    vx = sum((r - mx) ** 2 for r in rx) ** 0.5
    vy = sum((r - my) ** 2 for r in ry) ** 0.5
    rho = cov / (vx * vy) if vx and vy else 0.0

    return {"n": n, "spearman_rho": round(rho, 4), "fwd_days": fwd_days}


# ────────────────────────────────────────────────────────────────────────────
# TODO（占位，等数据足够后再实现）
# ────────────────────────────────────────────────────────────────────────────


def simulate_test1_framework(signals: list[Signal], prices: dict) -> dict:
    """反事实持仓回放：在测试2 股票池上用测试1 框架走一遍，记录每笔进出和净盈亏。

    TODO: 实现 ATR×2 止损 / ATR×4 止盈 / 信号反转出场（持仓>2日 且 composite<-15）/
          仓位上限 3 笔 / 板块上限 30%（暂略）/ 手续费 0.20% 来回。

    目前样本太少（测试2 刚开 2 个交易日），等 06-15 第一节点再启用。
    """
    return {"status": "stub", "note": "等测试2 累计 ≥20 个交易日后再实现"}


# ────────────────────────────────────────────────────────────────────────────
# Report
# ────────────────────────────────────────────────────────────────────────────


def write_report(out_path: Path, run_date: str, start: str, end: str,
                 signals: list[Signal], daily: dict, corr: dict) -> None:
    n_days = len(daily)
    n_signals = len(signals)
    total_t1 = sum(len(d["t1_entries"]) for d in daily.values())
    total_t2 = sum(len(d["t2_entries"]) for d in daily.values())
    total_t1_only = sum(len(d["t1_only"]) for d in daily.values())
    total_t2_only = sum(len(d["t2_only"]) for d in daily.values())
    total_both = sum(len(d["both"]) for d in daily.values())

    lines: list[str] = []
    lines.append(f"# 测试2 量化权重归因分析（{run_date}）\n")
    lines.append(f"> 边界：仅测试2（{start} ~ {end}），25 股票池。本文件由 `paper_trading/quant_attribution.py` 生成，与生产代码完全解耦。\n")
    lines.append("## 分析范围\n")
    lines.append(f"- 信号区间：{start} ~ {end}")
    lines.append(f"- 交易日数（有信号）：{n_days}")
    lines.append(f"- 信号总条数：{n_signals}")
    lines.append("- 框架对比：")
    lines.append(f"  - **测试1（带量化）**：weights q={T1_W_QUANT}/t={T1_W_TECH}/s={T1_W_SENT}，阈值 >{T1_ENTRY_THRESHOLD}")
    lines.append(f"  - **测试2（无量化）**：weights q={T2_W_QUANT}/t={T2_W_TECH}/s={T2_W_SENT}，阈值 >{T2_ENTRY_THRESHOLD}\n")

    lines.append("## 入场决策对比（每日候选数）\n")
    lines.append(f"- 测试1 框架累计候选：**{total_t1}** 次")
    lines.append(f"- 测试2 框架累计候选：**{total_t2}** 次（实际跑的就是这套）")
    lines.append(f"- 两套框架重合：**{total_both}** 次")
    lines.append(f"- **测试1 独有**（带量化才会进的）：**{total_t1_only}** 次")
    lines.append(f"- **测试2 独有**（去量化才放行的）：**{total_t2_only}** 次\n")

    lines.append("## 每日候选明细\n")
    lines.append("| 日期 | T1 候选 | T2 候选 | T1 独有 | T2 独有 |")
    lines.append("|------|---------|---------|---------|---------|")
    for d, info in sorted(daily.items()):
        lines.append(f"| {d} | {','.join(info['t1_entries']) or '—'} "
                     f"| {','.join(info['t2_entries']) or '—'} "
                     f"| {','.join(info['t1_only']) or '—'} "
                     f"| {','.join(info['t2_only']) or '—'} |")
    lines.append("")

    lines.append(f"## 量化分预测力（Spearman ρ vs 后续 {corr.get('fwd_days', '?')} 日收益）\n")
    if corr.get("spearman_rho") is None:
        lines.append(f"- 样本数：{corr.get('n', 0)}（{corr.get('note', '')}）\n")
    else:
        rho = corr["spearman_rho"]
        if abs(rho) < 0.05:
            verdict = "🟡 接近 0 → 量化分无明显预测力，归零有道理"
        elif rho > 0.1:
            verdict = "🟢 正向 → 量化分有信号，值得重新评估权重"
        elif rho < -0.1:
            verdict = "🔴 负向 → 量化分反向（可能存在系统性错误）"
        else:
            verdict = "🟡 弱相关 → 待更多样本"
        lines.append(f"- 样本数 n={corr['n']}，Spearman ρ = **{rho}**")
        lines.append(f"- 解读：{verdict}\n")

    lines.append("## 反事实回放（持仓 PnL 模拟）\n")
    sim = simulate_test1_framework(signals, {})
    lines.append(f"- 状态：{sim.get('status')}")
    lines.append(f"- 说明：{sim.get('note')}\n")

    lines.append("---\n")
    lines.append("_生成命令：`python3 paper_trading/quant_attribution.py`_\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description="测试2 量化权重归因分析（只读，与生产代码解耦）")
    ap.add_argument("--db", default="stock-sage.db", help="SQLite 路径")
    ap.add_argument("--start", default=TEST2_START, help="信号区间起始日（默认测试2 启动日）")
    ap.add_argument("--as-of", default=None, help="截止日（默认今天）")
    ap.add_argument("--fwd-days", type=int, default=5, help="量化分预测力评估的前瞻天数")
    ap.add_argument("--out-dir", default="paper_trading", help="输出目录")
    args = ap.parse_args()

    end = args.as_of or dt.date.today().isoformat()
    run_date = dt.date.today().isoformat()

    print(f"[quant_attribution] 区间 {args.start} ~ {end}，股票池 {len(TEST2_UNIVERSE)} 只")
    signals = load_signals(args.db, args.start, end)
    prices = load_prices(args.db, args.start, end)
    print(f"[quant_attribution] 拉取信号 {len(signals)} 条，价格 {len(prices)} 条")

    daily = compare_daily_entries(signals)
    corr = quant_score_correlation(signals, prices, fwd_days=args.fwd_days)

    out_path = Path(args.out_dir) / f"quant_attribution_{run_date}.md"
    write_report(out_path, run_date, args.start, end, signals, daily, corr)
    print(f"[quant_attribution] 报告写入 {out_path}")


if __name__ == "__main__":
    main()
