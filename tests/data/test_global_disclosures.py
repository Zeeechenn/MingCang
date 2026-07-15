from datetime import datetime


def test_fetch_sec_filings_preserves_filing_date_and_archive_url():
    from backend.data.global_disclosures import (
        SEC_SUBMISSIONS_URL,
        SEC_TICKERS_URL,
        fetch_sec_filings,
    )

    def fake_fetch(url):
        if url == SEC_TICKERS_URL:
            return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        assert url == SEC_SUBMISSIONS_URL.format(cik="0000320193")
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000001"],
                    "filingDate": ["2026-07-10"],
                    "reportDate": ["2026-06-30"],
                    "form": ["10-Q"],
                    "primaryDocument": ["aapl-20260630.htm"],
                    "primaryDocDescription": ["Quarterly report"],
                }
            }
        }

    rows = fetch_sec_filings(
        "aapl",
        since=datetime(2026, 7, 1).date(),
        fetch_json=fake_fetch,
    )
    assert len(rows) == 1
    assert rows[0]["published_at"] == datetime(2026, 7, 10)
    assert rows[0]["ann_type"] == "10-Q"
    assert "/320193/000032019326000001/aapl-20260630.htm" in rows[0]["source_url"]


def test_save_global_disclosures_is_market_scoped_and_idempotent(test_db):
    from backend.data.database import Announcement
    from backend.data.global_disclosures import save_global_disclosures

    rows = [{
        "symbol": "AAPL",
        "title": "SEC 8-K",
        "published_at": datetime(2026, 7, 10),
        "provider": "sec_submissions",
    }]
    assert save_global_disclosures(rows, test_db, market="US") == 1
    assert save_global_disclosures(rows, test_db, market="US") == 0
    saved = test_db.query(Announcement).one()
    assert saved.asset_key == "US:AAPL"
    assert saved.currency == "USD"
