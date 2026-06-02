class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_normalize_ohlcv_converts_common_columns_and_drops_bad_close():
    import pandas as pd

    from backend.data.market import _normalize_ohlcv

    frame = pd.DataFrame({
        "日期": ["2026-01-03", "2026-01-01", "2026-01-02"],
        "开盘": ["3.0", "1.0", "2.0"],
        "最高": ["3.5", "1.5", "2.5"],
        "最低": ["2.5", "0.5", "1.5"],
        "收盘": ["bad", "1.2", "2.2"],
        "成交量": ["300", "100", "200"],
    })

    normalized = _normalize_ohlcv(frame)

    assert list(normalized.index) == ["2026-01-01", "2026-01-02"]
    assert normalized.loc["2026-01-01", "open"] == 1.0
    assert normalized.loc["2026-01-02", "volume"] == 200


def test_normalize_ohlcv_requires_volume_column():
    import pandas as pd
    import pytest

    from backend.data.market import _normalize_ohlcv

    with pytest.raises(ValueError, match="missing OHLCV column: volume"):
        _normalize_ohlcv(pd.DataFrame({
            "date": ["2026-01-01"],
            "open": [1],
            "high": [2],
            "low": [1],
            "close": [1.5],
        }))


def test_eastmoney_stock_news_bypasses_system_proxy(monkeypatch):
    import sys
    from types import SimpleNamespace

    import pandas as pd

    from backend.data import news

    calls = []

    class FakeJSONPResponse:
        text = (
            'jQuery_stocksage({"result":{"cmsArticleWebOld":[{'
            '"title":"<em>贵州茅台</em>公告",'
            '"code":"202605260001",'
            '"date":"2026-05-26 12:00:00",'
            '"mediaName":"东方财富"'
            "}]}});"
        )

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, url, params, headers, timeout):
            calls.append((self.trust_env, url, params, headers, timeout))
            return FakeJSONPResponse()

    def fail_if_direct_get_is_used(*_args, **_kwargs):
        raise AssertionError("Eastmoney news should use a proxy-bypassing Session")

    monkeypatch.setattr("requests.Session", FakeSession)
    monkeypatch.setattr("requests.get", fail_if_direct_get_is_used)
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_news_em=lambda symbol: pd.DataFrame(),
    ))
    monkeypatch.setattr(news.time, "sleep", lambda _seconds: None)

    df = news._fetch_news_df("600519")

    assert calls[0][0] is False
    assert calls[0][1] == "https://search-api-web.eastmoney.com/search/jsonp"
    assert df.iloc[0]["新闻标题"] == "贵州茅台公告"


def test_fetch_stock_news_cn_deduplicates_generates_url_and_converts_cst(monkeypatch):
    import hashlib

    import pandas as pd

    from backend.data import news

    monkeypatch.setattr(news, "_fetch_news_df", lambda symbol: pd.DataFrame([
        {
            "新闻标题": "贵州茅台公告",
            "新闻链接": "https://example.com/a",
            "文章来源": "东方财富",
            "发布时间": "2026-05-26 12:00:00",
        },
        {
            "新闻标题": "重复链接",
            "新闻链接": "https://example.com/a",
            "文章来源": "东方财富",
            "发布时间": "2026-05-26 13:00:00",
        },
        {
            "新闻标题": "无链接标题",
            "新闻链接": "",
            "文章来源": "东财",
            "发布时间": "2026-05-26 14:00:00",
        },
    ]))

    rows = news.fetch_stock_news_cn("600519", limit=10)

    assert [row.title for row in rows] == ["贵州茅台公告", "无链接标题"]
    assert rows[0].published_at.isoformat() == "2026-05-26T04:00:00"
    digest = hashlib.md5("无链接标题".encode()).hexdigest()[:8]  # noqa: S324 - expected legacy URL key.
    assert rows[1].url == f"em://600519#{digest}"
    assert rows[1].symbol == "600519"


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


def test_postmarket_news_sentiment_skips_tavily_when_local_titles_meet_threshold(
    monkeypatch,
):
    """本地新闻数量已达 threshold 时，Tavily 不应被调用（节省 API 配额）。"""
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

    captured = {"tavily_called": False}

    monkeypatch.setattr("backend.data.news_audit.audited_titles", fake_audited_titles)
    monkeypatch.setattr("backend.data.news.fetch_stock_news_anspire", lambda *args, **kwargs: [])

    def fake_tavily(symbol, name):
        captured["tavily_called"] = True
        return ["Tavily新闻"]

    monkeypatch.setattr("backend.data.news.fetch_titles_tavily", fake_tavily)

    def fake_analyze_news(titles, symbol):
        captured["titles"] = titles
        return {"sentiment": 0.0}

    monkeypatch.setattr("backend.analysis.sentiment.analyze_news", fake_analyze_news)

    result = _postmarket_news_sentiment(Stock(), db=object())

    assert result["sentiment"] == 0.0
    # 本地已有 3 条 >= threshold=3，Tavily 不应被调用
    assert not captured["tavily_called"], "本地新闻已达阈值，Tavily 不应被调用"
    assert captured["titles"] == ["本地新闻1", "本地新闻2", "本地新闻3"]
