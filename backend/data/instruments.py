"""Market-aware instrument lookup with legacy symbol compatibility."""

from __future__ import annotations

from backend.data.market_profiles import (
    SUPPORTED_MARKETS,
    instrument_key,
    normalize_market,
    normalize_symbol,
)


class AmbiguousInstrumentError(ValueError):
    pass


def symbol_candidates(symbol: str) -> list[str]:
    raw = str(symbol).strip().upper()
    rows = [raw]
    for market in SUPPORTED_MARKETS:
        normalized = normalize_symbol(raw, market)
        if normalized not in rows:
            rows.append(normalized)
    return rows


def resolve_stock(db, symbol: str, market: str | None = None):
    """Resolve a Stock by market-scoped identity, accepting old HK/US suffix forms."""
    from backend.data.database import Stock

    if market is not None:
        normalized_market = normalize_market(market)
        key = instrument_key(normalized_market, symbol)
        row = db.query(Stock).filter(Stock.asset_key == key).first()
        if row is not None:
            return row
        return db.query(Stock).filter(
            Stock.market == normalized_market,
            Stock.symbol == normalize_symbol(symbol, normalized_market),
        ).first()

    raw = str(symbol).strip().upper()
    exact = db.query(Stock).filter(Stock.symbol == raw).all()
    if len(exact) == 1:
        return exact[0]
    rows = db.query(Stock).filter(Stock.symbol.in_(symbol_candidates(raw))).all()
    unique = {str(row.asset_key or f"{row.market}:{row.symbol}"): row for row in rows}
    if len(unique) > 1:
        raise AmbiguousInstrumentError(
            f"symbol {symbol!r} exists in multiple markets; pass market explicitly"
        )
    return next(iter(unique.values()), None)
