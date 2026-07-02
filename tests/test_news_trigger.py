from datetime import datetime, timedelta
from unittest.mock import patch

from backend.data.news_clustering import cluster_evidence
from backend.data.news_evidence import NewsEvidence
from backend.data.news_trigger import (
    MAIN_CAUSE_COMPANY_EVENT,
    MAIN_CAUSE_INDUSTRY_PEER,
    MAIN_CAUSE_MARKET_SENTIMENT,
    MAIN_CAUSE_REGULATION_POLICY,
    REASON_L0_EVENT_SCORE,
    REASON_NEW_ANNOUNCEMENT,
    REASON_POLICY_KEYWORD,
    REASON_PRICE_ANOMALY,
    REASON_PRICE_VOLUME_SKIPPED,
    REASON_SOURCE_DIVERSITY_SURGE,
    REASON_VOLUME_ANOMALY,
    PreviousTriggerState,
    decide_trigger,
)

BASE_TIME = datetime(2026, 6, 28, 9, 30, 0)
SYMBOL = "603986"


def _evidence(
    title: str,
    *,
    url: str,
    provider: str = "eastmoney",
    minutes: int = 0,
    symbol: str = SYMBOL,
) -> NewsEvidence:
    return NewsEvidence(
        symbol=symbol,
        title=title,
        url=url,
        published_at=BASE_TIME + timedelta(minutes=minutes),
        source_name=provider,
        provider=provider,
    )


def _clusters(items):
    return cluster_evidence(items)


def test_new_announcement_event_triggers():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新发布重大合同公告：中标5亿元订单",
                url="https://example.com/a1",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is True
    assert REASON_NEW_ANNOUNCEMENT in decision.reasons


def test_no_trigger_when_nothing_fires():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价小幅波动",
                url="https://example.com/b1",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is False
    assert decision.attribution_card is None
    # price/volume input missing must be recorded as a flag, not silently dropped
    assert REASON_PRICE_VOLUME_SKIPPED in decision.reasons


def test_price_volume_anomaly_triggers_when_injected():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价小幅波动",
                url="https://example.com/b2",
            )
        ]
    )
    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        price_change_pct=7.2,
        volume_ratio=1.0,
    )
    assert decision.triggered is True
    assert REASON_PRICE_ANOMALY in decision.reasons
    assert REASON_VOLUME_ANOMALY not in decision.reasons
    assert REASON_PRICE_VOLUME_SKIPPED not in decision.reasons


def test_volume_ratio_anomaly_triggers():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价小幅波动",
                url="https://example.com/b3",
            )
        ]
    )
    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        price_change_pct=0.1,
        volume_ratio=3.5,
    )
    assert decision.triggered is True
    assert REASON_VOLUME_ANOMALY in decision.reasons
    assert REASON_PRICE_ANOMALY not in decision.reasons


def test_price_volume_missing_flag_when_both_none():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价小幅波动",
                url="https://example.com/b4",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert REASON_PRICE_VOLUME_SKIPPED in decision.reasons


def test_policy_keyword_hit_triggers():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新收到监管问询函，暂无重大影响",
                url="https://example.com/c1",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is True
    assert REASON_POLICY_KEYWORD in decision.reasons


def test_source_diversity_surge_triggers():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/d1",
                provider="eastmoney",
            ),
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/d2",
                provider="sina",
                minutes=5,
            ),
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/d3",
                provider="tencent",
                minutes=10,
            ),
        ]
    )
    assert clusters[0].source_diversity == 3

    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        previous_state=PreviousTriggerState(max_source_diversity=0),
    )
    assert decision.triggered is True
    assert REASON_SOURCE_DIVERSITY_SURGE in decision.reasons


def test_source_diversity_surge_not_triggered_when_no_delta_vs_yesterday():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/e1",
                provider="eastmoney",
            ),
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/e2",
                provider="sina",
                minutes=5,
            ),
            _evidence(
                "兆易创新获多家机构集中关注",
                url="https://example.com/e3",
                provider="tencent",
                minutes=10,
            ),
        ]
    )
    assert clusters[0].source_diversity == 3

    # yesterday already had source_diversity=3, so no surge today (delta=0 < 2)
    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        previous_state=PreviousTriggerState(max_source_diversity=3),
    )
    assert REASON_SOURCE_DIVERSITY_SURGE not in decision.reasons


def test_l0_event_score_threshold_triggers():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新重大资产重组预案获批，预计影响重大",
                url="https://example.com/f1",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters, materiality_threshold=0.01)
    assert decision.triggered is True
    assert REASON_L0_EVENT_SCORE in decision.reasons


def test_l0_event_score_threshold_not_triggered_when_threshold_high():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价小幅波动",
                url="https://example.com/f2",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters, materiality_threshold=0.99)
    assert REASON_L0_EVENT_SCORE not in decision.reasons


def test_attribution_card_company_event_classification():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新与某集团签署重大合同：中标5亿元订单",
                url="https://example.com/g1",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is True
    card = decision.attribution_card
    assert card is not None
    assert card.main_cause == MAIN_CAUSE_COMPANY_EVENT
    assert card.thesis_recheck is True
    assert card.symbol == SYMBOL
    assert card.as_of == BASE_TIME
    assert len(card.timeline) == 1
    assert card.timeline[0]["title"].startswith("兆易创新")


def test_attribution_card_regulation_policy_classification():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新收到证监会立案调查通知，公司发布风险提示公告",
                url="https://example.com/g2",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is True
    card = decision.attribution_card
    assert card is not None
    assert card.main_cause == MAIN_CAUSE_REGULATION_POLICY
    assert card.thesis_recheck is True


def test_attribution_card_industry_peer_classification():
    clusters = _clusters(
        [
            _evidence(
                "半导体行业景气度回升，机器人芯片需求旺盛",
                url="https://example.com/g3",
            )
        ]
    )
    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        price_change_pct=6.0,
    )
    assert decision.triggered is True
    card = decision.attribution_card
    assert card is not None
    assert card.main_cause == MAIN_CAUSE_INDUSTRY_PEER
    assert card.thesis_recheck is False


def test_attribution_card_market_sentiment_fallback_classification():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新今日股价异动上涨",
                url="https://example.com/g4",
            )
        ]
    )
    decision = decide_trigger(
        SYMBOL,
        BASE_TIME,
        clusters,
        price_change_pct=8.0,
        volume_ratio=1.0,
    )
    assert decision.triggered is True
    card = decision.attribution_card
    assert card is not None
    assert card.main_cause == MAIN_CAUSE_MARKET_SENTIMENT
    assert card.thesis_recheck is False


def test_timeline_sorted_chronologically_across_clusters():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新签署重大合同：中标5亿元订单",
                url="https://example.com/h1",
                minutes=30,
            ),
            _evidence(
                "兆易创新发布股价异动公告",
                url="https://example.com/h2",
                minutes=0,
            ),
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is True
    card = decision.attribution_card
    assert card is not None
    times = [entry["time"] for entry in card.timeline]
    assert times == sorted(times)


def test_clusters_for_other_symbol_are_ignored():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新发布重大合同公告：中标5亿元订单",
                url="https://example.com/i1",
                symbol="000001",
            )
        ]
    )
    decision = decide_trigger(SYMBOL, BASE_TIME, clusters)
    assert decision.triggered is False
    assert decision.attribution_card is None


def test_decide_trigger_makes_zero_llm_calls():
    clusters = _clusters(
        [
            _evidence(
                "兆易创新发布重大合同公告：中标5亿元订单，收到监管问询",
                url="https://example.com/j1",
            )
        ]
    )
    with patch("backend.llm.factory.get_provider") as mock_get_provider:
        decision = decide_trigger(
            SYMBOL,
            BASE_TIME,
            clusters,
            price_change_pct=9.0,
            volume_ratio=4.0,
        )
        assert decision.triggered is True
        mock_get_provider.assert_not_called()
