"""M26.1 训练股票池扩容工具。

流程：
  1. 从 AkShare 拉取 HS300 + CSI500 成分股列表（共 ~800 支）
  2. 对每支股票，用 AkShare 腾讯接口（绕过代理）回填 5 年日线历史
  3. 若腾讯接口失败，fallback 到 BaoStock（需 pip install baostock）
  4. 新股票写入 stocks 表（active=False，避免影响生产自选股）
  5. 价格数据写入 prices 表，factor 字段同步计算
  6. 完成后打印统计，可直接接 --retrain 用 active+inactive 扩盘股重训 LightGBM

用法（从 mingcang 根目录）：
    PYTHONPATH=. python3 backend/tools/m26_expand_universe.py --dry-run
    PYTHONPATH=. python3 backend/tools/m26_expand_universe.py
    PYTHONPATH=. python3 backend/tools/m26_expand_universe.py --retrain
    PYTHONPATH=. python3 backend/tools/m26_expand_universe.py --symbols 600036,000001
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, timedelta
from typing import TypedDict

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class ExpandStats(TypedDict):
    total: int
    added: int
    skipped: int
    failed: int
    bars_written: int
    sources: dict[str, int]

# ── 常量 ────────────────────────────────────────────────────────────────────
INDICES = ["000300", "000905"]          # HS300 + CSI500
BACKFILL_YEARS = 5
DELAY_BETWEEN_STOCKS = 0.6             # 腾讯接口限速缓冲（秒）
MAX_RETRIES = 3


def _strip_proxy() -> None:
    """从当前进程环境变量中移除代理设置（不修改系统/全局配置）。"""
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "ALL_PROXY", "all_proxy", "ftp_proxy", "FTP_PROXY"]:
        os.environ.pop(key, None)


def _to_tx_symbol(symbol: str) -> str:
    """Convert 6-digit A-share code to sh/sz/bj prefix."""
    if symbol.startswith(("60", "68", "11", "51", "52", "56", "58")):
        return f"sh{symbol}"
    if symbol.startswith(("43", "81", "82", "83", "87", "88", "92")):
        return f"bj{symbol}"
    return f"sz{symbol}"


# ── 第一步：拉取成分股列表 ────────────────────────────────────────────────────

def fetch_index_constituents(index_codes: list[str]) -> dict[str, str]:
    """
    通过 AkShare 拉取多个指数的成分股，返回 {symbol: name}。
    index_stock_cons 只返回代码，名称通过 stock_info_a_code_name 补全。
    """
    _strip_proxy()
    import akshare as ak

    logger.info("拉取指数成分股列表: %s", index_codes)
    all_symbols: set[str] = set()
    for idx in index_codes:
        try:
            df = ak.index_stock_cons(symbol=idx)
            col = "品种代码" if "品种代码" in df.columns else df.columns[0]
            symbols = df[col].astype(str).str.zfill(6).tolist()
            all_symbols.update(symbols)
            logger.info("  %s: %d 支", idx, len(symbols))
        except Exception as e:
            logger.warning("  %s 失败: %s", idx, e)

    # 补全名称
    name_map: dict[str, str] = {}
    try:
        info = ak.stock_info_a_code_name()
        code_col = info.columns[0]
        name_col = info.columns[1]
        name_map = dict(zip(info[code_col].astype(str).str.zfill(6), info[name_col], strict=False))
    except Exception as e:
        logger.warning("stock_info_a_code_name 失败，名称留空: %s", e)

    result = {s: name_map.get(s, "") for s in sorted(all_symbols)}
    logger.info("合并后共 %d 支成分股", len(result))
    return result


# ── 第二步：AkShare 腾讯接口回填（主力，绕过代理）───────────────────────────

def _fetch_via_akshare_tx(symbol: str, days: int) -> pd.DataFrame:
    """
    用 AkShare 腾讯接口拉单股历史日线（绕过代理）。
    返回标准 DataFrame：index=date str，列=open/high/low/close/volume。
    腾讯接口返回 amount（成交额），用 amount/close 推算 volume（成交量代理值）。
    """
    _strip_proxy()
    import akshare as ak

    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    tx_sym = _to_tx_symbol(symbol)

    df = ak.stock_zh_a_hist_tx(symbol=tx_sym, start_date=start,
                                end_date="20500101", adjust="hfq")
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"date": "date", "open": "open", "high": "high",
                             "low": "low", "close": "close", "amount": "amount"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.set_index("date").sort_index()

    for col in ("open", "high", "low", "close", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # amount 是成交额（万元）→ 推算成交量（股）
    if "amount" in df.columns and "close" in df.columns:
        df["volume"] = (df["amount"] * 10000 / df["close"].replace(0, float("nan"))).round(0)
    else:
        df["volume"] = 0.0

    df = df.dropna(subset=["close"])
    return df[["open", "high", "low", "close", "volume"]]


# ── BaoStock fallback ──────────────────────────────────────────────────────

def _fetch_via_baostock(symbol: str, days: int) -> pd.DataFrame:
    """
    BaoStock fallback：完全免费、无限速、历史深度足。
    需要 pip install baostock（约 2MB，无依赖冲突）。
    """
    try:
        import baostock as bs
    except ImportError:
        logger.warning("baostock 未安装，运行: pip install baostock")
        return pd.DataFrame()

    prefix = "sh." if symbol.startswith(("60", "68")) else "sz."
    bs_code = f"{prefix}{symbol}"
    start_str = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_str = date.today().strftime("%Y-%m-%d")

    login_resp = bs.login()
    if login_resp.error_code != "0":
        logger.warning("BaoStock login 失败: %s", login_resp.error_msg)
        return pd.DataFrame()

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_str,
            end_date=end_str,
            frequency="d",
            adjustflag="2",  # 前复权
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=rs.fields)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.set_index("date").sort_index()
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    finally:
        bs.logout()


# ── 带重试的统一拉取入口 ──────────────────────────────────────────────────────

def fetch_stock_history(symbol: str, days: int) -> tuple[pd.DataFrame, str]:
    """返回 (df, source_name)，df 为空表示全部失败。"""
    for attempt in range(MAX_RETRIES):
        try:
            df = _fetch_via_akshare_tx(symbol, days)
            if not df.empty:
                return df, "akshare_tx"
        except Exception as e:
            logger.debug("akshare_tx %s attempt %d: %s", symbol, attempt + 1, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(1.0 * (attempt + 1))

    logger.info("  %s: akshare_tx 全部失败，尝试 BaoStock...", symbol)
    try:
        df = _fetch_via_baostock(symbol, days)
        if not df.empty:
            return df, "baostock"
    except Exception as e:
        logger.warning("  %s: baostock 也失败: %s", symbol, e)

    return pd.DataFrame(), "failed"


# ── 第三步：写入 DB ──────────────────────────────────────────────────────────

def _upsert_stock(db, symbol: str, name: str) -> None:
    """把扩盘股写入 stocks 表，active=False（不影响生产自选股池）。"""
    from backend.data.database import Stock

    existing = db.query(Stock).filter(Stock.symbol == symbol).first()
    if existing:
        return  # 已存在（含生产自选股），不修改 active 状态
    market = "CN"
    db.add(Stock(symbol=symbol, name=name or symbol,
                 market=market, active=False))
    db.commit()


def _write_prices(db, symbol: str, df: pd.DataFrame) -> int:
    """把 df 写入 prices 表（只写 DB 中不存在的日期，用已存在日期集合过滤）。"""
    from backend.analysis.factors import add_all_factors
    from backend.data.database import Price

    # 查该股所有已存在日期，完整过滤避免重复插入（比只看 latest_date 更安全）
    existing_dates: set[str] = {
        r.date for r in db.query(Price.date).filter(Price.symbol == symbol).all()
    }
    if existing_dates:
        df = df[~df.index.isin(existing_dates)]
    if df.empty:
        return 0

    df_f = add_all_factors(df)
    records = []
    for date_str, row in df_f.iterrows():
        atr = row.get("atr14")
        records.append(Price(
            symbol=symbol,
            date=date_str,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
            atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
        ))
    db.bulk_save_objects(records)
    db.commit()
    return len(records)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    symbols: dict[str, str] | None = None,
    dry_run: bool = False,
    retrain: bool = False,
    delay: float = DELAY_BETWEEN_STOCKS,
) -> ExpandStats:
    from backend.data.database import SessionLocal

    if symbols is None:
        symbols = fetch_index_constituents(INDICES)

    db = SessionLocal()
    stats: ExpandStats = {
        "total": len(symbols),
        "added": 0,
        "skipped": 0,
        "failed": 0,
        "bars_written": 0,
        "sources": {},
    }
    days = BACKFILL_YEARS * 365 + 10

    try:
        for i, (symbol, name) in enumerate(symbols.items(), 1):
            logger.info("[%d/%d] %s %s", i, len(symbols), symbol, name)
            if dry_run:
                logger.info("  dry-run，跳过实际拉取")
                continue

            df, source = fetch_stock_history(symbol, days)
            if df.empty:
                logger.warning("  %s: 数据拉取全部失败，跳过", symbol)
                stats["failed"] += 1
                time.sleep(delay)
                continue

            bars = len(df)
            if bars < 60:
                logger.warning("  %s: 数据太短（%d bars），跳过", symbol, bars)
                stats["skipped"] += 1
                time.sleep(delay)
                continue

            _upsert_stock(db, symbol, name)
            written = _write_prices(db, symbol, df)
            stats["added"] += 1
            stats["bars_written"] += written
            stats["sources"][source] = stats["sources"].get(source, 0) + 1
            logger.info("  %s: %d bars 可用，新写入 %d 行 [%s]",
                        symbol, bars, written, source)
            time.sleep(delay)

    finally:
        db.close()

    logger.info("── 扩盘完成 ──────────────────────────────")
    logger.info("总计 %d 支 | 成功 %d | 跳过 %d | 失败 %d | 新写 %d bars",
                stats["total"], stats["added"], stats["skipped"],
                stats["failed"], stats["bars_written"])
    logger.info("数据源分布: %s", stats["sources"])

    if retrain and not dry_run and stats["added"] > 0:
        logger.info("── 开始重训 LightGBM ──────────────────────────────")
        from backend.analysis.qlib_engine import train
        from backend.data.database import SessionLocal as SL2

        db2 = SL2()
        try:
            ok = train(db2, include_inactive=True)
            logger.info("重训结果: %s", "通过 promotion gate ✅" if ok else "未通过 gate ⚠️")
        finally:
            db2.close()

    return stats


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="只拉成分股列表，不写 DB")
    parser.add_argument("--retrain", action="store_true",
                        help="扩盘完成后自动重训 LightGBM")
    parser.add_argument("--symbols", type=str, default=None,
                        help="逗号分隔的自定义股票代码（跳过指数列表）")
    parser.add_argument("--delay", type=float, default=DELAY_BETWEEN_STOCKS,
                        help=f"每支请求间隔秒数（默认 {DELAY_BETWEEN_STOCKS}）")
    parser.add_argument("--indices", type=str, default=",".join(INDICES),
                        help="逗号分隔的指数代码（默认 000300,000905）")
    args = parser.parse_args()

    if args.symbols:
        raw = [s.strip().zfill(6) for s in args.symbols.split(",") if s.strip()]
        symbols = {s: "" for s in raw}
    else:
        indices = [i.strip() for i in args.indices.split(",") if i.strip()]
        symbols = fetch_index_constituents(indices)

    if not symbols:
        logger.error("成分股列表为空，退出")
        return 1

    run(symbols=symbols, dry_run=args.dry_run,
        retrain=args.retrain, delay=args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
