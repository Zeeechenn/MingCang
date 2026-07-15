"""Safely replace only the M67 pilot price histories after an adjustment change."""

from __future__ import annotations

import argparse
import json


def _quality_summary(db, asset_key: str) -> dict:
    from backend.data.database import Price

    rows = (
        db.query(Price)
        .filter(Price.asset_key == asset_key)
        .order_by(Price.date.asc())
        .all()
    )
    worst_return = 0.0
    worst_date = None
    previous = None
    for row in rows:
        close = float(row.close)
        if previous and previous > 0:
            daily_return = close / previous - 1
            if abs(daily_return) > abs(worst_return):
                worst_return = daily_return
                worst_date = row.date
        previous = close
    return {
        "rows": len(rows),
        "first_date": rows[0].date if rows else None,
        "last_date": rows[-1].date if rows else None,
        "sources": sorted({row.source for row in rows if row.source}),
        "adjustments": sorted({row.adjustment for row in rows if row.adjustment}),
        "max_abs_daily_return_pct": round(abs(worst_return) * 100, 4),
        "max_return_date": worst_date,
        "continuity_pass": bool(rows) and abs(worst_return) < 0.5,
    }


def resync(*, years: int = 5) -> dict:
    from backend.data.database import Price, SessionLocal, init_db
    from backend.data.market import backfill_if_needed
    from backend.data.market_profiles import instrument_key
    from backend.tools.m67_gray_bootstrap import PILOT_STOCKS, ensure_pilot_stocks

    init_db()
    db = SessionLocal()
    results = []
    try:
        allowed = set(ensure_pilot_stocks(db))
        for market, symbol, _name, _industry in PILOT_STOCKS:
            asset_key = instrument_key(market, symbol)
            if asset_key not in allowed:
                raise RuntimeError(f"pilot is not gray-allowlisted: {asset_key}")
            deleted = (
                db.query(Price)
                .filter(Price.asset_key == asset_key)
                .delete(synchronize_session=False)
            )
            db.commit()
            try:
                written = backfill_if_needed(symbol, market, db, years=years, refresh_today=False)
                quality = _quality_summary(db, asset_key)
                results.append({
                    "asset_key": asset_key,
                    "deleted": deleted,
                    "written": written,
                    **quality,
                })
            except Exception as exc:
                db.rollback()
                results.append({
                    "asset_key": asset_key,
                    "deleted": deleted,
                    "written": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                })
    finally:
        db.close()
    passed = all(
        row.get("continuity_pass") and row.get("adjustments") == ["forward"]
        for row in results
    )
    return {"status": "pass" if passed else "fail", "years": years, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace M67 pilot price rows only")
    parser.add_argument("--apply", action="store_true", help="Required destructive confirmation")
    parser.add_argument("--years", type=int, default=5)
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing to delete pilot prices without --apply")
    result = resync(years=args.years)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
