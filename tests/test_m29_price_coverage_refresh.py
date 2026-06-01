from datetime import date, datetime

import pandas as pd
import pytest


def _daily_frame():
    df = pd.DataFrame(
        [
            {"date": "2026-05-27", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000},
            {"date": "2026-05-28", "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5, "volume": 1100},
            {"date": "2026-05-29", "open": 12.0, "high": 13.0, "low": 11.0, "close": 12.5, "volume": 1200},
            {"date": "2026-06-01", "open": 13.0, "high": 14.0, "low": 12.0, "close": 13.5, "volume": 1300},
        ]
    ).set_index("date")
    df.attrs["source"] = "unit_provider"
    df.attrs["fetched_at"] = datetime(2026, 6, 1, 1, 2, 3)
    df.attrs["adjustment"] = "qfq"
    return df


def test_validate_window_rejects_today_without_explicit_override():
    from backend.tools import m29_price_coverage_refresh as tool

    with pytest.raises(ValueError, match="before today"):
        tool._validate_window("2026-05-29", "2026-06-01", today=date(2026, 6, 1))

    assert tool._validate_window(
        "2026-05-29",
        "2026-06-01",
        allow_today=True,
        today=date(2026, 6, 1),
    ) == (date(2026, 5, 29), date(2026, 6, 1))


def test_price_record_payloads_filters_to_close_confirmed_window_and_keeps_provenance():
    from backend.tools import m29_price_coverage_refresh as tool

    payloads = tool.price_record_payloads("000001", _daily_frame(), start="2026-05-27", end="2026-05-29")

    assert [row["date"] for row in payloads] == ["2026-05-27", "2026-05-28", "2026-05-29"]
    assert {row["source"] for row in payloads} == {"unit_provider"}
    assert {row["adjustment"] for row in payloads} == {"qfq"}
    assert all(row["fetched_at"] == datetime(2026, 6, 1, 1, 2, 3) for row in payloads)
    assert all(row["symbol"] == "000001" for row in payloads)


def test_price_record_payloads_accepts_date_column():
    from backend.tools import m29_price_coverage_refresh as tool

    df = _daily_frame().reset_index()
    df.attrs["source"] = "unit_provider"
    df.attrs["fetched_at"] = datetime(2026, 6, 1, 1, 2, 3)
    df.attrs["adjustment"] = "qfq"

    payloads = tool.price_record_payloads("000001", df, start="2026-05-28", end="2026-05-29")

    assert [row["date"] for row in payloads] == ["2026-05-28", "2026-05-29"]
