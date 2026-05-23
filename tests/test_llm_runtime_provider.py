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


def test_disabled_runtime_provider_is_not_available():
    from backend.llm.factory import has_runtime_llm_provider

    with patch("backend.llm.factory.settings") as mock_settings:
        mock_settings.ai_provider = "disabled"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""

        assert has_runtime_llm_provider() is False


def test_provider_model_tiers_map_to_distinct_models():
    from backend.llm import anthropic_provider, openai_provider

    assert anthropic_provider._model_for_tier("fast") != anthropic_provider._model_for_tier("capable")
    assert openai_provider._model_for_tier("fast") != openai_provider._model_for_tier("capable")
    assert not openai_provider._model_for_tier("fast").startswith("anthropic/")


@patch("backend.llm.local_cli_provider.subprocess.run")
def test_local_cli_provider_passes_model_for_tier(mock_run, monkeypatch):
    from backend.llm.local_cli_provider import LocalCLIProvider

    mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
    monkeypatch.setattr("backend.config.settings.local_cli_model_fast", "claude-haiku")

    result = LocalCLIProvider(timeout=1).complete_structured(
        "prompt",
        {"name": "tool", "input_schema": {"type": "object"}},
        model_tier="fast",
    )

    assert result == {"ok": True}
    assert "--model" in mock_run.call_args.args[0]
    assert "claude-haiku" in mock_run.call_args.args[0]


@patch("backend.analysis.sentiment.get_provider")
def test_analyze_news_skips_provider_when_runtime_disabled(mock_get_provider):
    from backend.analysis import sentiment

    with patch("backend.analysis.sentiment.settings") as mock_settings:
        mock_settings.ai_provider = "disabled"
        mock_settings.anthropic_api_key = ""
        mock_settings.openai_api_key = ""

        result = sentiment.analyze_news(["订单改善"], symbol="600519")

    assert result["sentiment"] == 0.0
    assert result["summary"] == "LLM已禁用"
    mock_get_provider.assert_not_called()


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
