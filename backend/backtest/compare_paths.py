"""
M4.6 双路径并排回测：aggregator（旧）vs multi_agent pipeline（新）

设计：
  • 输入：每条 SignalInput（symbol/date/技术/量化/情感原始结果 + 前向价格）
  • 路径 A：aggregate() —— 三路加权（multi_agent_enabled=False 等价路径）
  • 路径 B：aggregate_v2() —— Director → 多轮辩论 → Trader → RiskManager
  • 退出规则：统一 fixed_5d（取信号日 + 5 交易日收盘对比）
  • 对比指标：trades / win_rate / sharpe / profit_loss / total_return / max_drawdown

约束：
  • 默认关闭 LLM（避免重跑成本和噪声）
  • LLM 关闭后辩论降级为 quick_consensus，仍能验证结构性差异
"""
from __future__ import annotations

import statistics
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from backend.backtest.costs import annualized_sharpe, net_return


@dataclass
class SignalInput:
    """单次信号生成的输入快照"""
    symbol: str
    date: str
    technical_result: dict          # technical_score() 输出
    qlib_result: dict               # qlib_score() 输出
    sentiment_result: dict          # analyze_news() 输出
    close: float
    atr: float
    forward_returns: list[float]    # 信号日 +1, +2, ... +N 的收盘价对开盘价的收益率

    def forward_return_at(self, days: int) -> float | None:
        """返回 days 个交易日后的累计收益率（信号日后第 days 天）"""
        if 1 <= days <= len(self.forward_returns):
            return self.forward_returns[days - 1]
        return None


@dataclass
class PathMetrics:
    path_name: str
    trades: int
    wins: int
    losses: int
    win_rate: float                 # %
    avg_return: float               # %
    sharpe: float
    profit_loss: float | None       # 平均盈利 / 平均亏损
    total_return: float             # %
    max_drawdown: float             # %（基于累计权益曲线）
    entry_signal_count: int = 0     # ENTRY 信号数（trades 的母集）
    notes: list[str] = field(default_factory=list)


@dataclass
class ComparisonReport:
    path_a: PathMetrics
    path_b: PathMetrics
    delta: dict                     # path_b - path_a 关键指标差值
    recommendation: str             # 继续推进 M4 / 暂停 M4 / 需要更多数据
    rationale: str

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return {
            "path_a": asdict(self.path_a),
            "path_b": asdict(self.path_b),
            "delta": self.delta,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
        }


@contextmanager
def _no_llm_settings():
    """暂时关闭多轮辩论 + 单轮辩论 + 长期团硬约束。
    长期团关闭原因：回测无法获得历史 long_term_label，
    否则 risk_manager 会把"可小仓试错"全部降级，path_b 无 ENTRY 信号。
    API key 临时清空：阻止 aggregate_v2 内 fallback 单轮 LLM 辩论（460 信号 × 30% 分歧
    ≈ 138 次 OpenAI 调用，太慢）。
    """
    from backend.config import settings
    saved = {
        "multi_round_debate_enabled": settings.multi_round_debate_enabled,
        "long_term_team_enabled": settings.long_term_team_enabled,
        "anthropic_api_key": settings.anthropic_api_key,
        "openai_api_key": settings.openai_api_key,
    }
    settings.multi_round_debate_enabled = False
    settings.long_term_team_enabled = False
    settings.anthropic_api_key = ""
    settings.openai_api_key = ""
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


def _path_a(inp: SignalInput) -> dict:
    """旧 aggregator 单路（三路加权）"""
    from backend.decision.aggregator import aggregate
    return aggregate(
        quant_score=inp.qlib_result.get("score", 0.0),
        technical_result=inp.technical_result,
        sentiment_score=inp.sentiment_result.get("sentiment", 0.0),
        close=inp.close,
        atr=inp.atr,
        sentiment_result=inp.sentiment_result,
    )


def _path_b(inp: SignalInput) -> dict:
    """新 multi-Agent pipeline（aggregate_v2）"""
    from backend.decision.aggregator import aggregate_v2
    return aggregate_v2(
        quant_result=inp.qlib_result,
        technical_result=inp.technical_result,
        sentiment_result=inp.sentiment_result,
        close=inp.close,
        atr=inp.atr,
    )


def _exit_logic_5d(inp: SignalInput) -> float:
    """统一退出：T+5 收盘价对入场价的净收益率。"""
    r = inp.forward_return_at(5)
    return net_return(r if r is not None else 0.0)


def _max_drawdown(returns: Sequence[float]) -> float:
    """累计权益曲线的最大回撤（%）"""
    if not returns:
        return 0.0
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    peak = equity[0]
    mdd = 0.0
    for v in equity[1:]:
        peak = max(peak, v)
        dd = (v - peak) / peak
        mdd = min(mdd, dd)
    return round(mdd * 100, 2)


def _compute_metrics(path_name: str, trade_returns: list[float], n_entry: int) -> PathMetrics:
    """从单笔交易收益率列表汇总指标"""
    if not trade_returns:
        return PathMetrics(
            path_name=path_name, trades=0, wins=0, losses=0,
            win_rate=0.0, avg_return=0.0, sharpe=0.0,
            profit_loss=None, total_return=0.0, max_drawdown=0.0,
            entry_signal_count=n_entry,
            notes=["路径无 ENTRY 信号产生"] if n_entry == 0 else ["所有信号 0 收益"],
        )

    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]
    mean = statistics.mean(trade_returns)
    sharpe = annualized_sharpe(trade_returns, avg_hold_days=5)
    pl = (
        statistics.mean(wins) / abs(statistics.mean(losses))
        if wins and losses and statistics.mean(losses) != 0
        else None
    )
    total = 1.0
    for r in trade_returns:
        total *= 1 + r
    return PathMetrics(
        path_name=path_name,
        trades=len(trade_returns),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(trade_returns) * 100, 1),
        avg_return=round(mean * 100, 2),
        sharpe=round(sharpe, 2),
        profit_loss=round(pl, 2) if pl is not None else None,
        total_return=round((total - 1) * 100, 2),
        max_drawdown=_max_drawdown(trade_returns),
        entry_signal_count=n_entry,
    )


def _is_entry(rec: str) -> bool:
    from backend.decision.signal_policy import is_entry_signal
    return is_entry_signal(rec, include_legacy=True)


def simulate_path(
    path_name: str,
    path_fn,
    inputs: Sequence[SignalInput],
) -> PathMetrics:
    """对所有输入跑指定路径，收集 ENTRY 信号的 T+5 收益率"""
    trade_returns: list[float] = []
    n_entry = 0
    for inp in inputs:
        try:
            result = path_fn(inp)
        except Exception:
            continue
        if _is_entry(result.get("recommendation", "")):
            n_entry += 1
            r = _exit_logic_5d(inp)
            trade_returns.append(r)
    return _compute_metrics(path_name, trade_returns, n_entry)


def _generate_recommendation(a: PathMetrics, b: PathMetrics) -> tuple[str, str]:
    """根据对比结果给出 M4.4/M4.5 推进建议"""
    if a.trades < 10 and b.trades < 10:
        return (
            "数据不足",
            f"path_a 仅 {a.trades} 笔、path_b 仅 {b.trades} 笔，"
            f"需 ≥10 笔才能得出结论。建议先回填 signal 输入快照",
        )
    sharpe_delta = b.sharpe - a.sharpe
    win_delta = b.win_rate - a.win_rate
    dd_delta = b.max_drawdown - a.max_drawdown   # 注意 max_drawdown 是负数，正向 delta 表示回撤减轻

    # 决策规则
    if sharpe_delta > 0.3 and dd_delta > -2.0:
        return (
            "继续推进 M4.4 / M4.5",
            f"multi_agent 路径 Sharpe 提升 {sharpe_delta:+.2f}，"
            f"胜率 {win_delta:+.1f}%，回撤 {dd_delta:+.2f}pp，"
            f"结构性收益明显",
        )
    if sharpe_delta < -0.2 or (win_delta < -5.0 and dd_delta < -2.0):
        return (
            "暂停 M4.4 / M4.5",
            f"multi_agent 路径 Sharpe 变化 {sharpe_delta:+.2f}，"
            f"胜率 {win_delta:+.1f}%，回撤 {dd_delta:+.2f}pp，"
            f"未见结构性优势",
        )
    return (
        "条件性推进 M4.4 / M4.5",
        f"指标差异不显著（Sharpe {sharpe_delta:+.2f}, 胜率 {win_delta:+.1f}%）。"
        f"建议先做 M4.4 增强辩论质量，再观察",
    )


def compare_paths(inputs: Sequence[SignalInput]) -> ComparisonReport:
    """主入口：跑两条路径并生成对比报告"""
    with _no_llm_settings():
        a = simulate_path("aggregator_v1", _path_a, inputs)
        b = simulate_path("multi_agent_v2", _path_b, inputs)

    delta = {
        "trades": b.trades - a.trades,
        "sharpe": round(b.sharpe - a.sharpe, 2),
        "win_rate": round(b.win_rate - a.win_rate, 1),
        "avg_return": round(b.avg_return - a.avg_return, 2),
        "total_return": round(b.total_return - a.total_return, 2),
        "max_drawdown": round(b.max_drawdown - a.max_drawdown, 2),
    }
    rec, why = _generate_recommendation(a, b)
    return ComparisonReport(
        path_a=a, path_b=b, delta=delta,
        recommendation=rec, rationale=why,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: 从 Signal 表读取已有信号 + Price 表生成 forward returns → 跑对比。

    注意：当前 Signal 表只存 score 不存原始 input dict，
    所以 CLI 跑出来的两路结果会一致（输入相同 → 输出相同）。
    实际验证需要离线回填 input snapshots（见 docs/M4_BACKTEST.md）。
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description="M4.6 多Agent 双路径并排回测")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-05-15")
    ap.add_argument("--limit", type=int, default=200,
                    help="最多取多少条信号（默认 200）")
    ap.add_argument("--backfill-news", action="store_true",
                    help="对 cache miss 的信号调 analyze_news() LLM 回填 key_events")
    ap.add_argument("--no-cache", action="store_true",
                    help="忽略 news_cache，sentiment 全部来自 Signal.sentiment_score")
    args = ap.parse_args(argv)

    inputs = _load_inputs_from_db(
        args.start, args.end, args.limit,
        use_news_cache=not args.no_cache,
        backfill_llm=args.backfill_news,
    )
    if not inputs:
        print(json.dumps({
            "error": "no_signals_in_range",
            "hint": "Signal 表为空或时间段无数据，请先生成信号",
        }, ensure_ascii=False, indent=2))
        return 1
    report = compare_paths(inputs)
    out = report.to_dict()
    # 报告新闻覆盖率
    with_events = sum(1 for inp in inputs if inp.sentiment_result.get("key_events"))
    out["news_coverage"] = {
        "total_signals": len(inputs),
        "with_key_events": with_events,
        "coverage_pct": round(with_events / len(inputs) * 100, 1) if inputs else 0.0,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _load_inputs_from_db(
    start: str, end: str, limit: int,
    *,
    use_news_cache: bool = True,
    backfill_llm: bool = False,
) -> list[SignalInput]:
    """
    从 Signal + Price + NewsItem 表重建 SignalInput。

    use_news_cache=True 时优先读 news_cache（task 1 回填的 key_events）。
    backfill_llm=True 时 cache miss 触发 analyze_news() LLM 调用并写回。
    """
    from backend.backtest.news_cache import get_or_backfill
    from backend.data.database import Price, SessionLocal, Signal
    db = SessionLocal()
    try:
        signals = (
            db.query(Signal)
            .filter(Signal.date >= start, Signal.date <= end)
            .order_by(Signal.date.asc())
            .limit(limit)
            .all()
        )
        out: list[SignalInput] = []
        for s in signals:
            prices = (
                db.query(Price)
                .filter(Price.symbol == s.symbol, Price.date >= s.date)
                .order_by(Price.date.asc())
                .limit(6)
                .all()
            )
            if len(prices) < 2:
                continue
            # M18.2 入场价滞后：信号在 bar 0 收盘生成，实际在 bar 1 开盘入场
            # （不能用同 bar 收盘，否则隐含未来信息 / 不可成交价）
            entry = prices[1].open
            fwd = [(p.close - entry) / entry for p in prices[1:]]
            tech = {
                "score": s.technical_score or 0.0,
                "raw_score": s.technical_score or 0.0,
                "adx_factor": 1.0,
                "latest": {},
                "limit": {},
            }
            qlib = {"score": s.quant_score or 0.0, "model": "historical"}

            # 优先用回填缓存，否则退回到 Signal 表里的 sentiment_score
            if use_news_cache:
                sent = get_or_backfill(s.symbol, s.date, db, use_llm=backfill_llm)
                # 缓存命中后用真实 sentiment + key_events，保持 sentiment_score 一致
                if sent.get("summary") in ("cache miss",):
                    sent = {
                        "sentiment": (s.sentiment_score or 0.0) / 100.0,
                        "impact": "short", "key_events": [], "summary": "",
                    }
            else:
                sent = {
                    "sentiment": (s.sentiment_score or 0.0) / 100.0,
                    "impact": "short", "key_events": [], "summary": "",
                }

            out.append(SignalInput(
                symbol=s.symbol, date=s.date,
                technical_result=tech, qlib_result=qlib,
                sentiment_result=sent,
                close=entry, atr=prices[0].atr14 or entry * 0.03,
                forward_returns=fwd,
            ))
        return out
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
