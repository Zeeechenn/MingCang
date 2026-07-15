"""Create the small M67 gray universe and run market-scoped refresh jobs."""

from __future__ import annotations

import json

PILOT_STOCKS = (
    ("HK", "00700", "腾讯控股", "互联网平台"),
    ("HK", "09988", "阿里巴巴-W", "互联网平台"),
    ("US", "AAPL", "Apple Inc.", "消费电子"),
    ("US", "MSFT", "Microsoft", "软件与云计算"),
    ("US", "NVDA", "NVIDIA", "半导体"),
)


def ensure_pilot_stocks(db) -> list[str]:
    from backend.config import settings
    from backend.data.database import Stock
    from backend.data.market_profiles import instrument_key

    expected = {instrument_key(market, symbol) for market, symbol, _name, _industry in PILOT_STOCKS}
    if not settings.multimarket_gray_enabled or not expected <= settings.multimarket_gray_asset_keys:
        raise RuntimeError("M67 gray config must explicitly allow every pilot asset key")
    keys: list[str] = []
    for market, symbol, name, industry in PILOT_STOCKS:
        key = instrument_key(market, symbol)
        row = db.query(Stock).filter(Stock.asset_key == key).first()
        if row is None:
            row = Stock(
                symbol=symbol,
                name=name,
                market=market,
                industry=industry,
                active=True,
            )
            db.add(row)
        else:
            row.name = name
            row.industry = row.industry or industry
            row.active = True
        keys.append(key)
    db.commit()
    return keys


def main() -> None:
    from backend.data.database import SessionLocal, init_db
    from backend.jobs.premarket import run_premarket

    init_db()
    db = SessionLocal()
    try:
        asset_keys = ensure_pilot_stocks(db)
    finally:
        db.close()
    result = {
        "asset_keys": asset_keys,
        "HK": run_premarket("HK"),
        "US": run_premarket("US"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
