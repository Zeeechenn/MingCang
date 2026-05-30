import pandas as pd
import pytest


def test_ifind_client_lists_tools(monkeypatch):
    from backend.data.ifind_mcp import IfindMcpClient

    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "get_stock_summary"}]}}

    class FakeSession:
        trust_env = True

        def post(self, url, headers, json, timeout):
            calls.update({
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
                "trust_env": self.trust_env,
            })
            return FakeResponse()

    def fake_session():
        return FakeSession()

    monkeypatch.setattr("backend.data.ifind_mcp.requests.Session", fake_session)

    client = IfindMcpClient(
        token="unit-token",
        base_url="https://ifind.test/ds-mcp-servers",
        timeout_seconds=3,
    )
    tools = client.list_tools("hexin-ifind-ds-stock-mcp")

    assert tools == [{"name": "get_stock_summary"}]
    assert calls["url"] == "https://ifind.test/ds-mcp-servers/hexin-ifind-ds-stock-mcp"
    assert calls["headers"]["Authorization"] == "unit-token"
    assert calls["json"]["method"] == "tools/list"
    assert calls["timeout"] == 3
    assert calls["trust_env"] is False


def test_ifind_client_call_tool_text(monkeypatch):
    from backend.data.ifind_mcp import IfindMcpClient

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jsonrpc": "2.0",
                "id": "stocksage-ifind",
                "result": {"content": [{"type": "text", "text": "hello"}]},
            }

    class FakeSession:
        trust_env = True

        def post(self, url, headers, json, timeout):
            return FakeResponse()

    monkeypatch.setattr("backend.data.ifind_mcp.requests.Session", FakeSession)

    result = IfindMcpClient(token="unit-token").call_tool(
        "hexin-ifind-ds-news-mcp",
        "search_news",
        {"query": "贵州茅台", "time_start": "2026-05-01", "time_end": "2026-05-30", "size": 5},
    )

    assert result.ok is True
    assert result.text == "hello"


def test_ifind_client_requires_token():
    from backend.data.ifind_mcp import IfindMcpClient

    with pytest.raises(ValueError, match="IFIND_MCP_TOKEN"):
        IfindMcpClient(token="").list_tools()


def test_parse_ifind_stock_daily_markdown_table():
    from backend.data.ifind_mcp import extract_stock_daily_table

    text = """
|证券代码|证券简称|日期|开盘价（单位：元）|最高价（单位：元）|最低价（单位：元）|收盘价（单位：元）|成交量|
|---|---|---|---|---|---|---|---|
|600519.SH|贵州茅台|20260529|1270.6|1329.0|1270.0|1326.0|764.7805万|
"""

    df = extract_stock_daily_table(text)

    assert isinstance(df, pd.DataFrame)
    assert df.index.tolist() == ["2026-05-29"]
    assert float(df.loc["2026-05-29", "close"]) == pytest.approx(1326.0)
    assert float(df.loc["2026-05-29", "volume"]) == pytest.approx(7_647_805.0)


def test_ifind_stock_daily_parser_rejects_incomplete_table():
    from backend.data.ifind_mcp import extract_stock_daily_table

    text = """
|证券代码|证券简称|日期|收盘价（单位：元）|
|---|---|---|---|
|600519.SH|贵州茅台|20260529|1326.0|
"""

    assert extract_stock_daily_table(text).empty


def test_parse_ifind_embedded_news_json():
    from backend.data.ifind_mcp import parse_embedded_json

    payload = '{"code":1,"data":"[{\\"资讯标题\\":\\"标题\\",\\"日期\\":\\"2026-05-26\\"}]"}'

    parsed = parse_embedded_json(payload)

    assert parsed[0]["资讯标题"] == "标题"


def test_probe_ifind_mcp_is_disabled_by_default(monkeypatch):
    from backend.config import settings
    from backend.data import ifind_mcp

    def fail_list(*args, **kwargs):
        raise AssertionError("disabled probe should not call iFinD")

    monkeypatch.setattr(settings, "ifind_mcp_enabled", False)
    monkeypatch.setattr(ifind_mcp.IfindMcpClient, "list_tools", fail_list)

    result = ifind_mcp.probe_ifind_mcp()

    assert result["ok"] is False
    assert result["enabled"] is False
    assert result["error"] == "IFIND_MCP_ENABLED=false"


def test_list_ifind_mcp_tools_is_disabled_by_default(monkeypatch):
    from backend.config import settings
    from backend.data import ifind_mcp

    def fail_session(*args, **kwargs):
        raise AssertionError("disabled tools/list should not call iFinD")

    monkeypatch.setattr(settings, "ifind_mcp_enabled", False)
    monkeypatch.setattr(settings, "ifind_mcp_token", "unit-token")
    monkeypatch.setattr(ifind_mcp.requests, "Session", fail_session)

    result = ifind_mcp.list_ifind_mcp_tools()

    assert result["ok"] is False
    assert result["enabled"] is False
    assert result["error"] == "IFIND_MCP_ENABLED=false"


def test_call_ifind_mcp_tool_parses_json_fence_and_markdown_table(monkeypatch):
    from backend.config import settings
    from backend.data import ifind_mcp

    class FakeSession:
        trust_env = True

        def post(self, url, headers, json, timeout):
            return type(
                "FakeResponse",
                (),
                {
                    "raise_for_status": lambda self: None,
                    "json": lambda self: {
                        "jsonrpc": "2.0",
                        "id": "stocksage-ifind",
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "```json\n"
                                        "{\"symbol\":\"600519\",\"close\":1326.0}\n"
                                        "```\n\n"
                                        "| 日期 | 收盘 |\n"
                                        "| --- | ---: |\n"
                                        "| 2026-05-29 | 1326.0 |"
                                    ),
                                }
                            ]
                        },
                    },
                },
            )()

    monkeypatch.setattr(settings, "ifind_mcp_enabled", True)
    monkeypatch.setattr(settings, "ifind_mcp_token", "unit-token")
    monkeypatch.setattr(settings, "ifind_mcp_qps_limit", 0.0)
    monkeypatch.setattr(ifind_mcp.requests, "Session", FakeSession)

    result = ifind_mcp.call_ifind_mcp_tool("get_stock_quote", {"symbol": "600519"})

    assert result["ok"] is True
    assert result["parsed"]["json"] == {"symbol": "600519", "close": 1326.0}
    assert result["parsed"]["tables"] == [
        {
            "headers": ["日期", "收盘"],
            "rows": [{"日期": "2026-05-29", "收盘": "1326.0"}],
        }
    ]
