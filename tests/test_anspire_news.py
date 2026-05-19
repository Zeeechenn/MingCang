from datetime import datetime


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_stock_news_anspire_returns_filtered_event_items(monkeypatch):
    from backend.config import settings
    from backend.data.news import fetch_stock_news_anspire

    monkeypatch.setattr(settings, "anspire_api_key", "test-key")

    def fake_get(url, params, headers, timeout):
        assert "plugin.anspire.cn" in url
        assert headers["Authorization"] == "Bearer test-key"
        return _FakeResponse({
            "results": [
                {
                    "title": "五粮液：回购方案获临时股东会审议通过",
                    "content": "五粮液 000858 回购方案通过",
                    "url": "https://finance.eastmoney.com/a/202605181.html",
                    "date": "2026-05-18 09:30:00",
                },
                {
                    "title": "五粮液(000858)财务摘要_新浪财经_新浪网",
                    "content": "行情资料",
                    "url": "https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/000858.phtml",
                    "date": "2026-05-18 09:31:00",
                },
                {
                    "title": "五粮液股份有限公司",
                    "content": "公司资料",
                    "url": "https://www.qcc.com/firm/example.html",
                    "date": "2026-05-18 09:32:00",
                },
                {
                    "title": "五粮液 124.00(0.10%)_公司公告_新浪财经_新浪网",
                    "content": "公告栏目页",
                    "url": "https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllBulletin/stockid/000858.phtml",
                    "date": "2026-05-18 09:32:30",
                },
                {
                    "title": "白酒板块今日走强",
                    "content": "未点名个股",
                    "url": "https://finance.sina.cn/news/example.html",
                    "date": "2026-05-18 09:33:00",
                },
            ]
        })

    monkeypatch.setattr("requests.get", fake_get)

    items = fetch_stock_news_anspire("000858", "五粮液", now=datetime(2026, 5, 19, 10, 0, 0))

    assert [item.title for item in items] == ["五粮液：回购方案获临时股东会审议通过"]
    assert items[0].source == "finance.eastmoney.com"
    assert items[0].symbol == "000858"


def test_fetch_stock_news_anspire_disabled_without_key(monkeypatch):
    from backend.config import settings
    from backend.data.news import fetch_stock_news_anspire

    monkeypatch.setattr(settings, "anspire_api_key", "")

    def fail_get(*args, **kwargs):
        raise AssertionError("Anspire should not be called without a key")

    monkeypatch.setattr("requests.get", fail_get)

    assert fetch_stock_news_anspire("000858", "五粮液") == []


def test_fetch_stock_news_anspire_limits_added_items(monkeypatch):
    from backend.config import settings
    from backend.data.news import fetch_stock_news_anspire

    monkeypatch.setattr(settings, "anspire_api_key", "test-key")

    def fake_get(url, params, headers, timeout):
        return _FakeResponse({
            "results": [
                {
                    "title": f"五粮液：第{i}条回购公告",
                    "content": "五粮液 000858 回购",
                    "url": f"https://finance.eastmoney.com/a/{i}.html",
                    "date": "2026-05-18 09:30:00",
                }
                for i in range(5)
            ]
        })

    monkeypatch.setattr("requests.get", fake_get)

    items = fetch_stock_news_anspire("000858", "五粮液", limit=2)

    assert len(items) == 2
