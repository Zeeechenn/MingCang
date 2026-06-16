"""Tests for the M27.x news sentiment hardening: market-flow filter, hard-event-only
override, and the company-evidence floor (2026-06-15 sentiment IC diagnosis follow-up)."""
from __future__ import annotations

from datetime import datetime

import backend.analysis.sentiment as sentiment
from backend.analysis.event_taxonomy import (
    classify_events,
    company_specific_titles,
    event_score,
    is_company_specific,
    is_market_flow,
)

# ---- market-flow / relevance detection ---------------------------------------

def test_market_flow_detects_fund_flow_and_lists():
    assert is_market_flow("主力动向：6月10日特大单净流出542.55亿元")
    assert is_market_flow("7只个股大宗交易超5000万元")
    assert is_market_flow("收盘价创历史新高股一览")
    assert is_market_flow("54股获杠杆资金净买入超亿元")
    assert is_market_flow("汽车芯片概念涨4.59%，主力资金净流入这些股")


def test_company_specific_keeps_real_company_news():
    assert is_company_specific("兆易创新：拟回购公司股份用于股权激励")
    assert is_company_specific("北方华创公告：中标某半导体设备订单")
    assert not is_company_specific("91股特大单净流入资金超2亿元")


def test_company_specific_titles_filters_noise():
    titles = [
        "兆易创新发布业绩预增公告",       # keep
        "7只个股大宗交易超5000万元",       # drop (list)
        "主力资金净流入这些股",           # drop (flow)
    ]
    assert company_specific_titles(titles) == ["兆易创新发布业绩预增公告"]


def test_company_aliases_catch_cross_company_contamination():
    # 长鑫-IPO headlines loosely tagged to 兆易: not market noise, but not about 兆易.
    titles = [
        "长鑫上市在即 存储炒作能否有二波",
        "兆易创新参与臻宝科技战略配售",
    ]
    kept = company_specific_titles(titles, company_aliases=["兆易创新", "兆易", "603986"])
    assert kept == ["兆易创新参与臻宝科技战略配售"]


# ---- classify_events no longer misfires on market noise ----------------------

def test_market_noise_not_misclassified_as_hard_event():
    # "下滑" would historically match earnings_warning; inside market noise it must not.
    assert classify_events(["大盘下滑，两融余额三连降"]) == []
    assert classify_events(["基金浮亏名单出炉"]) == []


def test_real_hard_event_still_classifies():
    out = classify_events(["公司发布业绩预增公告，净利润预增"])
    assert out and out[0]["code"] == "earnings_beat"
    assert out[0]["polarity"] == 1


# ---- event_score: only hard events override ----------------------------------

def test_event_score_market_flow_only_falls_back_to_raw():
    # Even with override explicitly enabled, market-flow noise must not override.
    res = event_score(0.42, ["主力净流入榜单", "7只个股大宗交易"], enable_override=True)
    assert res["event_score_mode"] == "sentiment_fallback"
    assert res["event_score"] == 0.42  # raw kept, no override


def test_event_score_override_off_by_default():
    # Default (settings flag OFF) keeps raw sentiment even on a real hard event.
    res = event_score(0.0, ["公司收到监管处罚决定书，被立案调查"])
    assert res["event_score_mode"] == "sentiment_fallback"
    assert res["event_score"] == 0.0
    assert res["event_types"][0]["code"] == "regulatory_penalty"  # still reported


def test_event_score_hard_event_overrides_when_enabled():
    res = event_score(0.0, ["公司收到监管处罚决定书，被立案调查"], enable_override=True)
    assert res["event_score_mode"] == "event_override"
    assert res["event_score"] < 0  # negative hard event drives it down


# ---- analyze_news evidence floor (no company news -> neutral, no LLM call) ----

def test_analyze_news_evidence_floor_neutralises_and_skips_llm(monkeypatch):
    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda *_a, **_k: True)

    def _boom(*_a, **_k):  # must NOT be called when only noise is present
        raise AssertionError("LLM provider called on noise-only window")

    monkeypatch.setattr(sentiment, "get_provider", _boom)

    # The 兆易 603986 whipsaw window: sector-IPO headlines, zero company news.
    res = sentiment.analyze_news(
        ["长鑫上市在即 存储炒作能否有二波", "长鑫科技上市在即：撑起3万亿产业链"],
        symbol="603986",
        company_aliases=["兆易创新", "兆易", "603986"],
    )
    assert res["sentiment"] == 0.0
    assert res["event_score_mode"] == "evidence_floor"
    assert res.get("low_confidence") is True


def test_analyze_news_keeps_company_news_path(monkeypatch):
    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda *_a, **_k: True)
    sentiment._INPROC_CACHE.clear() if hasattr(sentiment, "_INPROC_CACHE") else None

    called = {"n": 0}

    class _Prov:
        def complete_structured(self, **_k):
            called["n"] += 1
            return {"sentiment": 0.6, "summary": "利好", "impact": "short", "key_events": []}

    monkeypatch.setattr(sentiment, "get_provider", lambda: _Prov())
    monkeypatch.setattr(sentiment, "_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_cache_set", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_set", lambda *_a, **_k: None)

    res = sentiment.analyze_news(["兆易创新发布业绩预增公告"], symbol="603986")
    assert called["n"] == 1  # company news -> LLM is consulted
    assert res["sentiment"] == 0.6


def test_analyze_news_sends_only_company_specific_titles_to_llm(monkeypatch):
    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda *_a, **_k: True)
    monkeypatch.setattr(sentiment, "_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_cache_set", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_set", lambda *_a, **_k: None)

    captured = {}

    class _Prov:
        def complete_structured(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return {"sentiment": 0.4, "summary": "偏正", "impact": "short", "key_events": []}

    monkeypatch.setattr(sentiment, "get_provider", lambda: _Prov())

    res = sentiment.analyze_news(
        [
            "兆易创新发布业绩预增公告",
            "长鑫科技上市在即：撑起3万亿产业链",
            "主力资金净流入这些股",
        ],
        symbol="603986",
        company_aliases=["兆易创新", "603986"],
    )

    assert res["sentiment"] == 0.4
    assert "兆易创新发布业绩预增公告" in captured["prompt"]
    assert "长鑫科技上市在即" not in captured["prompt"]
    assert "主力资金净流入" not in captured["prompt"]


def test_backtest_news_cache_passes_company_aliases(monkeypatch, tmp_path, test_db):
    from backend.backtest import news_cache
    from backend.data.database import NewsItem, Stock

    test_db.add(Stock(symbol="603986", name="兆易创新", market="CN", active=True))
    test_db.add_all([
        NewsItem(
            symbol="603986",
            title="长鑫科技上市在即：撑起3万亿产业链",
            url="https://example.com/changxin",
            published_at=datetime(2026, 6, 15, 10, 0, 0),
            source="test",
        ),
        NewsItem(
            symbol="603986",
            title="兆易创新发布业绩预增公告",
            url="https://example.com/giga",
            published_at=datetime(2026, 6, 15, 11, 0, 0),
            source="test",
        ),
    ])
    test_db.commit()
    monkeypatch.setattr(news_cache, "_CACHE_FILE", tmp_path / "sentiment-cache.json")

    captured = {}

    def fake_analyze_news(titles, symbol, company_aliases=None):
        captured["titles"] = titles
        captured["symbol"] = symbol
        captured["company_aliases"] = company_aliases
        return {"sentiment": 0.0, "summary": "ok", "impact": "short", "key_events": []}

    monkeypatch.setattr("backend.analysis.sentiment.analyze_news", fake_analyze_news)

    news_cache.get_or_backfill("603986", "2026-06-15", test_db, use_llm=True)

    assert captured["symbol"] == "603986"
    assert captured["company_aliases"] == ["兆易创新", "603986"]
    assert "兆易创新发布业绩预增公告" in captured["titles"]


def test_analyze_news_uses_configured_sentiment_model_tier(monkeypatch):
    # Sentiment must score with the configured tier (default "capable" → sonnet-4.6),
    # not the hardcoded "fast" tier. Clean OOS measured IC 0.0735 (sonnet) vs ~0.02 (fast).
    from backend.config import settings

    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda *_a, **_k: True)
    monkeypatch.setattr(sentiment, "_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_cache_set", lambda *_a, **_k: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_set", lambda *_a, **_k: None)
    monkeypatch.setattr(settings, "sentiment_model_tier", "capable")

    captured = {}

    class _Prov:
        def complete_structured(self, **kwargs):
            captured["model_tier"] = kwargs.get("model_tier")
            return {"sentiment": 0.3, "summary": "ok", "impact": "short", "key_events": []}

    monkeypatch.setattr(sentiment, "get_provider", lambda: _Prov())

    sentiment.analyze_news(["兆易创新发布业绩预增公告"], symbol="603986")
    assert captured["model_tier"] == "capable"
