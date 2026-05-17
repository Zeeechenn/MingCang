from datetime import datetime, timedelta


def test_audit_news_items_downweights_weak_and_stale_sources():
    from backend.data.news import RawNews
    from backend.data.news_audit import audit_news_items

    now = datetime(2026, 5, 17, 12, 0, 0)
    items = [
        RawNews(
            title="公司签订重大订单",
            url="https://finance.eastmoney.com/a/202605171234.html",
            published_at=now - timedelta(hours=2),
            source="东方财富",
            symbol="600519",
        ),
        RawNews(
            title="网传公司将重组",
            url="em://600519#deadbeef",
            published_at=now - timedelta(days=9),
            source="股吧",
            symbol="600519",
        ),
    ]

    audited = audit_news_items(items, now=now)

    assert audited[0].usable is True
    assert audited[0].score > audited[1].score
    assert audited[1].usable is False
    assert "stale" in audited[1].risk_flags
    assert "synthetic_url" in audited[1].risk_flags
    assert "weak_source" in audited[1].risk_flags


def test_audit_news_items_marks_duplicate_titles():
    from backend.data.news import RawNews
    from backend.data.news_audit import audit_news_items

    now = datetime(2026, 5, 17, 12, 0, 0)
    items = [
        RawNews("中际旭创业绩大增", "https://a.example/1", now, "证券时报", "300308"),
        RawNews("中际旭创业绩大增", "https://b.example/2", now, "新浪财经", "300308"),
    ]

    audited = audit_news_items(items, now=now)

    assert audited[0].duplicate_group == audited[1].duplicate_group
    assert "duplicate_title" in audited[1].risk_flags
    assert audited[1].score < audited[0].score


def test_audited_titles_keep_only_usable_items_ordered_by_score():
    from backend.data.news import RawNews
    from backend.data.news_audit import audited_titles

    now = datetime(2026, 5, 17, 12, 0, 0)
    items = [
        RawNews("弱来源旧闻", "em://x#1", now - timedelta(days=20), "股吧", "600519"),
        RawNews("交易所公告澄清", "https://www.sse.com.cn/disclosure", now, "上交所", "600519"),
        RawNews("普通财经报道", "https://finance.eastmoney.com/a/1.html", now, "东方财富", "600519"),
    ]

    titles, audits = audited_titles(items, now=now, min_score=50)

    assert titles == ["交易所公告澄清", "普通财经报道"]
    assert len(audits) == 3
