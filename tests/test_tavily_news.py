class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_titles_tavily_bypasses_system_proxy(monkeypatch):
    from backend.config import settings
    from backend.data.news import search_titles_tavily

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    calls = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, url, json, timeout):
            calls.append((self.trust_env, url, json, timeout))
            return _FakeResponse({"results": [{"title": "兆易创新：存储芯片订单增长"}]})

    monkeypatch.setattr("requests.Session", FakeSession)

    titles = search_titles_tavily("兆易创新 603986 股票 最新消息")

    assert titles == ["兆易创新：存储芯片订单增长"]
    assert calls[0][0] is False


def test_postmarket_news_sentiment_uses_tavily_even_when_local_titles_meet_threshold(
    monkeypatch,
):
    from backend.config import settings
    from backend.scheduler import _postmarket_news_sentiment

    class Stock:
        symbol = "603986"
        name = "兆易创新"

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    monkeypatch.setattr(settings, "ai_provider", "disabled")
    monkeypatch.setattr(settings, "tavily_supplement_threshold", 3)
    monkeypatch.setattr("backend.data.news.get_recent_news_items", lambda symbol, db, hours: [])

    def fake_audited_titles(items, **kwargs):
        return ["本地新闻1", "本地新闻2", "本地新闻3"], []

    captured = {}

    monkeypatch.setattr("backend.data.news_audit.audited_titles", fake_audited_titles)
    monkeypatch.setattr("backend.data.news.fetch_stock_news_anspire", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.data.news.fetch_titles_tavily", lambda symbol, name: ["Tavily新闻"])

    def fake_analyze_news(titles, symbol):
        captured["titles"] = titles
        return {"sentiment": 0.0}

    monkeypatch.setattr("backend.analysis.sentiment.analyze_news", fake_analyze_news)

    result = _postmarket_news_sentiment(Stock(), db=object())

    assert result["sentiment"] == 0.0
    assert captured["titles"] == ["本地新闻1", "本地新闻2", "本地新闻3", "Tavily新闻"]
