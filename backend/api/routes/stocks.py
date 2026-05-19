"""Stock search and autocomplete routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.data.database import Stock, get_db

router = APIRouter()


def _local_matches(q: str, market: str, limit: int, db: Session) -> list[dict]:
    needle = q.strip().lower()
    rows = db.query(Stock).filter(Stock.market == market).all()
    matches = []
    for row in rows:
        haystack = f"{row.symbol} {row.name or ''}".lower()
        if needle in haystack:
            matches.append({
                "symbol": row.symbol,
                "name": row.name,
                "market": row.market,
                "industry": row.industry,
                "source": "local",
            })
    return matches[:limit]


def _remote_cn_matches(q: str, limit: int) -> list[dict]:
    """Best-effort A-share autocomplete via the project's AkShare dependency."""
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        code_col = "code" if "code" in df.columns else "证券代码"
        name_col = "name" if "name" in df.columns else "证券简称"
        needle = q.strip().lower()
        out = []
        for _, row in df.iterrows():
            symbol = str(row.get(code_col, "")).zfill(6)
            name = str(row.get(name_col, ""))
            if needle in symbol.lower() or needle in name.lower():
                out.append({"symbol": symbol, "name": name, "market": "CN", "source": "akshare"})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


@router.get("/stocks/search")
def search_stocks(q: str, market: str = "CN", limit: int = 8, db: Session = Depends(get_db)):
    """Search by symbol or Chinese name, local rows first and remote provider second."""
    if not q.strip():
        return []
    local = _local_matches(q, market, limit, db)
    seen = {item["symbol"] for item in local}
    remote = []
    if market == "CN" and len(local) < limit:
        for item in _remote_cn_matches(q, limit - len(local)):
            if item["symbol"] not in seen:
                remote.append(item)
                seen.add(item["symbol"])
    return (local + remote)[:limit]
