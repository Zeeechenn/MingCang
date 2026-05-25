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
