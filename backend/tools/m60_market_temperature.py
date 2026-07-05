"""Observe-only M60 market temperature snapshots from Eastmoney board pools."""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from typing import Any

import requests

from backend.data.category_fetchers import EASTMONEY_QUOTE_HEADERS, SharedThrottle
from backend.data.database import Base, MarketTemperatureSnapshot, SessionLocal
from backend.data.orm import _utcnow

EASTMONEY_ZT_POOL_URL = "https://push2ex.eastmoney.com/getTopicZTPool"
EASTMONEY_ZB_POOL_URL = "https://push2ex.eastmoney.com/getTopicZBPool"
EASTMONEY_YZT_POOL_URL = "https://push2ex.eastmoney.com/getYesterdayZTPool"
EASTMONEY_POOL_UT = "7eea3edcaed734bea9cbfc24409ed989"
_EASTMONEY_THROTTLE = SharedThrottle()


def _date_arg(value: str | date | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_pool(url: str, snap_date: date, sort: str) -> list[dict[str, Any]]:
    _EASTMONEY_THROTTLE.wait()
    response = requests.get(
        url,
        params={
            "ut": EASTMONEY_POOL_UT,
            "dpt": "wz.ztzt",
            "date": snap_date.strftime("%Y%m%d"),
            "Pageindex": 0,
            "pagesize": 10000,
            "sort": sort,
        },
        headers=EASTMONEY_QUOTE_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    pool = data.get("pool") if isinstance(data, dict) else None
    if not isinstance(pool, list):
        raise ValueError("eastmoney market temperature missing data.pool")
    return [item for item in pool if isinstance(item, dict)]


def _snapshot_row(item: dict[str, Any], pool_type: str, snap_date: date, fetched_at: datetime) -> dict[str, Any] | None:
    code = str(item.get("c") or item.get("code") or "").strip()
    if not code:
        return None
    price_raw = _to_float(item.get("p"))
    return {
        "snap_date": datetime.combine(snap_date, datetime.min.time()),
        "pool_type": pool_type,
        "code": code,
        "name": str(item.get("n") or item.get("name") or "").strip() or None,
        "price": None if price_raw is None else price_raw / 1000.0,
        "fields_json": json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
        "fetched_at": fetched_at,
        "raw": item,
    }


def _save_snapshot_rows(rows: list[dict[str, Any]], db) -> int:
    inserted = 0
    for row in rows:
        existing = (
            db.query(MarketTemperatureSnapshot)
            .filter(
                MarketTemperatureSnapshot.snap_date == row["snap_date"],
                MarketTemperatureSnapshot.pool_type == row["pool_type"],
                MarketTemperatureSnapshot.code == row["code"],
            )
            .first()
        )
        if existing:
            continue
        db.add(
            MarketTemperatureSnapshot(
                snap_date=row["snap_date"],
                pool_type=row["pool_type"],
                code=row["code"],
                name=row.get("name"),
                price=row.get("price"),
                fields_json=row["fields_json"],
                fetched_at=row.get("fetched_at") or _utcnow(),
            )
        )
        inserted += 1
    db.commit()
    return inserted


def _summary(rows: list[dict[str, Any]], snap_date: date) -> dict[str, Any]:
    zt_count = sum(1 for row in rows if row["pool_type"] == "zt")
    zb_count = sum(1 for row in rows if row["pool_type"] == "zb")
    yzt_changes = [
        _to_float(row["raw"].get("zdp"))
        for row in rows
        if row["pool_type"] == "yzt" and _to_float(row["raw"].get("zdp")) is not None
    ]
    denominator = zt_count + zb_count
    avg_chg = sum(yzt_changes) / len(yzt_changes) if yzt_changes else None
    return {
        "snap_date": snap_date.isoformat(),
        "limit_up_count": zt_count,
        "failed_limit_up_count": zb_count,
        "failed_limit_up_rate": None if denominator == 0 else zb_count / denominator,
        "yesterday_limit_up_avg_chg_pct": avg_chg,
        "consecutive_limit_height": None,
    }


def capture_market_temperature_snapshot(snap_date: str | date | None = None, db=None) -> dict[str, Any]:
    day = _date_arg(snap_date)
    owned_session = db is None
    session = db or SessionLocal()
    try:
        Base.metadata.create_all(bind=session.get_bind())
        fetched_at = _utcnow()
        pools = (
            ("zt", EASTMONEY_ZT_POOL_URL, "fbt:asc"),
            ("zb", EASTMONEY_ZB_POOL_URL, "fbt:asc"),
            ("yzt", EASTMONEY_YZT_POOL_URL, "zs:desc"),
        )
        rows: list[dict[str, Any]] = []
        for pool_type, url, sort in pools:
            for item in _fetch_pool(url, day, sort):
                row = _snapshot_row(item, pool_type, day, fetched_at)
                if row is not None:
                    rows.append(row)
        inserted = _save_snapshot_rows(rows, session)
        return {
            "tool": "backend.tools.m60_market_temperature",
            "run_mode": "observe_only",
            "inserted": inserted,
            "fetched": len(rows),
            "summary": _summary(rows, day),
        }
    finally:
        if owned_session:
            session.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture observe-only market temperature board pools.")
    parser.add_argument("--date", default=None, help="Snapshot date, YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = capture_market_temperature_snapshot(args.date)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
