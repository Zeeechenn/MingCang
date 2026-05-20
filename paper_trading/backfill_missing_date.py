"""补救脚本：scheduler 缺勤导致的单日数据回填（盘中安全版）

背景：2026-05-19 后端服务/scheduler 未运行 → prices/signals 都缺当日数据。
若现在（盘中）跑生产 backfill_if_needed，会把当日 05-20 的"半成品" K 线
（实时滚动 OHLC）一起写进 prices 表，污染 signals。

本脚本做的：
  1. 拉指定 --date 的日线数据
  2. 严格 filter date <= --date，排除今日盘中脏数据
  3. 用 backend.analysis.factors.add_all_factors 重算 ATR14 等
  4. UPSERT 进 prices 表（只补缺失日期，不覆盖已存在）
  5. 之后由用户单独 invoke job_postmarket() 跑信号
     （或 `python3 -c "from backend.scheduler import job_postmarket; job_postmarket()"`）

边界承诺：
  - 不修改 backend/ 任何文件
  - DB 写入只 INSERT prices 表的缺失行，不 DELETE 任何已存在数据
  - 不动 signals/decision_runs 表（postmarket job 自己写）
  - 脚本放 paper_trading/，不进 backend 调度

用法：
  python3 paper_trading/backfill_missing_date.py --date 2026-05-19
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 添加项目根目录到 sys.path 以便 import backend
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.data.database import SessionLocal, Stock, Price
from backend.data.market import fetch_daily
from backend.analysis.factors import add_all_factors


def backfill_one_symbol(db, symbol: str, market: str, target_date: str,
                        fetch_days: int = 60) -> tuple[int, str]:
    """补一只股票的指定日期数据。返回 (写入条数, 状态说明)。

    target_date: ISO 'YYYY-MM-DD'
    """
    existing = db.query(Price).filter(
        Price.symbol == symbol, Price.date == target_date
    ).first()
    if existing:
        return 0, f"skip(already exists)"

    try:
        df = fetch_daily(symbol, market, days=fetch_days)
    except Exception as e:
        return 0, f"fetch_failed: {e}"

    if df.empty:
        return 0, "empty"

    # 严格截止到 target_date —— 排除任何 > target_date 的脏行（含今日盘中）
    df = df[df.index <= target_date]
    if df.empty:
        return 0, f"no data ≤ {target_date}"

    if target_date not in df.index:
        return 0, f"provider has no data for {target_date} (latest={df.index[-1]})"

    df_factors = add_all_factors(df)
    if target_date not in df_factors.index:
        return 0, f"add_all_factors dropped {target_date}"

    row = df_factors.loc[target_date]
    atr = row.get("atr14")
    import pandas as pd
    price = Price(
        symbol=symbol,
        date=target_date,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
    )
    db.add(price)
    return 1, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description="单日缺失数据回填（盘中安全，不污染当日）")
    ap.add_argument("--date", required=True, help="要补的日期，格式 YYYY-MM-DD")
    ap.add_argument("--symbols", default=None,
                    help="只补指定 symbol（逗号分隔），默认补所有 active 股")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Stock).filter(Stock.active == True)
        if args.symbols:
            wanted = set(args.symbols.split(","))
            q = q.filter(Stock.symbol.in_(wanted))
        stocks = q.all()

        print(f"[backfill] 目标日期 {args.date}，候选股票 {len(stocks)} 只")
        ok = 0
        skipped = 0
        failed = 0
        for s in stocks:
            n, status = backfill_one_symbol(db, s.symbol, s.market, args.date)
            if n > 0:
                ok += 1
                print(f"  ✓ {s.symbol} {s.name}: {status}")
            elif "skip" in status:
                skipped += 1
            else:
                failed += 1
                print(f"  ✗ {s.symbol} {s.name}: {status}")

        db.commit()
        print(f"\n[backfill] 完成：写入 {ok} 行，跳过 {skipped} 行（已存在），失败 {failed} 行")
        print(f"[backfill] 后续步骤：跑 postmarket 信号")
        print(f"  python3 -c \"import sys; sys.path.insert(0,'.'); from backend.scheduler import job_postmarket; job_postmarket()\"")
    finally:
        db.close()


if __name__ == "__main__":
    main()
