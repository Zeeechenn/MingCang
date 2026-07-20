"""M69: audit (and, on explicit request, repair) stale adjustment bases in ``prices``.

Why this exists
---------------
``backfill_if_needed`` only ever appends rows newer than what the DB already
holds.  When a provider re-bases a series — an A-share cash dividend shifts the
whole pre-ex history down under forward adjustment — the already-stored rows keep
the *old* basis while every subsequently appended bar carries the *new* one.  The
series then contains a seam that nothing downstream can see:

  * P&L computed as (new close - stored entry) is wrong by the dividend;
  * stop-loss / take-profit levels recorded pre-seam sit on the other basis, so
    "did we breach the stop" answers change;
  * ATR is inflated because the seam day gets a fake True Range.

600900 on 2026-07-15 carried exactly this: a 0.79 offset, invisible to the
existing 3x ratio guard in ``price_quality.check_adjustment_basis_jump``.

Audit is read-only and safe to run any time.  ``--apply`` rewrites history and is
deliberately opt-in per symbol: these rows back a real-money ledger, and the
recorded entry/stop/target levels in ``live_trading/LIVE.md`` and
``paper_trading/test2.md`` are on the OLD basis — re-basing the DB without also
restating those makes the ledger disagree with the data.  Read the printed
summary and restate the ledger in the same change.

Usage::

    python3 -m backend.tools.rebase_price_history --symbols 600900,600547
    python3 -m backend.tools.rebase_price_history --universe live_trading/live_universe.json
    python3 -m backend.tools.rebase_price_history --symbols 600900 --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger("backend.tools.rebase_price_history")


@dataclass
class SymbolAudit:
    symbol: str
    status: str          # "clean" | "drift" | "skipped"
    detail: str
    payload: dict | None = None


def _load_symbols(args) -> list[str]:
    if args.symbols:
        return [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.universe:
        with open(args.universe, encoding="utf-8") as fh:
            return [s["symbol"] for s in json.load(fh)["stocks"]]
    raise SystemExit("需要 --symbols 或 --universe")


def audit_symbol(symbol: str, market: str, db, *, days: int) -> SymbolAudit:
    """Fetch a fresh window and compare it against stored closes. Read-only."""
    from backend.data.database import Price
    from backend.data.market import fetch_daily
    from backend.data.market_profiles import instrument_key, normalize_market, normalize_symbol
    from backend.data.price_quality import detect_adjustment_basis_drift

    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    asset_key = instrument_key(market, symbol)

    try:
        df = fetch_daily(symbol, market, days=days)
    except Exception as exc:
        return SymbolAudit(symbol, "skipped", f"抓取失败: {exc}")
    if df is None or df.empty:
        return SymbolAudit(symbol, "skipped", "provider 返回空")

    fetched = {
        str(day): float(row["close"])
        for day, row in df.iterrows()
        if row.get("close") is not None
    }
    stored_rows = (
        db.query(Price.date, Price.close)
        .filter(Price.asset_key == asset_key, Price.date.in_(list(fetched)))
        .all()
    )
    stored = {r.date: float(r.close) for r in stored_rows if r.close}
    if len(stored) < 3:
        return SymbolAudit(symbol, "skipped", f"重叠行仅 {len(stored)} 条，不足以判定")

    drift = detect_adjustment_basis_drift(fetched, stored)
    if not drift.detected:
        return SymbolAudit(symbol, "clean", f"重叠 {drift.compared_rows} 行全部一致")
    return SymbolAudit(symbol, "drift", drift.describe(), drift.to_payload())


def repair_symbol(symbol: str, market: str, db, *, days: int) -> str:
    """Re-fetch and overwrite the whole compared window so one basis governs it."""
    from backend.analysis.factors import add_all_factors
    from backend.data.database import Price
    from backend.data.market import fetch_daily
    from backend.data.market_profiles import (
        get_market_profile,
        instrument_key,
        normalize_market,
        normalize_symbol,
    )

    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    asset_key = instrument_key(market, symbol)
    profile = get_market_profile(market)

    df = fetch_daily(symbol, market, days=days)
    if df is None or df.empty:
        return "provider 返回空，未改动"

    df_factors = add_all_factors(df)
    dates = [str(d) for d in df_factors.index]
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")

    deleted = (
        db.query(Price)
        .filter(Price.asset_key == asset_key, Price.date.in_(dates))
        .delete(synchronize_session=False)
    )
    import pandas as pd

    records = []
    for date_str, row in df_factors.iterrows():
        atr = row.get("atr14")
        records.append(Price(
            symbol=symbol,
            asset_key=asset_key,
            market=market,
            currency=profile.currency,
            date=str(date_str),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
            source=source,
            fetched_at=fetched_at,
            adjustment=adjustment,
        ))
    db.bulk_save_objects(records)
    db.commit()
    return f"重写 {len(records)} 行（删除 {deleted} 行旧基准），统一到 provider 当前基准"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="M69 复权基准漂移审计/修复")
    p.add_argument("--symbols", help="逗号分隔股票代码")
    p.add_argument("--universe", help="股票池 JSON 路径")
    p.add_argument("--market", default="CN")
    p.add_argument("--days", type=int, default=120, help="比对窗口天数（默认 120）")
    p.add_argument("--apply", action="store_true",
                   help="对检出漂移的标的重写历史。默认只审计不改库。")
    args = p.parse_args(argv)

    from backend.data.database import SessionLocal

    symbols = _load_symbols(args)
    db = SessionLocal()
    audits: list[SymbolAudit] = []
    try:
        for sym in symbols:
            audit = audit_symbol(sym, args.market, db, days=args.days)
            audits.append(audit)
            mark = {"clean": "✅", "drift": "⚠️", "skipped": "—"}[audit.status]
            print(f"{mark} {audit.symbol}: {audit.detail}")

        drifted = [a for a in audits if a.status == "drift"]
        print(f"\n审计 {len(audits)} 支：干净 {sum(1 for a in audits if a.status=='clean')} · "
              f"漂移 {len(drifted)} · 跳过 {sum(1 for a in audits if a.status=='skipped')}")

        if drifted and not args.apply:
            print("\n⚠️ 检出漂移但未改库（默认只审计）。确认后加 --apply 重写。")
            print("   注意：台账里记录的建仓价/止损/止盈是旧基准，重基后必须同步重述，"
                  "否则台账与数据互相打架。")
        elif drifted and args.apply:
            print("\n开始重写…")
            for a in drifted:
                msg = repair_symbol(a.symbol, args.market, db, days=args.days)
                print(f"  {a.symbol}: {msg}")
        return 1 if drifted and not args.apply else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
