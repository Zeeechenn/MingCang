from datetime import datetime


def test_news_evidence_marks_content_status_from_content():
    from backend.data.news_evidence import NewsEvidence

    with_content = NewsEvidence(
        symbol="600519",
        title="贵州茅台公告",
        url="https://example.com/a",
        published_at=datetime(2026, 6, 28, 9, 30, 0),
        source_name="东方财富",
        provider="eastmoney",
        content=" 贵州茅台公告正文 ",
    )
    title_only = NewsEvidence(
        symbol="600519",
        title="贵州茅台公告",
        url="https://example.com/b",
        published_at=datetime(2026, 6, 28, 9, 31, 0),
        source_name="东方财富",
        provider="eastmoney",
        content=" ",
    )

    assert with_content.content == "贵州茅台公告正文"
    assert with_content.content_status == "full"
    assert title_only.content is None
    assert title_only.content_status == "title_only"


def test_evidence_from_raw_news_maps_legacy_fields_and_provider_fallback():
    from backend.data.news_evidence import evidence_from_raw_news
    from backend.data.news_models import RawNews

    fetched_at = datetime(2026, 6, 28, 10, 0, 0)
    raw = RawNews(
        title="贵州茅台公告",
        url="https://example.com/raw",
        published_at=datetime(2026, 6, 28, 9, 30, 0),
        source="东方财富",
        symbol=None,
        content="正文",
        provider=None,
    )

    evidence = evidence_from_raw_news(
        raw,
        symbol="600519",
        provider="eastmoney",
        fetched_at=fetched_at,
    )

    assert evidence.symbol == "600519"
    assert evidence.title == raw.title
    assert evidence.url == raw.url
    assert evidence.published_at == raw.published_at
    assert evidence.source_name == "东方财富"
    assert evidence.provider == "eastmoney"
    assert evidence.content == "正文"
    assert evidence.fetched_at == fetched_at
    assert evidence.raw is None


def test_eastmoney_adapter_wraps_existing_fetcher(monkeypatch):
    from backend.data.news_adapters.eastmoney import EastmoneyAdapter
    from backend.data.news_evidence import NewsWindow
    from backend.data.news_models import RawNews

    calls = []

    def fake_fetch(symbol: str, limit: int = 20):
        calls.append((symbol, limit))
        return [
            RawNews(
                title="贵州茅台公告",
                url="https://example.com/eastmoney",
                published_at=datetime(2026, 6, 28, 9, 30, 0),
                source="东方财富",
                symbol=symbol,
                content="东财正文",
                provider="eastmoney",
            )
        ]

    monkeypatch.setattr("backend.data.news_adapters.eastmoney.fetch_stock_news_cn", fake_fetch)

    rows = EastmoneyAdapter().fetch("600519", NewsWindow(lookback_days=3, limit=7))

    assert calls == [("600519", 7)]
    assert len(rows) == 1
    assert rows[0].provider == "eastmoney"
    assert rows[0].source_name == "东方财富"
    assert rows[0].content == "东财正文"
    assert rows[0].content_status == "full"


def test_anspire_adapter_wraps_existing_fetcher_with_name_and_window(monkeypatch):
    from backend.data.news_adapters.anspire import AnspireAdapter
    from backend.data.news_evidence import NewsWindow
    from backend.data.news_models import RawNews

    calls = []

    def fake_fetch(
        symbol: str,
        name: str,
        *,
        days: int | None = None,
        max_results: int | None = None,
        limit: int | None = None,
    ):
        calls.append((symbol, name, days, max_results, limit))
        return [
            RawNews(
                title="五粮液：回购方案获通过",
                url="https://example.com/anspire",
                published_at=datetime(2026, 6, 28, 9, 30, 0),
                source="finance.eastmoney.com",
                symbol=symbol,
                content=None,
                provider="anspire",
            )
        ]

    monkeypatch.setattr("backend.data.news_adapters.anspire.fetch_stock_news_anspire", fake_fetch)

    adapter = AnspireAdapter(name_resolver=lambda symbol: "五粮液")
    rows = adapter.fetch("000858", NewsWindow(lookback_days=5, limit=2, max_results=11))

    assert calls == [("000858", "五粮液", 5, 11, 2)]
    assert len(rows) == 1
    assert rows[0].provider == "anspire"
    assert rows[0].source_name == "finance.eastmoney.com"
    assert rows[0].content is None
    assert rows[0].content_status == "title_only"


def test_tavily_adapter_maps_titles_to_title_only_evidence(monkeypatch):
    from backend.data.news_adapters.tavily import TavilyAdapter
    from backend.data.news_evidence import NewsWindow

    calls = []

    def fake_fetch(symbol: str, name: str, days: int = 1, max_results: int = 5):
        calls.append((symbol, name, days, max_results))
        return ["贵州茅台：回购计划推进", "贵州茅台发布经营数据"]

    monkeypatch.setattr("backend.data.news_adapters.tavily.fetch_titles_tavily", fake_fetch)

    as_of = datetime(2026, 6, 28, 15, 0, 0)
    adapter = TavilyAdapter(name_resolver=lambda symbol: "贵州茅台")
    rows = adapter.fetch("600519", NewsWindow(lookback_days=3, max_results=9, as_of=as_of))

    assert calls == [("600519", "贵州茅台", 3, 9)]
    assert [row.title for row in rows] == ["贵州茅台：回购计划推进", "贵州茅台发布经营数据"]
    assert {row.provider for row in rows} == {"tavily"}
    assert {row.source_name for row in rows} == {"tavily"}
    assert all(row.content is None for row in rows)
    assert all(row.content_status == "title_only" for row in rows)
    assert all(row.published_at == as_of for row in rows)
    assert rows[0].url.startswith("tavily://600519#")
    assert rows[0].url != rows[1].url


def test_ifind_adapter_maps_full_content_news(monkeypatch):
    from backend.data.news_adapters.ifind import IFindAdapter
    from backend.data.news_evidence import NewsWindow
    from backend.data.news_models import RawNews

    calls = []

    def fake_fetch(symbol: str, name: str, days: int = 7, max_results: int = 20):
        calls.append((symbol, name, days, max_results))
        return [
            RawNews(
                title="五粮液公告：中期分红方案",
                url="https://notice.example/000858",
                published_at=datetime(2026, 6, 28, 15, 30, 0),
                source="notice.example",
                symbol=symbol,
                content="五粮液公告正文",
                provider="ifind",
            )
        ]

    monkeypatch.setattr("backend.data.news_adapters.ifind.fetch_news_ifind", fake_fetch)

    as_of = datetime(2026, 6, 28, 16, 0, 0)
    adapter = IFindAdapter(name_resolver=lambda symbol: "五粮液")
    rows = adapter.fetch("000858", NewsWindow(lookback_days=4, max_results=7, as_of=as_of))

    assert calls == [("000858", "五粮液", 4, 7)]
    assert adapter.provides_content is True
    assert len(rows) == 1
    assert rows[0].title == "五粮液公告：中期分红方案"
    assert rows[0].provider == "ifind"
    assert rows[0].source_name == "notice.example"
    assert rows[0].content == "五粮液公告正文"
    assert rows[0].content_status == "full"
    assert rows[0].published_at == datetime(2026, 6, 28, 15, 30, 0)
    assert rows[0].url == "https://notice.example/000858"


def test_title_only_adapters_return_empty_when_fetcher_has_no_titles(monkeypatch):
    from backend.data.news_adapters.ifind import IFindAdapter
    from backend.data.news_adapters.tavily import TavilyAdapter
    from backend.data.news_evidence import NewsWindow

    monkeypatch.setattr("backend.data.news_adapters.tavily.fetch_titles_tavily", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.data.news_adapters.ifind.fetch_news_ifind", lambda *args, **kwargs: [])

    assert TavilyAdapter().fetch("600519", NewsWindow()) == []
    assert IFindAdapter().fetch("600519", NewsWindow()) == []


def test_get_enabled_adapters_uses_config_order_as_priority(monkeypatch):
    from backend.config import settings
    from backend.data.news_adapters import get_enabled_adapters

    monkeypatch.setattr(settings, "news_adapters_enabled", ["tavily", "ifind", "anspire", "eastmoney"])

    adapters = get_enabled_adapters()

    assert [adapter.name for adapter in adapters] == ["tavily", "ifind", "anspire", "eastmoney"]
    assert [adapter.requires_key for adapter in adapters] == [True, True, True, False]
