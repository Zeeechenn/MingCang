"""PIT-safe HK/US disclosure ingestion for M67 gray research."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

from backend.config import settings
from backend.data.market_profiles import instrument_key, normalize_market, normalize_symbol

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def _fetch_sec_json(url: str, *, max_bytes: int = 5_000_000) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=20,
    )
    response.raise_for_status()
    if len(response.content) > max_bytes:
        raise ValueError(f"SEC response too large: {len(response.content)} bytes")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SEC response is not a JSON object")
    return payload


def fetch_sec_filings(
    symbol: str,
    *,
    since: date | None = None,
    limit: int = 40,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_sec_json,
) -> list[dict[str, Any]]:
    """Fetch recent SEC submissions with exact filing dates and archive URLs."""
    symbol = normalize_symbol(symbol, "US")
    ticker_rows = fetch_json(SEC_TICKERS_URL)
    match = next(
        (
            row
            for row in ticker_rows.values()
            if isinstance(row, dict) and str(row.get("ticker") or "").upper() == symbol
        ),
        None,
    )
    if match is None:
        return []
    cik_int = int(match["cik_str"])
    submissions = fetch_json(SEC_SUBMISSIONS_URL.format(cik=f"{cik_int:010d}"))
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    fields = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    size = max((len(recent.get(field) or []) for field in fields), default=0)
    cutoff = since or (datetime.now(UTC).date() - timedelta(days=370))
    rows: list[dict[str, Any]] = []
    for index in range(size):
        values = {
            field: (recent.get(field) or [])[index] if index < len(recent.get(field) or []) else ""
            for field in fields
        }
        filing_date = str(values["filingDate"] or "")
        try:
            published_at = datetime.strptime(filing_date, "%Y-%m-%d")
        except ValueError:
            continue
        if published_at.date() < cutoff:
            continue
        accession = str(values["accessionNumber"] or "")
        primary_document = str(values["primaryDocument"] or "")
        accession_path = accession.replace("-", "")
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_path}/{primary_document}"
            if accession_path and primary_document
            else None
        )
        form = str(values["form"] or "filing")
        description = str(values["primaryDocDescription"] or "").strip()
        rows.append({
            "symbol": symbol,
            "market": "US",
            "title": f"SEC {form}" + (f" - {description}" if description else ""),
            "content": f"report_date={values['reportDate']}; accession={accession}",
            "ann_type": form,
            "published_at": published_at,
            "source_url": source_url,
            "provider": "sec_submissions",
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_hk_notices(symbol: str, name: str, *, since: date | None = None, limit: int = 20) -> list[dict]:
    """Fetch HK disclosure evidence through the configured iFinD notice tool."""
    from backend.data.category_fetchers import fetch_announcements_ifind_notice
    from backend.data.category_registry import FetchRequest

    end = datetime.now(UTC).date()
    start = since or (end - timedelta(days=90))
    normalized_symbol = normalize_symbol(symbol, "HK")
    rows = fetch_announcements_ifind_notice(FetchRequest(
        symbol=normalized_symbol,
        start=start,
        end=end,
        limit=limit,
        extra={"name": name},
    ))
    return [{**row, "market": "HK", "symbol": normalized_symbol} for row in rows]


def save_global_disclosures(rows: list[dict], db, *, market: str) -> int:
    from backend.data.database import Announcement
    from backend.data.market_profiles import get_market_profile

    market = normalize_market(market)
    profile = get_market_profile(market)
    inserted = 0
    for row in rows:
        symbol = normalize_symbol(str(row["symbol"]), market)
        key = instrument_key(market, symbol)
        existing = db.query(Announcement.id).filter(
            Announcement.asset_key == key,
            Announcement.title == row["title"],
            Announcement.published_at == row["published_at"],
        ).first()
        if existing:
            continue
        db.add(Announcement(
            symbol=symbol,
            asset_key=key,
            market=market,
            currency=profile.currency,
            title=row["title"],
            content=row.get("content"),
            ann_type=row.get("ann_type"),
            published_at=row["published_at"],
            source_url=row.get("source_url") or row.get("url"),
            provider=row.get("provider") or "unknown",
            fetched_at=row.get("fetched_at") or datetime.now(UTC).replace(tzinfo=None),
        ))
        inserted += 1
    db.commit()
    return inserted


def sync_global_disclosures(stock, db, *, since: date | None = None) -> int:
    market = normalize_market(stock.market)
    if market == "US":
        rows = fetch_sec_filings(stock.symbol, since=since)
    elif market == "HK":
        rows = fetch_hk_notices(stock.symbol, stock.name, since=since)
    else:
        return 0
    return save_global_disclosures(rows, db, market=market)
