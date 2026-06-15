"""M9.横向 反偏差缓冲：bias_override 记忆注入到 piotroski_analyst 输出。"""
from __future__ import annotations

from unittest.mock import patch


def _mock_piotroski_raw(score: int) -> dict:
    """Minimal `compute_piotroski_factors` payload that drives a given F-score."""
    return {
        "score": score,
        "factors": {
            "roa_positive": True,
            "cfo_positive": True,
            "roa_improving": False,
        },
        "raw": {"roa_cur": 0.05},
        "report_period": "2024-Q3",
        "comparison_period": "2023-Q3",
        "available": True,
    }


def test_seed_default_overrides_is_idempotent(test_db):
    from backend.memory.ai_memory import list_active
    from backend.memory.bias_override import seed_default_overrides

    seed_default_overrides(test_db)
    seed_default_overrides(test_db)

    rows = list_active(test_db, scope="bias_override", category="bias_override")
    assert len(rows) == 1
    assert rows[0]["key"] == "piotroski:规避"


def test_piotroski_injects_caveat_on_weak_vote(test_db):
    from backend.agents.long_term import piotroski_analyst
    from backend.memory.bias_override import PIOTROSKI_WEAK_DEFAULT, seed_default_overrides

    seed_default_overrides(test_db)

    with patch(
        "backend.agents.long_term.piotroski_analyst.compute_piotroski_factors",
        return_value=_mock_piotroski_raw(score=3),
    ):
        report = piotroski_analyst.analyze("000001", test_db)

    assert report.label_vote == "规避"  # 没被覆盖
    assert report.key_findings[0].startswith("⚠️ 偏差提示")
    assert PIOTROSKI_WEAK_DEFAULT in report.key_findings[0]
    assert report.raw.get("bias_caveat") == PIOTROSKI_WEAK_DEFAULT


def test_piotroski_no_caveat_when_no_seed(test_db):
    from backend.agents.long_term import piotroski_analyst

    with patch(
        "backend.agents.long_term.piotroski_analyst.compute_piotroski_factors",
        return_value=_mock_piotroski_raw(score=3),
    ):
        report = piotroski_analyst.analyze("000001", test_db)

    assert report.label_vote == "规避"
    assert not any("偏差提示" in f for f in report.key_findings)
    assert "bias_caveat" not in report.raw


def test_piotroski_no_caveat_on_strong_vote_even_with_weak_seed(test_db):
    """种子只针对 规避；强标签不应注入。"""
    from backend.agents.long_term import piotroski_analyst
    from backend.memory.bias_override import seed_default_overrides

    seed_default_overrides(test_db)

    with patch(
        "backend.agents.long_term.piotroski_analyst.compute_piotroski_factors",
        return_value=_mock_piotroski_raw(score=8),
    ):
        report = piotroski_analyst.analyze("000001", test_db)

    assert report.label_vote == "值得持有"
    assert not any("偏差提示" in f for f in report.key_findings)


def test_caveat_survives_team_merge(test_db, monkeypatch):
    """注入的 caveat 必须能流到 LongTermLabel.key_findings 里，否则决策链看不到。"""
    from backend.agents.long_term.team import LongTermTeam
    from backend.config import settings
    from backend.memory.bias_override import seed_default_overrides

    seed_default_overrides(test_db)

    # 只跑 piotroski 一路，让 team 退化为单分析师测试，避免依赖其他数据
    monkeypatch.setattr(settings, "long_term_track_enabled", False)
    monkeypatch.setattr(settings, "long_term_jingqi_enabled", False)
    monkeypatch.setattr(settings, "long_term_qfii_flow_enabled", False)
    monkeypatch.setattr(settings, "long_term_piotroski_enabled", True)

    with patch(
        "backend.agents.long_term.piotroski_analyst.compute_piotroski_factors",
        return_value=_mock_piotroski_raw(score=3),
    ):
        label = LongTermTeam().run("000001", "测试电力", test_db)

    assert label.label == "规避"  # 一票否决保留
    assert any("偏差提示" in f for f in label.key_findings), \
        f"caveat lost in team merge: {label.key_findings}"


def test_lookup_caveat_returns_none_when_missing(test_db):
    from backend.memory.bias_override import lookup_caveat

    assert lookup_caveat(test_db, "piotroski", "规避") is None
    assert lookup_caveat(test_db, "unknown_analyst", "规避") is None


def test_set_caveat_persists_and_recall_works(test_db):
    from backend.memory.bias_override import lookup_caveat, set_caveat

    persisted = set_caveat(test_db, "piotroski", "规避", "自定义提示")
    assert persisted is True
    assert lookup_caveat(test_db, "piotroski", "规避") == "自定义提示"
