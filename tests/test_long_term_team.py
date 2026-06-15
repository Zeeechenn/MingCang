"""
单元测试：长期分析师团聚合规则 + storage + 风险经理集成

mock 三个分析师，验证 label 映射规则的所有分支。
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.agents.long_term.base import LongTermLabel, LongTermReport, VoteLabel
from backend.agents.long_term.storage import bulk_get_labels, get_active_label, save_label
from backend.agents.long_term.team import LongTermTeam, _aggregate_score, _resolve_label

# ── 工具 ──────────────────────────────────────────────────────────────

def _date_after(days: int) -> str:
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")


def _date_before(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")


def _mk_report(role: str, score: float, vote: VoteLabel, conf: float = 0.8) -> LongTermReport:
    return LongTermReport(
        role=role, score=score, confidence=conf, label_vote=vote,
        key_findings=[f"{role} finding 1"], raw={},
    )


# ── _aggregate_score ──────────────────────────────────────────────────

def test_aggregate_score_weighted_average():
    """三路加权平均（默认权重 0.3/0.3/0.4）"""
    reports = {
        "track": _mk_report("track", 60, "值得持有"),
        "quality": _mk_report("quality", 40, "值得持有"),
        "boom": _mk_report("boom", 50, "值得持有"),
    }
    score = _aggregate_score(reports)
    # 0.3*60 + 0.3*40 + 0.4*50 = 50
    assert score == 50.0


def test_aggregate_score_skips_low_confidence():
    """confidence < 0.01 的报告被跳过"""
    reports = {
        "track": _mk_report("track", 60, "值得持有", conf=0.0),
        "quality": _mk_report("quality", 40, "值得持有", conf=0.8),
        "boom": _mk_report("boom", 50, "值得持有", conf=0.8),
    }
    score = _aggregate_score(reports)
    # 只算 quality+boom，0.3*40+0.4*50 / 0.7 = 45.71
    assert abs(score - 45.71) < 0.1


def test_aggregate_score_empty():
    """没有有效报告 → 0"""
    assert _aggregate_score({}) == 0.0


# ── _resolve_label 全分支 ─────────────────────────────────────────────

def test_resolve_label_avoid_veto():
    """一票否决：任一投'规避' → 规避"""
    label = _resolve_label(score=70, votes={"track": "规避", "quality": "值得持有", "boom": "值得持有"})
    assert label == "规避"


def test_resolve_label_track_layer5_avoid():
    """track_analyst 第五层'规避'即使无 vote 也强制规避"""
    label = _resolve_label(score=70, votes={"track": "值得持有"}, track_layer5="规避")
    assert label == "规避"


def test_resolve_label_hold():
    """score ≥ 50 → 值得持有"""
    label = _resolve_label(score=60, votes={"track": "值得持有", "quality": "值得持有", "boom": "值得持有"})
    assert label == "值得持有"


def test_resolve_label_hold_downgraded_by_layer5():
    """score ≥ 50 但 track_analyst 第五层'等回调' → 估值偏高"""
    label = _resolve_label(score=70, votes={"track": "值得持有"}, track_layer5="等回调")
    assert label == "估值偏高"


def test_resolve_label_overvalued():
    """30 ≤ score < 50 → 估值偏高"""
    label = _resolve_label(score=35, votes={"track": "观望", "quality": "值得持有"})
    assert label == "估值偏高"


def test_resolve_label_watch():
    """-20 ≤ score < 30 → 观望"""
    assert _resolve_label(score=0, votes={"track": "观望"}) == "观望"
    assert _resolve_label(score=25, votes={"track": "观望"}) == "观望"
    assert _resolve_label(score=-10, votes={"track": "观望"}) == "观望"


def test_resolve_label_avoid_low_score():
    """score < -20 → 规避"""
    label = _resolve_label(score=-30, votes={"track": "估值偏高"})
    assert label == "规避"


# ── LongTermTeam.run 集成 ─────────────────────────────────────────────

@patch("backend.agents.long_term.team.track_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_team_run_full_pipeline(mock_jingqi, mock_pio, mock_at, test_db):
    """三个分析师 mock → 团聚合 → 输出 LongTermLabel"""
    mock_at.return_value = _mk_report("track", 60, "值得持有")
    mock_pio.return_value = _mk_report("quality", 50, "值得持有")
    mock_jingqi.return_value = _mk_report("boom", 70, "值得持有")

    team = LongTermTeam()
    label = team.run("300308", "中际旭创", test_db)

    assert isinstance(label, LongTermLabel)
    assert label.symbol == "300308"
    # 0.3*60 + 0.3*50 + 0.4*70 = 18 + 15 + 28 = 61 → 值得持有
    assert label.score == 61.0
    assert label.label == "值得持有"
    assert label.quality == "trusted"
    assert label.constraint_eligible is True
    assert "track" in label.votes
    assert "quality" in label.votes
    assert "boom" in label.votes
    assert len(label.key_findings) > 0
    assert label.expires_at > label.date


@patch("backend.agents.long_term.team.track_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_team_run_avoid_vote_wins(mock_jingqi, mock_pio, mock_at, test_db):
    """一个'规避'票 → 整体'规避'（即使均分 70）"""
    mock_at.return_value = _mk_report("track", 80, "值得持有")
    mock_pio.return_value = _mk_report("quality", 80, "值得持有")
    mock_jingqi.return_value = _mk_report("boom", 80, "规避")  # 一票否决

    team = LongTermTeam()
    label = team.run("300308", "中际旭创", test_db)
    assert label.label == "规避"


@patch("backend.agents.long_term.team.track_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_team_run_analyst_exception_doesnt_crash(mock_jingqi, mock_pio, mock_at, test_db):
    """单个分析师抛异常 → 团仍能输出 label（基于剩余分析师）"""
    mock_at.side_effect = RuntimeError("LLM 调用失败")
    mock_pio.return_value = _mk_report("quality", 50, "值得持有")
    mock_jingqi.return_value = _mk_report("boom", 60, "值得持有")

    team = LongTermTeam()
    label = team.run("300308", "中际旭创", test_db)
    # 仅基于 quality+boom 算分: (0.3*50 + 0.4*60) / 0.7 = 50.0
    assert label is not None
    assert label.label in ("值得持有", "估值偏高")
    assert label.quality == "failed"
    assert label.constraint_eligible is False


# ── storage ──────────────────────────────────────────────────────────

def test_save_and_get_active_label(test_db):
    label = LongTermLabel(
        symbol="600519", date=_date_before(1),
        label="值得持有", score=65.0,
        votes={"track": "值得持有"},
        key_findings=["test finding"],
        expires_at=_date_after(10),
    )
    save_label(label, test_db)

    fetched = get_active_label("600519", test_db)
    assert fetched is not None
    assert fetched.label == "值得持有"
    assert fetched.score == 65.0


def test_get_active_label_returns_none_when_expired(test_db):
    label = LongTermLabel(
        symbol="600519", date=_date_before(30),
        label="值得持有", score=65.0,
        votes={}, key_findings=[],
        expires_at=_date_before(1),
    )
    save_label(label, test_db)

    fetched = get_active_label("600519", test_db)
    assert fetched is None


def test_save_label_is_idempotent(test_db):
    """同 (symbol, date) 重复 save 应更新而非插入"""
    label1 = LongTermLabel(
        symbol="600519", date=_date_before(1),
        label="观望", score=10.0, votes={}, key_findings=[],
        expires_at=_date_after(10),
    )
    label2 = LongTermLabel(
        symbol="600519", date=_date_before(1),
        label="值得持有", score=60.0, votes={}, key_findings=[],
        expires_at=_date_after(10),
    )
    save_label(label1, test_db)
    save_label(label2, test_db)

    from backend.data.database import LongTermLabel as ORM
    count = test_db.query(ORM).filter(ORM.symbol == "600519").count()
    assert count == 1   # 只有一条
    fetched = get_active_label("600519", test_db)
    assert fetched.label == "值得持有"   # 更新为最新


def test_bulk_get_labels(test_db):
    for sym, lbl in [("A", "值得持有"), ("B", "规避"), ("C", "观望")]:
        save_label(LongTermLabel(
            symbol=sym, date=_date_before(1),
            label=lbl, score=0, votes={}, key_findings=[],
            expires_at=_date_after(10),
        ), test_db)
    result = bulk_get_labels(["A", "B", "C", "Z"], test_db)
    assert len(result) == 3
    assert result["A"].label == "值得持有"
    assert result["B"].label == "规避"
    assert "Z" not in result   # 不存在的不返回
