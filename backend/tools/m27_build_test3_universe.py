"""Build the M27 test3 universe from the local StockSage SQLite database."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func

from backend.config import BASE_DIR
from backend.data.database import MarketSnapshot, Price, SessionLocal, Stock

DEFAULT_OUTPUT = BASE_DIR / "paper_trading" / "test3_universe.json"


@dataclass(frozen=True)
class UniverseRow:
    symbol: str
    name: str
    sector: str
    origin: str
    price_bars: int
    avg_turnover_60d: float | None
    turnover_source: str
    avg_traded_value_60d: float


def _recent_liquidity(db, symbol: str, limit: int = 60) -> tuple[float, float]:
    rows = (
        db.query(Price.close, Price.volume)
        .filter(Price.symbol == symbol)
        .order_by(Price.date.desc())
        .limit(limit)
        .all()
    )
    values = [float(close or 0.0) * float(volume or 0.0) for close, volume in rows]
    volumes = [float(volume or 0.0) for _, volume in rows]
    avg_value = sum(values) / len(values) if values else 0.0
    avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
    return avg_value, avg_volume


def _latest_shares_outstanding(db, symbol: str) -> float | None:
    row = (
        db.query(MarketSnapshot.shares_outstanding)
        .filter(MarketSnapshot.symbol == symbol, MarketSnapshot.shares_outstanding.isnot(None))
        .order_by(MarketSnapshot.date.desc())
        .first()
    )
    if not row or not row[0]:
        return None
    shares = float(row[0])
    return shares if shares > 0 else None


def build_universe(
    db,
    *,
    target_size: int = 100,
    min_bars: int = 500,
    min_turnover: float = 0.005,
    min_avg_traded_value: float = 0.0,
    max_per_sector: int = 12,
) -> dict:
    """Select a liquid, sector-diversified local universe."""
    counts = dict(
        db.query(Price.symbol, func.count(Price.date))
        .group_by(Price.symbol)
        .all()
    )
    candidates: list[UniverseRow] = []
    for stock in db.query(Stock).filter(Stock.market == "CN").all():
        price_bars = int(counts.get(stock.symbol, 0))
        if price_bars < min_bars:
            continue
        liquidity, avg_volume = _recent_liquidity(db, stock.symbol)
        if liquidity <= 0:
            continue
        shares = _latest_shares_outstanding(db, stock.symbol)
        avg_turnover = avg_volume / shares if shares else None
        if avg_turnover is not None and avg_turnover >= min_turnover:
            turnover_source = "shares_outstanding"
        elif liquidity >= min_avg_traded_value:
            turnover_source = "amount_proxy_no_or_low_shares_turnover"
        else:
            if liquidity < min_avg_traded_value:
                continue
        candidates.append(UniverseRow(
            symbol=stock.symbol,
            name=stock.name,
            sector=stock.industry or "UNKNOWN",
            origin="m27_test3_local_filter",
            price_bars=price_bars,
            avg_turnover_60d=round(avg_turnover, 6) if avg_turnover is not None else None,
            turnover_source=turnover_source,
            avg_traded_value_60d=round(liquidity, 2),
        ))

    buckets: dict[str, list[UniverseRow]] = defaultdict(list)
    for row in sorted(candidates, key=lambda item: item.avg_traded_value_60d, reverse=True):
        buckets[row.sector].append(row)

    selected: list[UniverseRow] = []
    while len(selected) < target_size:
        added = False
        for sector in sorted(buckets, key=lambda key: len(buckets[key]), reverse=True):
            taken_in_sector = sum(1 for row in selected if row.sector == sector)
            if taken_in_sector >= max_per_sector or not buckets[sector]:
                continue
            selected.append(buckets[sector].pop(0))
            added = True
            if len(selected) >= target_size:
                break
        if not added:
            break

    return {
        "version": "2026-05-30",
        "source": "M27.2 local SQLite filter: bars/liquidity/sector diversification",
        "rules": {
            "target_size": target_size,
            "min_bars": min_bars,
            "min_turnover_60d": min_turnover,
            "turnover_rule": (
                "avg(volume / shares_outstanding) over latest 60 local bars when shares are available; "
                "otherwise, or when turnover would over-filter due sparse shares data, "
                "use avg(close * volume) as local liquidity fallback"
            ),
            "min_avg_traded_value_fallback": min_avg_traded_value,
            "max_per_sector": max_per_sector,
        },
        "coverage": {
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "sector_count": len({row.sector for row in selected}),
        },
        "stocks": [asdict(row) for row in selected],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--target-size", type=int, default=100)
    parser.add_argument("--min-bars", type=int, default=500)
    parser.add_argument("--min-turnover", type=float, default=0.005)
    parser.add_argument("--min-avg-traded-value", type=float, default=0.0)
    parser.add_argument("--max-per-sector", type=int, default=12)
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        payload = build_universe(
            db,
            target_size=args.target_size,
            min_bars=args.min_bars,
            min_turnover=args.min_turnover,
            min_avg_traded_value=args.min_avg_traded_value,
            max_per_sector=args.max_per_sector,
        )
    finally:
        db.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} ({payload['coverage']['selected_count']} symbols)")
    return 0 if payload["coverage"]["selected_count"] >= min(90, args.target_size) else 1


if __name__ == "__main__":
    raise SystemExit(main())
