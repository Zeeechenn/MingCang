from datetime import UTC, datetime

import pandas as pd


class _FakeTicker:
    def __init__(self, _symbol):
        periods = [pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
        self.quarterly_financials = pd.DataFrame(
            {
                periods[0]: [130.0, 13.0, 55.0],
                periods[1]: [120.0, 12.0, 50.0],
                periods[2]: [100.0, 10.0, 40.0],
            },
            index=["Total Revenue", "Net Income", "Gross Profit"],
        )
        self.quarterly_balance_sheet = pd.DataFrame(
            {
                periods[0]: [520.0, 210.0, 120.0, 60.0, 20.0, 1000.0],
                periods[1]: [500.0, 200.0, 100.0, 50.0, 20.0, 1000.0],
                periods[2]: [480.0, 190.0, 90.0, 45.0, 22.0, 1000.0],
            },
            index=[
                "Total Assets",
                "Stockholders Equity",
                "Current Assets",
                "Current Liabilities",
                "Long Term Debt",
                "Ordinary Shares Number",
            ],
        )
        self.quarterly_cashflow = pd.DataFrame(
            {periods[0]: [18.0], periods[1]: [16.0], periods[2]: [14.0]},
            index=["Operating Cash Flow"],
        )
        self.news = [{
            "content": {
                "title": "Apple files quarterly update",
                "summary": "Quarterly filing summary",
                "pubDate": "2026-07-10T12:00:00Z",
                "canonicalUrl": {"url": "https://example.com/aapl"},
            }
        }]

    def get_earnings_dates(self, limit=40):
        return pd.DataFrame(
            {"Reported EPS": [1.0, 0.9]},
            index=pd.DatetimeIndex([
                pd.Timestamp("2026-07-30", tz="UTC"),
                pd.Timestamp("2026-04-30", tz="UTC"),
            ]),
        )


def test_ifind_nested_answer_normalizes_global_quotes():
    from backend.data.ifind_mcp import extract_stock_daily_table

    answer = (
        "|证券代码|日期|开盘价（单位：元）|收盘价（单位：元）|成交量|最高价（单位：元）|最低价（单位：元）|\n"
        "|---|---|---|---|---|---|---|\n"
        "|0700.HK|20260714|457.6|456.2|2554.054万|459.2|447.4|"
    )
    payload = '{"code":1,"data":{"answer":' + __import__("json").dumps(answer, ensure_ascii=False) + "}}"
    frame = extract_stock_daily_table(payload)
    assert list(frame.index) == ["2026-07-14"]
    assert frame.iloc[0]["volume"] == 25_540_540


def test_tickflow_hk_us_use_split_continuous_forward_adjustment(monkeypatch):
    from backend.data import tickflow
    from backend.data.market_sources import fetch_hk_daily_tickflow, fetch_us_daily_tickflow

    calls = []

    def fake_fetch(symbol, market, days, adjust):
        calls.append((symbol, market, days, adjust))
        return pd.DataFrame()

    monkeypatch.setattr(tickflow, "fetch_tickflow_daily", fake_fetch)
    fetch_hk_daily_tickflow("00700", days=30)
    fetch_us_daily_tickflow("AAPL", days=40)
    assert calls == [
        ("00700", "HK", 30, "forward"),
        ("AAPL", "US", 40, "forward"),
    ]


def test_global_financial_adapter_blocks_future_undisclosed_period(monkeypatch):
    import yfinance

    from backend.data.global_fundamentals import fetch_yfinance_financial_rows

    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    rows = fetch_yfinance_financial_rows(
        "AAPL",
        "US",
        as_of=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert [row["report_date"] for row in rows] == ["2026-03-31"]
    assert rows[0]["disclosure_date"] == "2026-04-30"
    assert rows[0]["gross_margin"] == 50.0 / 120.0 * 100


def test_sync_global_financial_metrics_persists_market_identity(monkeypatch, test_db):
    import yfinance

    from backend.data.database import FinancialMetric
    from backend.data.global_fundamentals import sync_global_financial_metrics

    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    inserted = sync_global_financial_metrics(
        "AAPL",
        "US",
        test_db,
        as_of=datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert inserted == 1
    row = test_db.query(FinancialMetric).one()
    assert (row.asset_key, row.market, row.currency, row.source) == (
        "US:AAPL",
        "US",
        "USD",
        "yfinance_global",
    )


def test_global_news_dispatch_combines_ifind_and_yahoo(monkeypatch):
    import yfinance

    from backend.data import news
    from backend.data.news_models import RawNews

    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    monkeypatch.setattr(
        news,
        "fetch_news_ifind",
        lambda *args, **kwargs: [RawNews(
            title="Apple event",
            url="https://example.com/event",
            published_at=datetime(2026, 7, 9),
            source="ifind",
            symbol="AAPL",
            provider="ifind",
        )],
    )
    rows = news.fetch_stock_news_global("aapl.o", "Apple", "US")
    assert {row.provider for row in rows} == {"ifind", "yfinance_news"}
    assert all(row.symbol == "AAPL" for row in rows)
