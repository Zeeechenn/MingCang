"""M4.1 多轮辩论测试。

覆盖：
  • quick_consensus 无分歧
  • multi_round_debate 三轮全部成功
  • Round 1 失败降级为 quick_consensus
  • Round 2 失败降级为 Bull + 均值裁定
  • Round 3 失败降级为 Bull/Bear + 均值裁定
  • 无 API key 时降级为 quick_consensus
  • disabled 时降级为 quick_consensus
  • pipeline.run_pipeline 透传 rounds 字段
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.analyst import AnalystReport
from backend.agents.researcher import (
    DebateRound,
    ResearcherConclusion,
    conclusion_to_arbitration_dict,
    debate,
    has_divergence,
    multi_round_debate,
    quick_consensus,
)


def _reports(scores: list[float]) -> list[AnalystReport]:
    """生成一组分歧 reports（同份数量但分数可控）"""
    roles = ["technical", "quant", "sentiment", "news"]
    return [
        AnalystReport(
            role=roles[i], score=s, confidence=0.5,
            key_findings=[f"{roles[i]}信号{int(s):+d}"],
            raw={},
        )
        for i, s in enumerate(scores)
    ]


# ── quick_consensus ──────────────────────────────────────────────────

def test_quick_consensus_consistent_bullish():
    """四路均偏多 → bias=偏多，零 LLM"""
    conclusion = quick_consensus(_reports([30, 25, 20, 18]))
    assert conclusion.action_bias == "偏多"
    assert conclusion.used_llm is False
    assert conclusion.rounds == []


def test_quick_consensus_neutral():
    """方向接近 0 → 中性"""
    conclusion = quick_consensus(_reports([5, -5, 8, -3]))
    assert conclusion.action_bias == "中性"


def test_has_divergence_uses_configured_threshold():
    """不显式传 threshold 时，应使用 settings.multi_round_debate_min_divergence"""
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        assert has_divergence(_reports([45, -10, 10, 10])) is True


# ── multi_round_debate ───────────────────────────────────────────────

def _mock_provider(round_outputs: list[dict | None]) -> MagicMock:
    """让 provider.complete_structured 按顺序返回 round_outputs 各项"""
    provider = MagicMock()
    provider.complete_structured.side_effect = [
        out if out is not None else {} for out in round_outputs
    ]
    return provider


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_three_rounds_success(mock_get_provider):
    """三轮均成功，conclusion 包含 3 个 DebateRound"""
    mock_get_provider.return_value = _mock_provider([
        {"points": ["技术突破", "新闻利好", "情感转正"], "key_signal": "technical"},
        {
            "rebuttals": [
                {"target": "技术突破", "counter": "ADX < 20 震荡市"},
                {"target": "新闻利好", "counter": "事件已被消化"},
            ],
            "additional_bears": ["北上资金流出"],
        },
        {
            "bull_response": ["突破伴随放量", "事件影响中期"],
            "winning_side": "bull",
            "action_bias": "偏多",
            "rationale": "技术 + 量能 > 估值担忧",
        },
    ])
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = "fake"
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 20.0

        conclusion = multi_round_debate(_reports([60, -30, 20, -10]))

    assert conclusion.used_llm is True
    assert conclusion.action_bias == "偏多"
    assert len(conclusion.rounds) == 3
    assert conclusion.rounds[0].speaker == "bull"
    assert conclusion.rounds[1].speaker == "bear"
    assert conclusion.rounds[2].speaker == "adjudicator"
    assert conclusion.bull_points == ["技术突破", "新闻利好", "情感转正"]
    assert "ADX < 20 震荡市" in conclusion.bear_points
    assert "北上资金流出" in conclusion.bear_points


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_round1_failure_falls_back(mock_get_provider):
    """Round 1 LLM 失败 → quick_consensus"""
    mock_get_provider.return_value = _mock_provider([None])
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = "fake"
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 20.0

        conclusion = multi_round_debate(_reports([60, -30, 20, -10]))

    assert conclusion.used_llm is False
    assert conclusion.rounds == []


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_round2_failure_falls_back_to_bull_only(mock_get_provider):
    """Round 2 失败 → 只剩 Bull 开场 + 均值 bias"""
    mock_get_provider.return_value = _mock_provider([
        {"points": ["技术突破"], "key_signal": "technical"},
        None,
    ])
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = "fake"
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 20.0

        # 均值为 0 → 中性
        conclusion = multi_round_debate(_reports([60, -60, 30, -30]))

    assert conclusion.used_llm is True
    assert len(conclusion.rounds) == 1
    assert conclusion.bull_points == ["技术突破"]
    assert conclusion.bear_points == []
    assert conclusion.action_bias == "中性"


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_round3_failure_falls_back_to_two_rounds(mock_get_provider):
    """Round 3 失败 → 前两轮 + 均值"""
    mock_get_provider.return_value = _mock_provider([
        {"points": ["技术突破"], "key_signal": "technical"},
        {"rebuttals": [{"target": "技术突破", "counter": "ADX 弱"}], "additional_bears": []},
        None,
    ])
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = "fake"
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 20.0

        conclusion = multi_round_debate(_reports([50, -30, 20, -10]))

    assert conclusion.used_llm is True
    assert len(conclusion.rounds) == 2
    # avg = (50 - 30 + 20 - 10) / 4 = 7.5 → 中性
    assert conclusion.action_bias == "中性"


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_no_api_key_falls_back(mock_get_provider):
    """无 API key → quick_consensus，零 LLM"""
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = None
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 20.0

        conclusion = multi_round_debate(_reports([60, -30, 20, -10]))

    assert conclusion.used_llm is False
    mock_get_provider.assert_not_called()


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_disabled_falls_back(mock_get_provider):
    """multi_round_debate_enabled=False → quick_consensus"""
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = False
        mock_settings.anthropic_api_key = "fake"

        conclusion = multi_round_debate(_reports([60, -30, 20, -10]))

    assert conclusion.used_llm is False
    mock_get_provider.assert_not_called()


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_skip_when_no_divergence(mock_get_provider):
    """分歧不达阈值 → quick_consensus"""
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.anthropic_api_key = "fake"
        mock_settings.openai_api_key = None
        mock_settings.multi_round_debate_min_divergence = 50.0   # 高阈值

        conclusion = multi_round_debate(_reports([20, 15, 18, 22]))

    assert conclusion.used_llm is False
    mock_get_provider.assert_not_called()


# ── debate() 接受 rounds 透传 ────────────────────────────────────────

def test_debate_accepts_rounds_in_arbitration():
    """单轮 debate() 兼容多轮 arbitration dict（透传 rounds）"""
    arbitration = {
        "bull_points": ["a"],
        "bear_points": ["b"],
        "action_bias": "偏多",
        "rationale": "test",
        "rounds": [
            {"round_num": 1, "speaker": "bull", "points": ["a"], "references": ["technical"]},
        ],
    }
    conclusion = debate(_reports([60, -30, 20, -10]), llm_arbitration=arbitration)
    assert conclusion.used_llm is True
    assert len(conclusion.rounds) == 1
    assert conclusion.rounds[0].speaker == "bull"


def test_conclusion_to_arbitration_dict_round_trip():
    """conclusion → dict → debate() 可恢复全部字段"""
    conclusion = ResearcherConclusion(
        bull_points=["a"], bear_points=["b"],
        action_bias="偏多", rationale="r", used_llm=True,
        rounds=[
            DebateRound(round_num=1, speaker="bull", points=["a"], references=["technical"]),
            DebateRound(round_num=2, speaker="bear", points=["b"], references=["a"]),
        ],
    )
    arbitration = conclusion_to_arbitration_dict(conclusion)
    restored = debate(_reports([60, -30, 20, -10]), llm_arbitration=arbitration)
    assert len(restored.rounds) == 2
    assert restored.rounds[1].speaker == "bear"


# ── pipeline 透传 ────────────────────────────────────────────────────

def test_pipeline_passes_rounds_through():
    """run_pipeline 应把 rounds 写入 to_signal_dict 的 llm_arbitration"""
    from backend.agents.pipeline import run_pipeline

    arbitration_with_rounds = {
        "bull_points": ["技术信号强"],
        "bear_points": ["估值过高"],
        "action_bias": "偏多",
        "rationale": "测试",
        "rounds": [
            {"round_num": 1, "speaker": "bull", "points": ["技术信号强"], "references": []},
            {"round_num": 2, "speaker": "bear", "points": ["估值过高"], "references": []},
            {"round_num": 3, "speaker": "adjudicator", "points": ["技术胜"], "references": ["bull"]},
        ],
    }

    technical_result = {
        "score": 50, "raw_score": 50, "adx_factor": 1.0, "latest": {"rsi14": 55},
        "limit": {},
    }
    qlib_result = {"score": -20, "model": "lgbm"}
    sentiment_result = {"sentiment": 0.3, "impact": "short", "key_events": ["利好"]}

    decision = run_pipeline(
        technical_result=technical_result,
        qlib_result=qlib_result,
        sentiment_result=sentiment_result,
        close=100.0, atr=2.0,
        llm_arbitration=arbitration_with_rounds,
    )

    signal_dict = decision.to_signal_dict()
    rounds = signal_dict["llm_arbitration"].get("rounds")
    assert rounds is not None
    assert len(rounds) == 3
    assert rounds[2]["speaker"] == "adjudicator"
