import json
from datetime import datetime


class _FakeIfindResult:
    def __init__(self, items: list[dict[str, str]]) -> None:
        self.text = json.dumps(
            {"data": {"data": json.dumps(items, ensure_ascii=False)}},
            ensure_ascii=False,
        )


def test_fetch_news_ifind_maps_news_and_notice_content_and_dedupes(monkeypatch):
    from backend.config import settings
    from backend.data import ifind_mcp
    from backend.data.news import fetch_news_ifind

    calls = []

    class FakeClient:
        def call_tool(self, mcp_id, tool, arguments):
            calls.append((mcp_id, tool, arguments))
            if tool == "search_news":
                return _FakeIfindResult(
                    [
                        {
                            "资讯标题": "兆易创新获得订单",
                            "资讯内容": "兆易创新新闻全文",
                            "日期": "2026-06-20 09:30:00",
                            "URL": "https://news.example.com/a",
                        },
                        {
                            "资讯标题": "重复 URL",
                            "资讯内容": "重复正文",
                            "日期": "2026-06-20",
                            "URL": "https://notice.example.com/b",
                        },
                    ]
                )
            return _FakeIfindResult(
                [
                    {
                        "公告标题": "兆易创新发布公告",
                        "公告内容": "兆易创新公告全文",
                        "日期": "2026-06-21",
                        "URL": "https://notice.example.com/b",
                    },
                    {
                        "公告标题": "兆易创新新增公告",
                        "公告内容": "新增公告全文",
                        "日期": "bad-date",
                        "URL": "",
                    },
                ]
            )

    monkeypatch.setattr(settings, "ifind_mcp_enabled", True)
    monkeypatch.setattr(settings, "ifind_mcp_token", "unit-token")
    monkeypatch.setattr(ifind_mcp, "IfindMcpClient", FakeClient)

    rows = fetch_news_ifind("603986", "兆易创新", days=3, max_results=9)

    assert [call[1] for call in calls] == ["search_news", "search_notice"]
    assert calls[0][2]["query"] == "兆易创新 603986"
    assert calls[0][2]["size"] == 9
    assert len(rows) == 3
    assert rows[0].title == "兆易创新获得订单"
    assert rows[0].content == "兆易创新新闻全文"
    assert rows[0].url == "https://news.example.com/a"
    assert rows[0].published_at == datetime(2026, 6, 20, 9, 30, 0)
    assert rows[0].source == "news.example.com"
    assert rows[0].provider == "ifind"
    assert rows[0].symbol == "603986"
    assert rows[1].title == "重复 URL"
    assert rows[1].url == "https://notice.example.com/b"
    assert rows[1].published_at == datetime(2026, 6, 20)
    assert rows[2].title == "兆易创新新增公告"
    assert rows[2].content == "新增公告全文"
    assert rows[2].url.startswith("ifind://603986#")
    assert rows[2].source == "ifind"


def test_fetch_news_ifind_returns_empty_when_disabled_or_without_token(monkeypatch):
    from backend.config import settings
    from backend.data import ifind_mcp
    from backend.data.news import fetch_news_ifind

    class FailClient:
        def __init__(self) -> None:
            raise AssertionError("disabled iFinD fetch should not instantiate client")

    monkeypatch.setattr(ifind_mcp, "IfindMcpClient", FailClient)
    monkeypatch.setattr(settings, "ifind_mcp_enabled", False)
    monkeypatch.setattr(settings, "ifind_mcp_token", "unit-token")
    assert fetch_news_ifind("603986", "兆易创新") == []

    monkeypatch.setattr(settings, "ifind_mcp_enabled", True)
    monkeypatch.setattr(settings, "ifind_mcp_token", "")
    assert fetch_news_ifind("603986", "兆易创新") == []
