"""任务1 news_cache 单元测试。

不调用真实 LLM，全部 mock。
"""
from __future__ import annotations
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from backend.backtest import news_cache


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    """每个测试用独立临时缓存文件，避免污染真实缓存"""
    monkeypatch.setattr(news_cache, "_CACHE_FILE", tmp_path / "test_cache.json")
    yield


def _row(title: str, pub_dt: datetime):
    """模拟 NewsItem 行（只关心 .title / .published_at）"""
    row = MagicMock()
    row.title = title
    row.published_at = pub_dt
    return (title,)   # query(NewsItem.title) 返回 tuples


def test_get_or_backfill_cache_miss_no_llm_returns_fallback():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    result = news_cache.get_or_backfill("600519", "2026-05-01", db, use_llm=False)
    assert result["sentiment"] == 0.0
    assert "cache miss" in result["summary"]


def test_get_or_backfill_cache_hit_short_circuits():
    """缓存命中时不应查 DB，不应调 LLM"""
    # 预填缓存
    news_cache._save_cache({
        "600519|2026-05-01": {
            "sentiment": 0.5, "summary": "test",
            "impact": "short", "key_events": ["利好A"],
        }
    })
    db = MagicMock()
    result = news_cache.get_or_backfill("600519", "2026-05-01", db, use_llm=True)
    assert result["key_events"] == ["利好A"]
    db.query.assert_not_called()


def test_get_or_backfill_with_news_calls_llm_and_caches():
    db = MagicMock()
    # _fetch_titles 内部走 db.query(NewsItem.title).filter().order_by().limit().all()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        ("利好公告：业绩超预期",),
        ("机构看多",),
    ]
    with patch("backend.analysis.sentiment.analyze_news") as mock_analyze:
        mock_analyze.return_value = {
            "sentiment": 0.7, "summary": "整体偏正",
            "impact": "short", "key_events": ["业绩超预期", "机构看多"],
        }
        result = news_cache.get_or_backfill("600519", "2026-05-01", db, use_llm=True)
    assert result["sentiment"] == 0.7
    assert "业绩超预期" in result["key_events"]
    # 写回缓存
    cache = news_cache._load_cache()
    assert "600519|2026-05-01" in cache


def test_get_or_backfill_no_news_caches_empty():
    """无新闻 → 缓存空事件，避免重复查 DB"""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    result = news_cache.get_or_backfill("600519", "2026-05-01", db, use_llm=True)
    assert result["sentiment"] == 0.0
    assert result["key_events"] == []
    cache = news_cache._load_cache()
    assert cache["600519|2026-05-01"]["summary"] == "无相关新闻"


def test_backfill_all_skips_existing_when_requested():
    news_cache._save_cache({
        "600519|2026-05-01": {"sentiment": 0.3, "summary": "old", "impact": "short", "key_events": []},
    })
    sig = MagicMock()
    sig.symbol = "600519"
    sig.date = "2026-05-01"

    db = MagicMock()
    stats = news_cache.backfill_all([sig], db, skip_existing=True)
    assert stats["existing"] == 1
    assert stats["new"] == 0


def test_backfill_all_stats_new_and_no_news():
    """1 个有新闻，1 个无新闻"""
    sig_with = MagicMock()
    sig_with.symbol = "AAA"
    sig_with.date = "2026-05-01"
    sig_without = MagicMock()
    sig_without.symbol = "BBB"
    sig_without.date = "2026-05-01"

    db = MagicMock()
    call_count = [0]

    def fake_all():
        call_count[0] += 1
        if call_count[0] == 1:
            return [("利好",), ("公告",)]
        return []

    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.side_effect = fake_all

    with patch("backend.analysis.sentiment.analyze_news") as mock_analyze:
        mock_analyze.return_value = {
            "sentiment": 0.6, "summary": "正面",
            "impact": "short", "key_events": ["利好"],
        }
        stats = news_cache.backfill_all([sig_with, sig_without], db, skip_existing=True)

    assert stats["new"] == 1
    assert stats["no_news"] == 1


def test_clear_cache_removes_file(tmp_path):
    news_cache._save_cache({"x|y": {"sentiment": 0.0}})
    assert Path(news_cache.cache_path()).exists()
    news_cache.clear_cache()
    assert not Path(news_cache.cache_path()).exists()
