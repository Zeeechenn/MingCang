"""
测试1专属信号跑手

使用 test1_legacy_qlib 权重（quant=0.45, tech=0.40, sent=0.15）。
无 LLM 多智能体，纯公式加权聚合。
结果写入 paper_trading/test1_signals.json，不覆盖主 signals 表。

用法（从 stock-sage 根目录执行）：
    PYTHONPATH=. python3 paper_trading/test1_runner.py
"""
from __future__ import annotations
import json
import sys
import logging
from datetime import date as _date
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

# ── 测试1持仓/候选（手动维护，与 test1.md 保持同步）──────────────────────
TEST1_STOCKS = {
    "603986": "兆易创新",
    "300750": "宁德时代",
    "600584": "长电科技",
    "002050": "三花智控",
    "300124": "汇川技术",
}

OUTPUT = Path(__file__).parent / "test1_signals.json"


def _override_to_test1() -> None:
    """把运行时配置强制切到 test1_legacy_qlib，且关闭多智能体。"""
    from backend.config import settings
    settings.paper_trading_profile = "test1_legacy_qlib"
    settings.multi_agent_enabled = False


def run() -> list[dict]:
    _override_to_test1()

    from backend.data.database import SessionLocal
    from backend.data.market import load_price_df
    from backend.data.news import (
        fetch_stock_news_anspire,
        fetch_titles_tavily,
        get_recent_news_items,
    )
    from backend.data.news_audit import audited_titles
    from backend.analysis.technical import technical_score
    from backend.analysis.qlib_engine import qlib_score
    from backend.analysis.sentiment import analyze_news
    from backend.decision.aggregator import aggregate
    from backend.config import settings

    db = SessionLocal()
    results = []

    try:
        for symbol, name in TEST1_STOCKS.items():
            try:
                df = load_price_df(symbol, db, days=200)
                if len(df) < 60:
                    print(f"  ⚠ {symbol} {name}: 数据不足，跳过", file=sys.stderr)
                    continue

                tech = technical_score(df, market="CN")
                close = tech["latest"]["close"]
                atr   = tech["latest"]["atr14"] or 0.0
                date_str = df.index[-1]

                quant_result = qlib_score(df, symbol=symbol, db=db)
                quant = quant_result["score"]

                news_items = get_recent_news_items(symbol, db, hours=24)
                titles, news_audits = audited_titles(news_items)
                if len(titles) < settings.tavily_supplement_threshold:
                    slots = settings.tavily_supplement_threshold - len(titles)
                    limit = min(settings.anspire_news_max_add, max(0, slots))
                    anspire = fetch_stock_news_anspire(symbol, name, limit=limit)
                    if anspire:
                        extra, _ = audited_titles(
                            anspire,
                            min_score=settings.anspire_news_min_score,
                            limit=limit,
                        )
                        titles = titles + extra[:slots]
                if len(titles) < settings.tavily_supplement_threshold:
                    tavily = fetch_titles_tavily(symbol, name)
                    if tavily:
                        titles = titles + tavily

                sentiment_result = analyze_news(titles, symbol=symbol)

                result = aggregate(
                    quant_score=quant,
                    technical_result=tech,
                    sentiment_score=sentiment_result["sentiment"],
                    close=close,
                    atr=atr,
                    sentiment_result=sentiment_result,
                )

                row = {
                    "symbol": symbol,
                    "name": name,
                    "date": date_str,
                    "composite_score": result["composite_score"],
                    "recommendation": result["recommendation"],
                    "quant_score": result["breakdown"]["quant"],
                    "technical_score": result["breakdown"]["technical"],
                    "sentiment_score": result["breakdown"]["sentiment"],
                    "stop_loss": result["stop_loss"],
                    "take_profit": result["take_profit"],
                    "rule_version": result["rule_version"],
                }
                results.append(row)

            except Exception as e:
                print(f"  ✗ {symbol} {name}: {e}", file=sys.stderr)

    finally:
        db.close()

    return results


def print_table(results: list[dict]) -> None:
    if not results:
        print("无结果")
        return
    date_str = results[0]["date"]
    print(f"\n=== 测试1 信号（{date_str}，test1_legacy_qlib: Q×0.45 T×0.40 S×0.15）===\n")
    print(f"{'股票':<18} {'综合':>6} {'建议':<10} {'量化':>6} {'技术':>6} {'情感':>6} {'止损':>8} {'止盈':>8}")
    print("─" * 78)
    for r in sorted(results, key=lambda x: -x["composite_score"]):
        print(
            f"{r['symbol']} {r['name']:<12}"
            f"{r['composite_score']:>+7.1f}"
            f"  {r['recommendation']:<10}"
            f"{r['quant_score']:>+7.1f}"
            f"{r['technical_score']:>+7.1f}"
            f"{r['sentiment_score']:>+7.1f}"
            f"{r['stop_loss']:>9.2f}"
            f"{r['take_profit']:>9.2f}"
        )
    print()


def main() -> None:
    print("跑测试1信号（legacy_qlib，无多智能体）…")
    results = run()
    print_table(results)

    OUTPUT.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"结果已写入 {OUTPUT}")


if __name__ == "__main__":
    main()
