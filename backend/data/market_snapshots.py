"""市值 / 融资余额日频快照拉取与写库

为 LightGBM Alpha 模型补齐 market_snapshots 表的增量特征。

字段说明：
  - market_cap, shares_outstanding：来自东方财富 datacenter RZRQ 报表的 SZ 字段
    （总市值）。shares_outstanding = SZ / close 倒推。
  - float_market_cap：当前数据源没有独立流通市值历史，统一沿用 market_cap
    （写入相同值），模型侧会自动剔除冗余。
  - margin_balance：东方财富 RZRQ 报表 RZYE。
  - north_net_buy：个股口径在 2024-08 后政策变更不再公开，写 NULL；
    qlib_data.FEATURE_COLS 已剔除。
  - large_order_net_inflow：fflow daykline 端点在 Clash TUN 环境下返回空体，
    本机无法稳定抓取；写 NULL，qlib_data.FEATURE_COLS 已剔除。

只走 datacenter-web.eastmoney.com，与 backend/data/market.py 同样用 curl
绕开 Clash TUN 与 requests/SSL 的握手问题。
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import text

from backend.data.database import Price, Stock

logger = logging.getLogger(__name__)

_CURL_TIMEOUT = "15"
_RETRY_ATTEMPTS = 3
_RETRY_BASE_SLEEP = 1.5


def _curl_json(url: str) -> dict | None:
    """curl + JSON 解析，失败返回 None。带指数退避重试。"""
    last_err = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", _CURL_TIMEOUT,
                 "-H", "Referer: https://data.eastmoney.com/",
                 "-H", "User-Agent: Mozilla/5.0",
                 url],
                capture_output=True, text=True,
            )
            if result.returncode != 0 or not result.stdout:
                last_err = f"curl rc={result.returncode} stderr={result.stderr[:100]}"
            else:
                return json.loads(result.stdout)
        except Exception as e:
            last_err = str(e)
        if attempt < _RETRY_ATTEMPTS - 1:
            time.sleep(_RETRY_BASE_SLEEP * (2 ** attempt))
    logger.debug("curl_json giving up after %d attempts: %s | %s", _RETRY_ATTEMPTS, last_err, url[:120])
    return None


def _cn_secid(symbol: str) -> str:
    """East Money secid prefix: 1=SH (60/68/11), 0=SZ otherwise."""
    return f"1.{symbol}" if symbol[:2] in ("60", "68", "11") else f"0.{symbol}"


# ---------------------------------------------------------------------------
# Provider: 融资余额 + 总市值（per-stock 完整历史）
# ---------------------------------------------------------------------------

def fetch_margin_history(symbol: str, page_size: int = 500) -> pd.DataFrame:
    """返回 DataFrame[date, margin_balance, market_cap_from_rzrq]。

    使用 datacenter-web.eastmoney.com 的 RPTA_WEB_RZRQ_GGMX 报表，
    SCODE 过滤即可拿全历史，pageSize=500 一次性覆盖约 2 年交易日。
    若该股不在融资融券标的池，返回空 DataFrame。
    """
    all_rows: list[dict] = []
    page = 1
    while True:
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?reportName=RPTA_WEB_RZRQ_GGMX"
            "&columns=DATE,SCODE,RZYE,SZ"
            f"&filter=(scode%3D%22{symbol}%22)"
            f"&pageNumber={page}&pageSize={page_size}"
            "&sortColumns=date&sortTypes=-1"
        )
        data = _curl_json(url)
        if not data or not data.get("success"):
            break
        result = data.get("result") or {}
        data_rows = result.get("data") or []
        if not data_rows:
            break
        for r in data_rows:
            dt = (r.get("DATE") or "")[:10]
            if not dt:
                continue
            all_rows.append({
                "date": dt,
                "margin_balance": float(r["RZYE"]) if r.get("RZYE") is not None else None,
                "market_cap_from_rzrq": float(r["SZ"]) if r.get("SZ") is not None else None,
            })
        total_pages = int(result.get("pages") or 1)
        if page >= total_pages:
            break
        page += 1
    return pd.DataFrame(all_rows)


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def build_snapshots_for_symbol(
    symbol: str,
    db,
    since: str | None = None,
) -> int:
    """为单只股票计算并 upsert 全部 market_snapshots 行，返回写入条数。

    since: ISO date 字符串，仅 upsert 该日之后（含）的快照；None 表示全量。
    """
    price_rows = db.query(Price.date, Price.close).filter(Price.symbol == symbol)
    if since:
        price_rows = price_rows.filter(Price.date >= since)
    price_rows = price_rows.order_by(Price.date).all()
    if not price_rows:
        return 0
    prices = pd.DataFrame([{"date": r.date, "close": r.close} for r in price_rows])

    margin = fetch_margin_history(symbol)
    if not margin.empty and since:
        margin = margin[margin["date"] >= since]

    merged = prices.merge(margin, on="date", how="left")
    merged["market_cap"] = merged.get("market_cap_from_rzrq")
    # 没有独立流通市值源 → 沿用总市值，模型侧会自动剔除冗余特征
    merged["float_market_cap"] = merged["market_cap"]
    # SZ / close 倒推总股本（每日刷新，自然覆盖送转/增发引发的变动）
    merged["shares_outstanding"] = merged["market_cap"] / merged["close"]

    # upsert via raw SQL（ORM bulk + UniqueConstraint 在 SQLite 上不友好）
    written = 0
    with db.bind.begin() as conn:
        for _, row in merged.iterrows():
            payload = {
                "symbol": symbol,
                "date": row["date"],
                "market_cap": _none_if_nan(row.get("market_cap")),
                "float_market_cap": _none_if_nan(row.get("float_market_cap")),
                "shares_outstanding": _none_if_nan(row.get("shares_outstanding")),
                "north_net_buy": None,  # 见模块文档，不抓取
                "margin_balance": _none_if_nan(row.get("margin_balance")),
                "large_order_net_inflow": None,  # 见模块文档，不抓取
                "source": "eastmoney_rzrq",
                "fetched_at": datetime.now(UTC).replace(tzinfo=None),
            }
            conn.execute(text("""
                INSERT INTO market_snapshots
                  (symbol, date, market_cap, float_market_cap, shares_outstanding,
                   north_net_buy, margin_balance, large_order_net_inflow,
                   source, fetched_at)
                VALUES
                  (:symbol, :date, :market_cap, :float_market_cap, :shares_outstanding,
                   :north_net_buy, :margin_balance, :large_order_net_inflow,
                   :source, :fetched_at)
                ON CONFLICT(symbol, date) DO UPDATE SET
                  market_cap = excluded.market_cap,
                  float_market_cap = excluded.float_market_cap,
                  shares_outstanding = excluded.shares_outstanding,
                  margin_balance = excluded.margin_balance,
                  large_order_net_inflow = excluded.large_order_net_inflow,
                  source = excluded.source,
                  fetched_at = excluded.fetched_at
            """), payload)
            written += 1
    return written


def _none_if_nan(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def backfill_all_snapshots(db, since: str = "2024-01-01") -> dict:
    """为所有 active 自选股回填快照，返回统计 dict。"""
    stocks = db.query(Stock).filter(Stock.active, Stock.market == "CN").all()
    summary: dict[str, Any] = {
        "total": len(stocks),
        "ok": 0,
        "skipped": 0,
        "rows_written": 0,
        "failures": [],
    }
    for i, s in enumerate(stocks, 1):
        try:
            n = build_snapshots_for_symbol(s.symbol, db, since=since)
            if n > 0:
                summary["ok"] += 1
                summary["rows_written"] += n
            else:
                summary["skipped"] += 1
            logger.info("[%d/%d] %s — wrote %d snapshot rows", i, len(stocks), s.symbol, n)
        except Exception as e:
            summary["failures"].append({"symbol": s.symbol, "error": str(e)})
            logger.warning("[%d/%d] %s — failed: %s", i, len(stocks), s.symbol, e)
    return summary


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true", help="回填全部 active 自选股")
    p.add_argument("--symbol", type=str, help="只回填单只股")
    p.add_argument("--since", type=str, default="2024-01-01", help="起始日期 YYYY-MM-DD")
    args = p.parse_args()

    from backend.data.database import SessionLocal
    db = SessionLocal()
    try:
        if args.symbol:
            n = build_snapshots_for_symbol(args.symbol, db, since=args.since)
            print(f"{args.symbol}: {n} rows")
        elif args.backfill:
            summary = backfill_all_snapshots(db, since=args.since)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            p.print_help()
    finally:
        db.close()
