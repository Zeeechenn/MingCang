from datetime import datetime, timedelta

from backend.data.news_evidence import NewsEvidence

BASE_TIME = datetime(2026, 6, 28, 9, 30, 0)


def _evidence(
    title: str,
    *,
    url: str,
    provider: str = "eastmoney",
    minutes: int = 0,
    symbol: str = "603986",
) -> NewsEvidence:
    return NewsEvidence(
        symbol=symbol,
        title=title,
        url=url,
        published_at=BASE_TIME + timedelta(minutes=minutes),
        source_name=provider,
        provider=provider,
    )


def test_cluster_evidence_deduplicates_normalized_urls():
    from backend.data.news_clustering import cluster_evidence

    items = [
        _evidence(
            "兆易创新发布回购公告",
            url="HTTPS://Example.com/news/123?utm_source=x#section",
            provider="eastmoney",
        ),
        _evidence(
            "兆易创新发布回购公告",
            url="https://example.com/news/123?from=feed",
            provider="eastmoney",
            minutes=1,
        ),
    ]

    clusters = cluster_evidence(items)

    assert len(clusters) == 1
    assert len(clusters[0].members) == 1
    assert clusters[0].representative_title == "兆易创新发布回购公告"


def test_cluster_evidence_groups_similar_titles_from_nearby_sources():
    from backend.data.news_clustering import cluster_evidence

    items = [
        _evidence(
            "兆易创新拟回购股份用于员工持股计划",
            url="https://eastmoney.example.com/a",
            provider="eastmoney",
        ),
        _evidence(
            "兆易创新：拟回购公司股份 用于员工持股计划",
            url="https://anspire.example.com/b",
            provider="anspire",
            minutes=35,
        ),
    ]

    clusters = cluster_evidence(items)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert [member.provider for member in cluster.members] == ["eastmoney", "anspire"]
    assert cluster.source_diversity == 2
    assert cluster.event_type == "regulatory"
    assert cluster.representative_title == "兆易创新拟回购股份用于员工持股计划"
    assert "603986" in cluster.entities
    assert "兆易创新" in cluster.entities
    assert cluster.first_seen == BASE_TIME


def test_cluster_evidence_does_not_merge_similar_titles_outside_time_window():
    from backend.data.news_clustering import cluster_evidence

    items = [
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://example.com/a",
            provider="eastmoney",
        ),
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://example.com/b",
            provider="anspire",
            minutes=60 * 72,
        ),
    ]

    clusters = cluster_evidence(items)

    assert len(clusters) == 2
    assert [cluster.source_diversity for cluster in clusters] == [1, 1]


def test_source_diversity_counts_distinct_providers_not_article_count():
    from backend.data.news_clustering import cluster_evidence

    items = [
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://eastmoney.example.com/a",
            provider="eastmoney",
        ),
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://eastmoney.example.com/b",
            provider="eastmoney",
            minutes=3,
        ),
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://eastmoney.example.com/c",
            provider="eastmoney",
            minutes=6,
        ),
        _evidence(
            "兆易创新签署存储芯片供货合同",
            url="https://anspire.example.com/d",
            provider="anspire",
            minutes=9,
        ),
    ]

    clusters = cluster_evidence(items)

    assert len(clusters) == 1
    assert len(clusters[0].members) == 4
    assert clusters[0].source_diversity == 2


def test_cluster_evidence_lightly_filters_only_obvious_noise():
    from backend.data.news_clustering import cluster_evidence

    items = [
        _evidence("广告：免费领取股票课程", url="https://example.com/ad"),
        _evidence("600519 1688.00 +1.20%", url="https://example.com/quote"),
        _evidence("A股涨幅榜前十名单", url="https://example.com/rank"),
        _evidence("兆易创新中标存储芯片采购合同", url="https://example.com/contract"),
    ]

    clusters = cluster_evidence(items)

    assert len(clusters) == 1
    assert [member.title for member in clusters[0].members] == ["兆易创新中标存储芯片采购合同"]
    assert clusters[0].event_type == "contract"
