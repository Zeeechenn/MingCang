from datetime import datetime

from backend.data.news_clustering import EventCluster
from backend.data.news_scope import (
    classify_scope,
    plan_scope_sharing,
    shared_digest_key,
)

BASE_TIME = datetime(2026, 7, 2, 9, 30, 0)


def _cluster(
    *,
    cluster_id: str,
    symbol: str,
    title: str,
    event_type: str = "unknown",
    entities: list[str],
    source_diversity: int = 1,
    first_seen: datetime = BASE_TIME,
) -> EventCluster:
    return EventCluster(
        cluster_id=cluster_id,
        symbol=symbol,
        members=[],
        event_type=event_type,
        representative_title=title,
        source_diversity=source_diversity,
        entities=entities,
        first_seen=first_seen,
    )


def _policy_cluster(cluster_id: str = "evt_600000_policy", symbol: str = "600000") -> EventCluster:
    return _cluster(
        cluster_id=cluster_id,
        symbol=symbol,
        title="证监会发布新规范新股发行监管要求",
        event_type="regulatory",
        entities=[symbol],
    )


def _market_cluster(cluster_id: str = "evt_000001_market", symbol: str = "000001") -> EventCluster:
    return _cluster(
        cluster_id=cluster_id,
        symbol=symbol,
        title="大盘全天震荡收跌两市成交额萎缩",
        event_type="unknown",
        entities=[symbol],
    )


def _sector_cluster(cluster_id: str = "evt_300750_sector", symbol: str = "300750") -> EventCluster:
    return _cluster(
        cluster_id=cluster_id,
        symbol=symbol,
        title="半导体行业机构集体看好，宁德时代长鑫存储同步受益",
        event_type="opinion",
        entities=[symbol, "宁德时代", "长鑫存储"],
    )


def _stock_cluster(cluster_id: str = "evt_603986_stock", symbol: str = "603986") -> EventCluster:
    return _cluster(
        cluster_id=cluster_id,
        symbol=symbol,
        title="兆易创新签署存储芯片采购合同",
        event_type="contract",
        entities=[symbol, "兆易创新"],
    )


# --- 四域分类边界 ---


def test_classify_scope_policy_keyword_wins():
    assert classify_scope(_policy_cluster()) == "policy"


def test_classify_scope_market_no_company_entity():
    assert classify_scope(_market_cluster()) == "market"


def test_classify_scope_sector_needs_multiple_company_entities():
    assert classify_scope(_sector_cluster()) == "sector"


def test_classify_scope_sector_falls_back_to_stock_with_single_entity():
    single_entity_cluster = _cluster(
        cluster_id="evt_300750_single",
        symbol="300750",
        title="半导体行业机构集体看好宁德时代",
        event_type="opinion",
        entities=["300750", "宁德时代"],
    )
    assert classify_scope(single_entity_cluster) == "stock"


def test_classify_scope_default_stock():
    assert classify_scope(_stock_cluster()) == "stock"


# --- 共享键稳定性 ---


def test_shared_digest_key_stable_for_same_cluster_same_day():
    cluster = _policy_cluster()
    key1 = shared_digest_key("policy", cluster, BASE_TIME)
    key2 = shared_digest_key("policy", cluster, BASE_TIME)
    assert key1 == key2


def test_shared_digest_key_same_day_different_cluster_id_collapses_for_shared_scope():
    # 两条不同 cluster_id 的政策簇，只要 event_type + 日期相同，应产出同一份共享键
    # （这正是域共享要实现的“同域同天只打一次分”）。
    cluster_a = _policy_cluster(cluster_id="evt_600000_policy_a", symbol="600000")
    cluster_b = _policy_cluster(cluster_id="evt_600519_policy_b", symbol="600519")
    key_a = shared_digest_key("policy", cluster_a, BASE_TIME)
    key_b = shared_digest_key("policy", cluster_b, BASE_TIME)
    assert key_a == key_b


def test_shared_digest_key_changes_across_days():
    cluster = _policy_cluster()
    key_day1 = shared_digest_key("policy", cluster, BASE_TIME)
    key_day2 = shared_digest_key("policy", cluster, datetime(2026, 7, 3, 9, 30, 0))
    assert key_day1 != key_day2


def test_shared_digest_key_stock_scope_is_per_cluster():
    cluster_a = _stock_cluster(cluster_id="evt_603986_a", symbol="603986")
    cluster_b = _stock_cluster(cluster_id="evt_603986_b", symbol="603986")
    key_a = shared_digest_key("stock", cluster_a, BASE_TIME)
    key_b = shared_digest_key("stock", cluster_b, BASE_TIME)
    assert key_a != key_b


# --- 调用数估算 ---


def test_plan_scope_sharing_reduces_llm_calls_below_naive():
    clusters = [
        _policy_cluster(cluster_id="evt_600000_policy_a", symbol="600000"),
        _policy_cluster(cluster_id="evt_600519_policy_b", symbol="600519"),
        _policy_cluster(cluster_id="evt_601988_policy_c", symbol="601988"),
        _stock_cluster(cluster_id="evt_603986_stock", symbol="603986"),
        _stock_cluster(cluster_id="evt_002594_stock", symbol="002594"),
    ]

    plan = plan_scope_sharing(clusters, symbols=["600000", "600519", "601988", "603986", "002594"])

    assert plan.naive_llm_calls == 5
    # 三条政策簇共享一次打分 + 两条个股簇各自打分 = 3
    assert plan.shared_llm_calls == 3
    assert plan.estimated_savings == 2
    assert plan.shared_llm_calls < plan.naive_llm_calls
    assert set(plan.stock_only_clusters) == {"evt_603986_stock", "evt_002594_stock"}
    assert len(plan.shared_clusters) == 1
    shared_key = next(iter(plan.shared_clusters))
    assert sorted(plan.shared_clusters[shared_key]) == [
        "evt_600000_policy_a",
        "evt_600519_policy_b",
        "evt_601988_policy_c",
    ]


def test_plan_scope_sharing_all_stock_only_has_no_savings():
    clusters = [
        _stock_cluster(cluster_id="evt_603986_stock", symbol="603986"),
        _stock_cluster(cluster_id="evt_002594_stock", symbol="002594"),
    ]

    plan = plan_scope_sharing(clusters)

    assert plan.naive_llm_calls == 2
    assert plan.shared_llm_calls == 2
    assert plan.estimated_savings == 0
    assert plan.shared_clusters == {}


def test_plan_scope_sharing_records_scope_per_cluster():
    clusters = [_policy_cluster(), _market_cluster(), _sector_cluster(), _stock_cluster()]
    plan = plan_scope_sharing(clusters)

    assert plan.scope_by_cluster[clusters[0].cluster_id] == "policy"
    assert plan.scope_by_cluster[clusters[1].cluster_id] == "market"
    assert plan.scope_by_cluster[clusters[2].cluster_id] == "sector"
    assert plan.scope_by_cluster[clusters[3].cluster_id] == "stock"
