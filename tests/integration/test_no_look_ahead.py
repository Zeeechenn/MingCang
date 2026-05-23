"""
Look-Ahead 集成测试（Tier 3）

灵感来自 Benhenda 2026 Look-Ahead-Bench：模拟 as_of=2024-10-01 时刻，
通过 PITSession 访问数据，断言所有受管表都不会泄漏 > as_of 的字段。

种子数据：故意把"未来数据"和"历史数据"混在一起，验证拦截器能挡住未来。
"""
from datetime import datetime

import pytest


@pytest.fixture
def seeded_db(test_db):
    """种 4 类时间字段的数据，跨越 as_of 边界"""
    from backend.data.database import (
        FinancialMetric,
        IndexPrice,
        LongTermLabel,
        NewsItem,
        Price,
        Signal,
    )

    # Price：历史 + 未来
    test_db.add(Price(symbol="600519", date="2024-09-30", close=100.0, open=99, high=101, low=98, volume=1e6))
    test_db.add(Price(symbol="600519", date="2024-10-01", close=101.0, open=100, high=102, low=100, volume=1e6))
    test_db.add(Price(symbol="600519", date="2024-12-01", close=120.0, open=118, high=122, low=117, volume=1e6))  # 未来

    # Signal
    test_db.add(Signal(symbol="600519", date="2024-09-25", composite_score=30, recommendation="可关注", confidence="中"))
    test_db.add(Signal(symbol="600519", date="2024-11-15", composite_score=50, recommendation="可小仓试错", confidence="高"))  # 未来

    # LongTermLabel
    test_db.add(LongTermLabel(symbol="600519", date="2024-09-20", label="值得持有",
                              score=60, expires_at="2024-09-30"))
    test_db.add(LongTermLabel(symbol="600519", date="2024-10-15", label="规避",
                              score=-40, expires_at="2024-10-25"))  # 未来

    # FinancialMetric：PIT 必须看 disclosure_date，而不是 report_date。
    test_db.add(FinancialMetric(
        symbol="600519", report_date="2024-06-30", disclosure_date="2024-08-20", revenue=1e9,
    ))
    test_db.add(FinancialMetric(
        symbol="600519", report_date="2024-09-30", disclosure_date="2024-10-28", revenue=1.1e9,
    ))
    test_db.add(FinancialMetric(
        symbol="600519", report_date="2024-12-31", disclosure_date="2025-03-28", revenue=1.2e9,
    ))  # 未来季报

    # NewsItem（用 datetime 字段）
    test_db.add(NewsItem(symbol="600519", title="历史新闻",
                         url="https://x.com/1",
                         published_at=datetime(2024, 9, 20, 10, 0)))
    test_db.add(NewsItem(symbol="600519", title="未来新闻",
                         url="https://x.com/2",
                         published_at=datetime(2024, 11, 1, 10, 0)))

    # IndexPrice
    test_db.add(IndexPrice(symbol="sh000300", date="2024-09-30", close=3500))
    test_db.add(IndexPrice(symbol="sh000300", date="2024-11-30", close=3700))  # 未来

    test_db.commit()
    return test_db


def test_pit_session_filters_price_by_date(seeded_db):
    from backend.data.database import Price
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    rows = pit.query(Price).all()
    assert len(rows) == 2
    for r in rows:
        assert r.date <= "2024-10-01"


def test_pit_session_filters_signal_by_date(seeded_db):
    from backend.data.database import Signal
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    sigs = pit.query(Signal).all()
    assert len(sigs) == 1
    assert sigs[0].date == "2024-09-25"


def test_pit_session_filters_long_term_label(seeded_db):
    from backend.data.database import LongTermLabel
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    labels = pit.query(LongTermLabel).all()
    assert len(labels) == 1
    assert labels[0].date == "2024-09-20"


def test_pit_session_filters_financial_metric_by_disclosure_date(seeded_db):
    from backend.data.database import FinancialMetric
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    rows = pit.query(FinancialMetric).all()
    assert len(rows) == 1
    for r in rows:
        assert r.disclosure_date <= "2024-10-01"


def test_pit_session_filters_news_by_published_at(seeded_db):
    from backend.data.database import NewsItem
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    news = pit.query(NewsItem).all()
    assert len(news) == 1
    assert news[0].title == "历史新闻"


def test_pit_session_filters_index_price(seeded_db):
    from backend.data.database import IndexPrice
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    rows = pit.query(IndexPrice).all()
    assert len(rows) == 1


def test_assert_pit_clean_catches_leak(seeded_db):
    from backend.data.database import Price
    from backend.data.point_in_time import assert_pit_clean

    # 裸 session 应有 1 条 > as_of
    leak = assert_pit_clean(seeded_db, "2024-10-01", Price)
    assert leak == 1


def test_pit_session_context_manager(seeded_db):
    from backend.data.database import Price
    from backend.data.point_in_time import pit_session

    with pit_session(seeded_db, "2024-10-01") as pit:
        rows = pit.query(Price).all()
    assert len(rows) == 2


def test_pit_session_passthrough_non_managed_models(seeded_db):
    """未注册的查询应该透传 — 暂时通过 .add / .commit 验证 session attr 透传"""
    from backend.data.point_in_time import PITSession

    pit = PITSession(seeded_db, as_of="2024-10-01")
    # 透传 .commit() 不抛
    pit.commit()
    # 透传 as_of 属性
    assert pit.as_of == "2024-10-01"


def test_simulated_decision_path_uses_only_historical_data(seeded_db):
    """端到端：模拟一次 as_of=2024-10-01 的决策访问，全部用 PIT 包装"""
    from backend.data.database import FinancialMetric, LongTermLabel, Price, Signal
    from backend.data.point_in_time import pit_session

    with pit_session(seeded_db, "2024-10-01") as db:
        prices = db.query(Price).filter(Price.symbol == "600519").all()
        signals = db.query(Signal).filter(Signal.symbol == "600519").all()
        labels = db.query(LongTermLabel).filter(LongTermLabel.symbol == "600519").all()
        fins = db.query(FinancialMetric).filter(FinancialMetric.symbol == "600519").all()

    assert all(p.date <= "2024-10-01" for p in prices)
    assert all(s.date <= "2024-10-01" for s in signals)
    assert all(label.date <= "2024-10-01" for label in labels)
    assert all(f.disclosure_date <= "2024-10-01" for f in fins)
