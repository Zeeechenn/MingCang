import json

from backend.agents import pipeline
from backend.agents.analyst import AnalystReport


def _report(role: str, score: float = 20.0) -> AnalystReport:
    return AnalystReport(
        role=role,
        score=score,
        confidence=0.8,
        key_findings=[f"{role} finding"],
        raw={"events": ["event"]} if role == "news" else {},
    )


def test_build_research_context_merges_sections_and_reflection_lines():
    sentiment_result = {
        "deep_research": {
            "evidence_json": json.dumps({
                "sections": [
                    {
                        "role": "research_writer",
                        "catalysts": ["订单增长"],
                        "risks": ["监管风险"],
                        "evidence_snippets": ["订单已确认"],
                        "stance": "偏多",
                        "confidence": 0.8,
                    }
                ]
            })
        }
    }

    context = pipeline.build_research_context(
        sentiment_result=sentiment_result,
        research_context={
            "sections": [
                {
                    "catalysts": ["订单增长", "产能改善"],
                    "risks": ["监管风险"],
                    "evidence_snippets": ["新增产能爬坡"],
                }
            ]
        },
        reflection_context=(
            "- [research] 订单改善带来催化\n"
            "- [research] 监管处罚风险仍需跟踪\n"
        ),
    )

    assert context is not None
    assert context["catalysts"] == ["订单增长", "产能改善", "[research] 订单改善带来催化"]
    assert context["risks"] == ["监管风险", "[research] 监管处罚风险仍需跟踪"]
    assert context["evidence_snippets"] == [
        "新增产能爬坡",
        "订单已确认",
        "[research] 订单改善带来催化",
        "[research] 监管处罚风险仍需跟踪",
    ]
    assert context["stance"] == "偏多"
    assert context["confidence"] == 0.8


def test_run_pipeline_reuses_precomputed_reports_without_llm():
    reports = [_report(role) for role in ("technical", "quant", "sentiment", "news")]

    decision = pipeline.run_pipeline(pipeline.PipelineInputs(
        technical_result={"score": 20.0},
        qlib_result={"score": 20.0, "model": "unit"},
        sentiment_result={"sentiment": 0.2, "key_events": ["event"]},
        close=10.0,
        atr=1.0,
        limit_status={
            "status": "limit_down",
            "limit_down": True,
            "stop_loss_executable": False,
        },
        _precomputed_reports=reports,
    ))
    signal = decision.to_signal_dict()

    assert signal["limit_status"] == "limit_down"
    assert signal["stop_loss_executable"] is False
    assert signal["llm_arbitration"]["used_llm"] is False
    assert signal["llm_arbitration"]["fallback_reason"] == "no_divergence"
    assert signal["decision_trace"][0]["step_name"] == "analysts"
    assert signal["decision_trace"][0]["report_count"] == 4
    assert [step["step_name"] for step in signal["decision_trace"]] == [
        "analysts",
        "director",
        "researcher",
        "trader",
        "risk_manager",
    ]
