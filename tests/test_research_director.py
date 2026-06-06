"""M4.2 Research Director 测试。

覆盖：
  • 无分析师报告 → quality_ok=False
  • 4 路均正常 → quality_ok=True, 议题为空（分歧不达阈值）
  • 4 路分歧大 → diverged=True, 生成议题（最大/最小角色名）
  • 关键发现缺失 → 进入 weak_roles + quality_notes
  • 低置信度 → quality_notes 提示
  • 过半数 weak → quality_ok=False
  • pipeline 集成：director_assessment 进 to_signal_dict
"""
from __future__ import annotations

from unittest.mock import patch

from backend.agents.analyst import AnalystReport
from backend.agents.director import assess, assessment_to_dict
from backend.agents.pipeline import PipelineInputs, run_pipeline


def _report(role: str, score: float, conf: float, findings: list[str]) -> AnalystReport:
    return AnalystReport(role=role, score=score, confidence=conf, key_findings=findings, raw={})


def test_assess_empty_reports():
    a = assess([])
    assert a.quality_ok is False
    assert a.score_stdev == 0.0
    assert a.diverged is False
    assert "无分析师报告" in a.quality_notes


def test_assess_consistent_no_topic():
    """四路分歧不大 → 不生成 debate_topic"""
    reports = [
        _report("technical", 20, 0.6, ["RSI 中性"]),
        _report("quant", 15, 0.6, ["lgbm 看多"]),
        _report("sentiment", 25, 0.6, ["新闻偏正"]),
        _report("news", 22, 0.6, ["利好事件"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    assert a.quality_ok is True
    assert a.diverged is False
    assert a.debate_topic == ""


def test_assess_diverged_generates_topic():
    """技术 +60 vs 量化 -50 → 生成议题"""
    reports = [
        _report("technical", 60, 0.7, ["突破"]),
        _report("quant", -50, 0.7, ["模型看空"]),
        _report("sentiment", 10, 0.5, ["持平"]),
        _report("news", 5, 0.5, ["无显著事件"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    assert a.diverged is True
    assert "技术" in a.debate_topic
    assert "量化" in a.debate_topic
    assert "+60" in a.debate_topic
    assert "-50" in a.debate_topic


def test_assess_missing_findings_marks_weak():
    """key_findings 缺失 → 进 weak_roles"""
    reports = [
        _report("technical", 20, 0.6, ["RSI 中性"]),
        _report("quant", 0, 0.5, []),       # 缺失
        _report("sentiment", 10, 0.5, ["持平"]),
        _report("news", 5, 0.5, ["无显著事件"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    assert "quant" in a.weak_roles
    assert any("量化" in n for n in a.quality_notes)


def test_assess_low_confidence_marks_weak():
    """置信度低于阈值 → 进 weak_roles"""
    reports = [
        _report("technical", 20, 0.6, ["RSI 中性"]),
        _report("quant", 0, 0.05, ["model=?"]),    # 低置信度
        _report("sentiment", 10, 0.5, ["持平"]),
        _report("news", 5, 0.5, ["事件"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    assert "quant" in a.weak_roles


def test_assess_majority_weak_marks_quality_not_ok():
    """≥半数报告 weak → quality_ok=False"""
    reports = [
        _report("technical", 20, 0.6, []),
        _report("quant", 0, 0.6, []),
        _report("sentiment", 10, 0.6, ["持平"]),
        _report("news", 5, 0.6, ["事件"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    assert a.quality_ok is False
    assert len(a.weak_roles) >= 2


def test_assessment_to_dict_fields():
    reports = [
        _report("technical", 60, 0.7, ["突破"]),
        _report("quant", -50, 0.7, ["模型看空"]),
    ]
    with patch("backend.agents.director.settings") as mock_settings:
        mock_settings.multi_round_debate_min_divergence = 20.0
        mock_settings.director_min_confidence = 0.25
        a = assess(reports)
    d = assessment_to_dict(a)
    assert d["quality_ok"] in (True, False)
    assert "score_stdev" in d
    assert "debate_topic" in d
    assert "weak_roles" in d


def test_pipeline_includes_director_in_signal_dict():
    """pipeline.run_pipeline 应把 director 评估写入 to_signal_dict"""
    technical_result = {
        "score": 60, "raw_score": 60, "adx_factor": 1.0,
        "latest": {"rsi14": 65}, "limit": {},
    }
    qlib_result = {"score": -50, "model": "lgbm"}
    sentiment_result = {"sentiment": 0.1, "impact": "short", "key_events": []}

    decision = run_pipeline(PipelineInputs(
        technical_result=technical_result,
        qlib_result=qlib_result,
        sentiment_result=sentiment_result,
        close=100.0, atr=2.0,
    ))

    signal_dict = decision.to_signal_dict()
    assert "director" in signal_dict
    director = signal_dict["director"]
    assert "quality_ok" in director
    assert "diverged" in director
    assert "debate_topic" in director
    # 技术 60 vs quant -50 应被判定为 diverged
    assert director["diverged"] is True
