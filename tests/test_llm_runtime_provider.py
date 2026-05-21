from unittest.mock import MagicMock, patch

from backend.agents.analyst import AnalystReport
from backend.agents.researcher import multi_round_debate
from backend.decision import aggregator


def _reports(scores: list[float]) -> list[AnalystReport]:
    roles = ["technical", "quant", "sentiment", "news"]
    return [
        AnalystReport(
            role=roles[i],
            score=score,
            confidence=0.5,
            key_findings=[f"{roles[i]} {score:+.0f}"],
            raw={},
        )
        for i, score in enumerate(scores)
    ]


def _mock_provider(outputs: list[dict]) -> MagicMock:
    provider = MagicMock()
    provider.complete_structured.side_effect = outputs
    return provider


def test_local_cli_runtime_provider_is_available_without_cloud_keys():
    from backend.llm.factory import has_runtime_llm_provider

    with patch("backend.llm.factory.settings") as mock_settings:
        mock_settings.ai_provider = "local_cli"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""

        assert has_runtime_llm_provider() is True


def test_cloud_runtime_provider_requires_matching_key():
    from backend.llm.factory import has_runtime_llm_provider

    with patch("backend.llm.factory.settings") as mock_settings:
        mock_settings.ai_provider = "anthropic"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = "openai-key"
        assert has_runtime_llm_provider() is False

        mock_settings.ai_provider = "openai"
        mock_settings.openai_api_key = ""
        mock_settings.anthropic_api_key = "anthropic-key"
        assert has_runtime_llm_provider() is False


@patch("backend.agents.researcher.get_provider")
def test_multi_round_debate_uses_local_cli_without_cloud_keys(mock_get_provider):
    mock_get_provider.return_value = _mock_provider([
        {"points": ["技术转强"], "key_signal": "technical"},
        {"rebuttals": [{"target": "技术转强", "counter": "估值偏高"}], "additional_bears": []},
        {
            "bull_response": ["量能确认"],
            "winning_side": "bull",
            "action_bias": "偏多",
            "rationale": "本地 runtime 完成裁定",
        },
    ])
    with patch("backend.agents.researcher.settings") as mock_settings:
        mock_settings.multi_round_debate_enabled = True
        mock_settings.ai_provider = "local_cli"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""
        mock_settings.multi_round_debate_min_divergence = 20.0

        conclusion = multi_round_debate(_reports([60, -30, 20, -10]))

    assert conclusion.used_llm is True
    assert conclusion.action_bias == "偏多"
    mock_get_provider.assert_called_once()


@patch("backend.decision.aggregator.get_provider")
def test_bull_bear_debate_uses_local_cli_without_cloud_keys(mock_get_provider):
    mock_get_provider.return_value = _mock_provider([
        {
            "bull_points": ["技术走强"],
            "bear_points": ["估值压力"],
            "action_bias": "中性",
            "rationale": "分歧较大，等待确认",
        },
    ])
    with patch("backend.decision.aggregator.settings") as mock_settings:
        mock_settings.ai_provider = "local_cli"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""

        result = aggregator._bull_bear_debate(
            composite_score=10,
            quant_score=70,
            tech_result={"score": -20, "latest": {"rsi14": 45}},
            sentiment_result={"sentiment": 0.1, "key_events": ["订单改善"]},
            close=10.0,
            stop_loss=9.0,
            take_profit=12.0,
        )

    assert result["action_bias"] == "中性"
    mock_get_provider.assert_called_once()
