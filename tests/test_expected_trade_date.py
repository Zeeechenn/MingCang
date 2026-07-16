"""expected_trade_date 四条路径：锚点、收盘后探针成功、探针失败回落、非收盘后。

不碰网络：探针路径通过 monkeypatch backend.data.providers.fetch_daily_with_fallback
拦截；数据库锚点用真实内存 SQLite（建 prices/index_prices 表）。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.data.freshness import expected_trade_date

SH = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE prices (date TEXT)"))
        conn.execute(text("CREATE TABLE index_prices (date TEXT)"))
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed(db, prices_max: str | None, index_max: str | None):
    if prices_max:
        db.execute(text("INSERT INTO prices (date) VALUES (:d)"), {"d": prices_max})
    if index_max:
        db.execute(text("INSERT INTO index_prices (date) VALUES (:d)"), {"d": index_max})
    db.commit()


def test_weekend_returns_anchor(db):
    _seed(db, "2026-07-15", "2026-07-14")
    # 2026-07-18 是周六
    now = datetime(2026, 7, 18, 16, 0, tzinfo=SH)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-15", "anchor")


def test_weekday_before_close_returns_anchor(db):
    _seed(db, "2026-07-15", "2026-07-15")
    # 2026-07-16 周四 14:00，尚未收盘
    now = datetime(2026, 7, 16, 14, 0, tzinfo=SH)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-15", "anchor")


def test_after_close_probe_success_returns_candidate(db, monkeypatch):
    _seed(db, "2026-07-15", "2026-07-15")
    now = datetime(2026, 7, 16, 15, 30, tzinfo=SH)

    def _fake_fetch(symbol, market, days, *, expected_latest=None):
        idx = pd.date_range(end="2026-07-16", periods=3, freq="D")
        return pd.DataFrame({"close": [1, 2, 3]}, index=idx), "fake_provider"

    monkeypatch.setattr("backend.data.providers.fetch_daily_with_fallback", _fake_fetch)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-16", "probe")


def test_after_close_probe_failure_falls_back_to_anchor(db, monkeypatch):
    _seed(db, "2026-07-15", "2026-07-15")
    now = datetime(2026, 7, 16, 15, 30, tzinfo=SH)

    def _fake_fetch(symbol, market, days, *, expected_latest=None):
        # 探针只拿到陈旧 bar（源尚未更新/节假日无交易）
        idx = pd.date_range(end="2026-07-15", periods=3, freq="D")
        return pd.DataFrame({"close": [1, 2, 3]}, index=idx), "fake_provider"

    monkeypatch.setattr("backend.data.providers.fetch_daily_with_fallback", _fake_fetch)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-15", "probe_failed_anchor")


def test_after_close_probe_exception_falls_back_to_anchor(db, monkeypatch):
    _seed(db, "2026-07-15", "2026-07-15")
    now = datetime(2026, 7, 16, 15, 30, tzinfo=SH)

    def _fake_fetch(symbol, market, days, *, expected_latest=None):
        raise RuntimeError("all providers down")

    monkeypatch.setattr("backend.data.providers.fetch_daily_with_fallback", _fake_fetch)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-15", "probe_failed_anchor")


def test_probe_false_skips_network_and_returns_candidate(db):
    _seed(db, "2026-07-15", "2026-07-15")
    now = datetime(2026, 7, 16, 15, 30, tzinfo=SH)
    expected, basis = expected_trade_date(db, now=now, probe=False)
    assert (expected, basis) == ("2026-07-16", "candidate")


def test_no_anchor_no_candidate_returns_unknown(db):
    now = datetime(2026, 7, 16, 14, 0, tzinfo=SH)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("", "unknown")


def test_anchor_takes_max_of_prices_and_index(db):
    _seed(db, "2026-07-10", "2026-07-15")
    now = datetime(2026, 7, 16, 14, 0, tzinfo=SH)
    expected, basis = expected_trade_date(db, now=now)
    assert (expected, basis) == ("2026-07-15", "anchor")
