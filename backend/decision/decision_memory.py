"""
决策记忆模块：持久化每次信号，下次分析同一股票时注入历史复盘。
类似 TradingAgents 的 decision log + reflection 机制。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.decision.signal_policy import is_entry_signal

MEMORY_DIR = Path.home() / ".stock-sage" / "memory"
_HEADER = "| 日期 | 建议 | 综合分 | 止盈 | 止损 | LLM偏向 |\n|------|------|--------|------|------|--------|\n"


def save_decision(symbol: str, date: str, signal: dict) -> None:
    """将信号追加到 ~/.stock-sage/memory/<symbol>.md"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = MEMORY_DIR / f"{symbol}.md"
    bias = signal.get("llm_arbitration", {}).get("action_bias", "-")
    row = (
        f"| {date} | {signal['recommendation']} | {signal['composite_score']:+.0f} "
        f"| {signal['take_profit']:.2f} | {signal['stop_loss']:.2f} | {bias} |\n"
    )
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(f"# {symbol} 决策记忆\n\n{_HEADER}", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(row)


def get_reflection_context(symbol: str, db, lookback_days: int = 30) -> str:
    """
    读取该股过去 lookback_days 天的历史信号，与实际价格对比，生成反思文本。
    注入到多空辩论 prompt，帮助 LLM 从历史复盘中修正偏差。
    无历史数据时返回空字符串。
    """
    from backend.data.database import Price, Signal  # 延迟导入避免循环依赖

    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    past_signals = (
        db.query(Signal)
        .filter(Signal.symbol == symbol, Signal.date >= cutoff)
        .order_by(Signal.date.desc())
        .limit(5)
        .all()
    )
    if not past_signals:
        return ""

    lines: list[str] = []
    for sig in past_signals:
        # 信号当日收盘价
        sig_row = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date == sig.date)
            .first()
        )
        # 信号后首个可用交易日收盘价
        next_row = (
            db.query(Price.close)
            .filter(Price.symbol == symbol, Price.date > sig.date)
            .order_by(Price.date.asc())
            .first()
        )

        if sig_row and next_row and sig_row[0]:
            pct = (next_row[0] - sig_row[0]) / sig_row[0] * 100
            # 判断实际结果与建议是否一致
            bullish_rec = is_entry_signal(sig.recommendation, include_legacy=True)
            correct = (bullish_rec and pct > 0) or (not bullish_rec and pct < 0)
            verdict = "✓ 方向正确" if correct else "✗ 方向有误"
            outcome = f"实际 {pct:+.1f}%（{verdict}）"
        else:
            outcome = "尚无后续数据"

        lines.append(
            f"- {sig.date}: 建议{sig.recommendation}(综合分{sig.composite_score:+.0f}) → {outcome}"
        )

    return "【历史决策复盘（供参考，不作为主要依据）】\n" + "\n".join(lines) + "\n"
