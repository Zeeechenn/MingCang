"""
M4.6 历史信号回填器。

对 [start, end] 内每个活跃股的每个交易日：
  1. 加载 PIT-正确价格（截到 date 当天）
  2. 计算 technical_score / qlib_score
  3. 通过 news_cache 获取 sentiment_result（LLM 调用按需 + 缓存）
  4. 算未来 1~5 个交易日收益率
  → 输出 SignalInput 列表，可直接喂给 compare_paths

不写 Signal 表：避免污染生产数据；输出仅用于 M4.6 回测。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pandas as pd

from backend.backtest.compare_paths import SignalInput
from backend.backtest.news_cache import get_or_backfill

logger = logging.getLogger(__name__)


def _load_price_pit(db, symbol: str, as_of: str, days_back: int = 200) -> pd.DataFrame:
    """按 PIT 切片：取 date <= as_of 的最近 days_back 条 OHLCV"""
    from backend.data.database import Price

    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date <= as_of)
        .order_by(Price.date.desc())
        .limit(days_back)
        .all()
    )
    if not rows:
        return pd.DataFrame()
    rows = list(reversed(rows))   # 升序
    return pd.DataFrame(
        [{"date": r.date, "open": r.open, "high": r.high,
          "low": r.low, "close": r.close, "volume": r.volume}
         for r in rows]
    ).set_index("date")


def _forward_returns(db, symbol: str, as_of: str, entry_close: float, n: int = 5) -> list[float]:
    """取 as_of 之后 n 个交易日的收益率（用 close 对 entry_close）"""
    from backend.data.database import Price

    rows = (
        db.query(Price)
        .filter(Price.symbol == symbol, Price.date > as_of)
        .order_by(Price.date.asc())
        .limit(n)
        .all()
    )
    return [(r.close - entry_close) / entry_close for r in rows]


def generate_input(
    symbol: str, date: str, db,
    *,
    use_llm_news: bool = False,
    market: str = "CN",
) -> SignalInput | None:
    """单点回填：(symbol, date) → SignalInput（无足够数据时返回 None）"""
    from backend.analysis.qlib_engine import qlib_score
    from backend.analysis.technical import technical_score

    df = _load_price_pit(db, symbol, date, days_back=200)
    if len(df) < 60:
        return None

    try:
        tech = technical_score(df, market=market, symbol=symbol)
    except Exception as e:
        logger.debug("technical_score 失败 %s %s: %s", symbol, date, e)
        return None
    close = tech["latest"].get("close")
    atr = tech["latest"].get("atr14") or (close * 0.03 if close else 0.0)
    if close is None:
        return None

    try:
        quant_result = qlib_score(df, symbol=symbol, db=db)
    except Exception as e:
        logger.debug("qlib_score 失败 %s %s: %s", symbol, date, e)
        quant_result = {"score": 0.0, "model": "fallback"}

    sentiment_result = get_or_backfill(symbol, date, db, use_llm=use_llm_news)

    fwd = _forward_returns(db, symbol, date, close, n=5)
    if len(fwd) < 1:
        return None

    return SignalInput(
        symbol=symbol, date=date,
        technical_result=tech,
        qlib_result=quant_result,
        sentiment_result=sentiment_result,
        close=close, atr=atr,
        forward_returns=fwd,
    )


def iter_window(
    start: str, end: str,
    symbols: list[str] | None = None,
    *,
    use_llm_news: bool = False,
    every_n_days: int = 1,
) -> Iterator[SignalInput]:
    """
    迭代生成 [start, end] 内每个 (symbol, date) 的 SignalInput。

    every_n_days=5 时每 5 个交易日采样一次（控制信号密度）。
    """
    from backend.data.database import Price, SessionLocal, Stock

    db = SessionLocal()
    try:
        if symbols is None:
            symbols = [s.symbol for s in db.query(Stock).filter(Stock.active).all()]

        for sym in symbols:
            dates = [
                r[0] for r in
                db.query(Price.date)
                .filter(Price.symbol == sym, Price.date >= start, Price.date <= end)
                .order_by(Price.date.asc())
                .all()
            ]
            sampled = dates[::every_n_days]
            for d in sampled:
                inp = generate_input(sym, d, db, use_llm_news=use_llm_news)
                if inp:
                    yield inp
    finally:
        db.close()


def backfill_window(
    start: str, end: str,
    symbols: list[str] | None = None,
    *,
    use_llm_news: bool = False,
    every_n_days: int = 1,
) -> list[SignalInput]:
    """同 iter_window 但返回 list"""
    return list(iter_window(
        start, end, symbols,
        use_llm_news=use_llm_news,
        every_n_days=every_n_days,
    ))


def main(argv: list[str] | None = None) -> int:
    """CLI: 回填 [start, end] 历史信号 → 跑 compare_paths → 输出对比报告"""
    import argparse
    import json

    from backend.backtest.compare_paths import compare_paths

    ap = argparse.ArgumentParser(description="M4.6 历史信号回填 + 双路径对比")
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default="2026-05-15")
    ap.add_argument("--every-n-days", type=int, default=1,
                    help="每 N 个交易日采样一次（默认每日，5=每周）")
    ap.add_argument("--symbols", nargs="*", help="指定股票代码（默认全活跃股）")
    ap.add_argument("--use-llm-news", action="store_true",
                    help="对 sentiment cache miss 触发 OpenAI 调用回填")
    args = ap.parse_args(argv)

    print(f"# 回填 {args.start} ~ {args.end} every_n_days={args.every_n_days}", flush=True)
    inputs = backfill_window(
        args.start, args.end,
        symbols=args.symbols,
        use_llm_news=args.use_llm_news,
        every_n_days=args.every_n_days,
    )
    print(f"# 生成 {len(inputs)} 个 SignalInput", flush=True)

    if not inputs:
        print(json.dumps({"error": "no_inputs_generated"}, ensure_ascii=False))
        return 1

    report = compare_paths(inputs)
    out = report.to_dict()
    # 新闻覆盖率
    with_events = sum(1 for inp in inputs if inp.sentiment_result.get("key_events"))
    out["news_coverage"] = {
        "total_signals": len(inputs),
        "with_key_events": with_events,
        "coverage_pct": round(with_events / len(inputs) * 100, 1) if inputs else 0.0,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
