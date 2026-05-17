"""股票池构建与批量回填入口."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend.data.database import Stock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UniverseCandidate:
    symbol: str
    name: str
    market: str = "CN"
    industry: str | None = None


def filter_universe(
    candidates: list[UniverseCandidate],
    *,
    stats: dict[str, dict[str, float]] | None = None,
    min_market_cap: float = 5e9,
    min_daily_amount: float = 1e8,
    limit: int | None = None,
) -> list[UniverseCandidate]:
    """
    Filter candidates by market cap and average daily traded amount.

    `stats` is intentionally injected so data-source quirks stay outside the
    selection rule. Expected keys per symbol: `market_cap`, `avg_daily_amount`.
    """
    stats = stats or {}
    out: list[UniverseCandidate] = []
    for c in candidates:
        row = stats.get(c.symbol)
        if not row:
            continue
        market_cap = row.get("market_cap") or 0.0
        avg_daily_amount = row.get("avg_daily_amount") or 0.0
        if market_cap < min_market_cap or avg_daily_amount < min_daily_amount:
            continue
        out.append(c)
        if limit and len(out) >= limit:
            break
    return out


def get_hs300_constituents() -> list[UniverseCandidate]:
    """Fetch current HS300 constituents from AkShare."""
    try:
        import akshare as ak
    except ImportError:
        logger.error("akshare 未安装")
        return []

    df = ak.index_stock_cons_csindex(symbol="000300")
    candidates = []
    for _, row in df.iterrows():
        raw_code = str(row.get("成分券代码") or row.get("con_code") or row.get("品种代码") or "")
        code = raw_code.split(".")[0].zfill(6)
        name = str(row.get("成分券名称") or row.get("con_name") or row.get("品种名称") or code)
        if code.isdigit() and code != "000000":
            candidates.append(UniverseCandidate(symbol=code, name=name))
    return candidates


def merge_candidates(*groups: list[UniverseCandidate], limit: int | None = None) -> list[UniverseCandidate]:
    """Deduplicate candidates while preserving order."""
    seen = set()
    merged: list[UniverseCandidate] = []
    for group in groups:
        for c in group:
            if c.symbol in seen:
                continue
            seen.add(c.symbol)
            merged.append(c)
            if limit and len(merged) >= limit:
                return merged
    return merged


def upsert_universe(db, candidates: list[UniverseCandidate], *, active: bool = True) -> int:
    """Insert or reactivate candidates in the Stock table."""
    count = 0
    for c in candidates:
        stock = db.query(Stock).filter(Stock.symbol == c.symbol).first()
        if stock is None:
            db.add(Stock(
                symbol=c.symbol,
                name=c.name,
                market=c.market,
                industry=c.industry,
                active=active,
            ))
            count += 1
        else:
            stock.active = active
            if c.name and not stock.name:
                stock.name = c.name
            if c.industry and not stock.industry:
                stock.industry = c.industry
    db.commit()
    return count


def backfill_universe(db, candidates: list[UniverseCandidate], *, years: int = 5, pause_s: float = 0.2) -> dict:
    """
    Upsert candidates and backfill OHLCV data.

    This is a callable building block for scripts/manual ops. It deliberately
    avoids running automatically from the scheduler.
    """
    from backend.data.market import backfill_if_needed

    inserted = upsert_universe(db, candidates)
    rows = 0
    errors: dict[str, str] = {}
    for c in candidates:
        try:
            rows += backfill_if_needed(c.symbol, c.market, db, years=years)
            time.sleep(pause_s)
        except Exception as e:
            errors[c.symbol] = str(e)
            logger.warning("backfill_universe failed %s: %s", c.symbol, e)
    return {
        "candidates": len(candidates),
        "inserted_stocks": inserted,
        "price_rows": rows,
        "years": years,
        "errors": errors,
    }
