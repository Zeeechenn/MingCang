from unittest.mock import patch


def test_analyze_news_returns_cache_copy(monkeypatch):
    from backend.analysis import sentiment

    sentiment._cache.clear()
    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda settings: True)
    provider = type("Provider", (), {
        "complete_structured": lambda self, **kwargs: {
            "sentiment": 0.6,
            "summary": "偏正",
            "impact": "short",
            "key_events": ["订单改善"],
        }
    })()

    with patch("backend.analysis.sentiment.get_provider", return_value=provider):
        first = sentiment.analyze_news(["订单改善"], symbol="600519")
        first["sentiment"] = -1
        second = sentiment.analyze_news(["订单改善"], symbol="600519")

    assert second["sentiment"] == 0.6


def test_sentiment_cache_is_bounded():
    from backend.analysis import sentiment

    sentiment._cache.clear()
    for i in range(sentiment._CACHE_MAX_SIZE + 3):
        sentiment._cache_set(str(i), {"sentiment": i})

    assert len(sentiment._cache) == sentiment._CACHE_MAX_SIZE
    assert "0" not in sentiment._cache


def test_market_sentiment_uses_separate_prompt_and_cache(monkeypatch):
    from backend.analysis import sentiment

    sentiment._cache.clear()
    seen = []
    monkeypatch.setattr(sentiment, "has_runtime_llm_provider", lambda settings: True)
    monkeypatch.setattr(sentiment, "_persistent_cache_get", lambda _key: None)
    monkeypatch.setattr(sentiment, "_persistent_cache_set", lambda *args: None)
    provider = type("Provider", (), {
        "complete_structured": lambda self, **kwargs: seen.append(kwargs) or {
            "sentiment": 0.1,
            "summary": "neutral",
            "impact": "short",
            "key_events": [],
        }
    })()
    monkeypatch.setattr(sentiment, "get_provider", lambda: provider)

    sentiment.analyze_news(["earnings update"], symbol="AAPL", market="US")
    sentiment.analyze_news(["earnings update"], symbol="AAPL", market="HK")

    assert len(seen) == 2
    assert "美股" in seen[0]["system"]
    assert "港股" in seen[1]["system"]
    assert sentiment._cache_key(["same"], "AAPL", "US")[0].startswith("US:")
