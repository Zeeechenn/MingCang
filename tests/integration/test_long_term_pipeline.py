"""
端到端集成测试：模拟一次完整盘后流水线，验证长期标签真实约束短期信号。

不依赖网络/真实 LLM：mock 三个长期分析师返回固定标签。
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from backend.agents.long_term.base import LongTermLabel, LongTermReport
from backend.agents.long_term.storage import bulk_get_labels, save_label
from backend.agents.long_term.team import LongTermTeam
from backend.data.database import Price, Stock

# ── 数据 helper ───────────────────────────────────────────────────────

def _date_after(days: int) -> str:
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")


def _date_before(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")


def _seed_prices(db, symbol: str, n: int = 100, start_price: float = 100.0):
    """种 n 条日线数据（用于 technical_score 计算）"""
    import random
    random.seed(42)
    price = start_price
    for i in range(n):
        date = f"2026-{(i//30)+1:02d}-{(i%30)+1:02d}"
        change = random.uniform(-0.02, 0.025)
        price = price * (1 + change)
        db.add(Price(
            symbol=symbol, date=date,
            open=price * 0.995, high=price * 1.01,
            low=price * 0.99, close=price,
            volume=1_000_000 + random.randint(-100_000, 100_000),
        ))
    db.commit()


def _seed_stocks_with_data(db):
    """3 只电子股 + 价格数据 + 财务数据"""
    stocks = [
        Stock(symbol="300308", name="中际旭创", market="CN", industry="电子", active=True),
        Stock(symbol="603986", name="兆易创新", market="CN", industry="电子", active=True),
        Stock(symbol="600036", name="招商银行", market="CN", industry="金融", active=True),
    ]
    for s in stocks:
        db.add(s)
    db.commit()

    for s in stocks:
        _seed_prices(db, s.symbol, n=100, start_price=100.0)
    return stocks


# ── 集成测试 ──────────────────────────────────────────────────────────

@patch("backend.agents.long_term.team.a_teacher_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_weekly_job_generates_labels_for_all_stocks(
    mock_jingqi, mock_pio, mock_at, test_db,
):
    """模拟周末 job：3 只股 → 3 个 label 落库"""
    stocks = _seed_stocks_with_data(test_db)

    # mock 不同股票返回不同结论
    def mock_at_fn(symbol, name, db):
        if symbol == "300308":
            return LongTermReport(role="track", score=70, confidence=0.9,
                                  label_vote="值得持有", key_findings=["光通信龙头"], raw={})
        elif symbol == "603986":
            return LongTermReport(role="track", score=30, confidence=0.6,
                                  label_vote="估值偏高", key_findings=["涨幅已大"], raw={})
        else:
            return LongTermReport(role="track", score=-50, confidence=0.8,
                                  label_vote="规避", key_findings=["金融板块β负"], raw={})
    mock_at.side_effect = mock_at_fn
    mock_pio.return_value = LongTermReport(role="quality", score=60, confidence=0.7,
                                            label_vote="值得持有", key_findings=["F=8"], raw={})
    mock_jingqi.return_value = LongTermReport(role="boom", score=50, confidence=0.6,
                                               label_vote="值得持有", key_findings=["Δ强"], raw={})

    # 跑团 + 落库
    team = LongTermTeam()
    for s in stocks:
        label = team.run(s.symbol, s.name, test_db)
        save_label(label, test_db)

    # 验证：所有股都有 active label
    labels = bulk_get_labels([s.symbol for s in stocks], test_db)
    assert len(labels) == 3
    assert labels["300308"].label == "值得持有"   # 高分 + 都不投规避
    assert labels["603986"].label == "估值偏高"   # 中等分
    assert labels["600036"].label == "规避"       # a_teacher 投规避 → 一票否决


@patch("backend.agents.long_term.team.a_teacher_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_postmarket_pipeline_respects_avoid_label(
    mock_jingqi, mock_pio, mock_at, test_db, monkeypatch,
):
    """端到端：'规避' label 应让短期信号被风险经理否决"""
    from backend.decision.aggregator import aggregate_v2

    monkeypatch.setattr("backend.config.settings.long_term_constraints_enabled", True)
    _seed_stocks_with_data(test_db)

    # 给 600036 标"规避"
    save_label(LongTermLabel(
        symbol="600036", date=_date_before(1),
        label="规避", score=-60,
        votes={"track": "规避"}, key_findings=["金融板块β负"],
        expires_at=_date_after(10),
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    ), test_db)

    # 模拟短期信号产出（technical_score 高 + 量化中等，应该买入）
    technical_result = {
        "score": 50.0, "raw_score": 50.0, "adx_factor": 1.0,
        "components": {"trend": 1.0, "rsi": 0.5, "macd": 1.0, "volume": 0.0},
        "limit": {"status": "normal", "limit_up": False, "limit_down": False,
                  "stop_loss_executable": True, "change_pct": 2.0},
        "latest": {"close": 50.0, "rsi14": 60.0, "atr14": 1.5, "adx14": 25.0, "ma20": 48.0, "ma60": 45.0},
    }
    quant_result = {"score": 30.0, "model": "lgbm_alpha_v1"}
    sentiment_result = {"sentiment": 0.3, "summary": "中性", "impact": "short", "key_events": ["利好"]}

    label = bulk_get_labels(["600036"], test_db).get("600036")
    assert label is not None and label.label == "规避"

    result = aggregate_v2(
        quant_result=quant_result,
        technical_result=technical_result,
        sentiment_result=sentiment_result,
        close=50.0, atr=1.5,
        regime=None,
        long_term_label=label,
    )

    # 风险经理应该否决
    assert result.get("veto_reason") is not None, f"应有 veto_reason，实际 result={result}"
    assert "规避" in result["veto_reason"]
    assert result.get("position_pct", 0) == 0.0
    assert result["recommendation"] == "观望"


@patch("backend.agents.long_term.team.a_teacher_analyst.analyze")
@patch("backend.agents.long_term.team.piotroski_analyst.analyze")
@patch("backend.agents.long_term.team.jingqi_analyst.analyze")
def test_postmarket_pipeline_respects_overvalued_label(
    mock_jingqi, mock_pio, mock_at, test_db, monkeypatch,
):
    """'估值偏高' label → 仓位 × 0.5"""
    from backend.decision.aggregator import aggregate_v2

    monkeypatch.setattr("backend.config.settings.long_term_constraints_enabled", True)
    _seed_stocks_with_data(test_db)
    save_label(LongTermLabel(
        symbol="603986", date=_date_before(1),
        label="估值偏高", score=35,
        votes={"track": "估值偏高"}, key_findings=["涨幅80%"],
        expires_at=_date_after(10),
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    ), test_db)

    technical_result = {
        "score": 50.0, "raw_score": 50.0, "adx_factor": 1.0,
        "components": {"trend": 1.0, "rsi": 0.5, "macd": 1.0, "volume": 0.0},
        "limit": {"status": "normal", "limit_up": False, "limit_down": False,
                  "stop_loss_executable": True, "change_pct": 2.0},
        "latest": {"close": 50.0, "rsi14": 60.0, "atr14": 1.5, "adx14": 25.0, "ma20": 48.0, "ma60": 45.0},
    }
    quant_result = {"score": 30.0, "model": "lgbm_alpha_v1"}
    sentiment_result = {"sentiment": 0.5, "summary": "正面", "impact": "short", "key_events": ["利好"]}

    label = bulk_get_labels(["603986"], test_db).get("603986")

    # 不带长期标签的对照
    result_no_lt = aggregate_v2(
        quant_result=quant_result, technical_result=technical_result,
        sentiment_result=sentiment_result, close=50.0, atr=1.5,
        regime=None, long_term_label=None,
    )
    pos_no_lt = result_no_lt.get("position_pct", 0)

    # 带长期标签
    result_lt = aggregate_v2(
        quant_result=quant_result, technical_result=technical_result,
        sentiment_result=sentiment_result, close=50.0, atr=1.5,
        regime=None, long_term_label=label,
    )
    pos_lt = result_lt.get("position_pct", 0)

    # 仓位被砍半
    assert pos_lt < pos_no_lt
    assert abs(pos_lt - pos_no_lt * 0.5) < 0.001, \
        f"position_pct 应该 × 0.5，实际 {pos_lt:.4f} vs 原 {pos_no_lt:.4f}"
    # 备注里应有"估值偏高"
    notes = result_lt.get("risk_notes", [])
    assert any("估值偏高" in n for n in notes)


def test_mirror_json_written(test_db, tmp_path, monkeypatch):
    """save_label 应写镜像 JSON 文件"""
    from backend.agents.long_term import storage
    monkeypatch.setattr(storage, "MIRROR_PATH", tmp_path / "labels.json")

    label = LongTermLabel(
        symbol="300308", date=_date_before(1),
        label="值得持有", score=65,
        votes={"track": "值得持有"}, key_findings=["test"],
        expires_at=_date_after(10),
        quality="trusted",
        constraint_eligible=True,
        quality_notes=["test trusted label"],
    )
    storage.save_label(label, test_db)

    mirror = tmp_path / "labels.json"
    assert mirror.exists()
    import json
    data = json.loads(mirror.read_text())
    assert "300308" in data
    assert data["300308"]["label"] == "值得持有"


def test_mirror_json_skipped_by_default(test_db, tmp_path, monkeypatch):
    """默认不应写入用户 Home 目录镜像文件。"""
    from backend.agents.long_term import storage

    home_mirror = tmp_path / "home" / ".mingcang" / "long_term_labels.json"
    monkeypatch.setattr(storage, "MIRROR_PATH", None)
    monkeypatch.setattr(storage.settings, "long_term_label_mirror_path", "")

    label = LongTermLabel(
        symbol="300308", date=_date_before(1),
        label="值得持有", score=65,
        votes={"track": "值得持有"}, key_findings=["test"],
        expires_at=_date_after(10),
    )
    storage.save_label(label, test_db)

    assert not home_mirror.exists()
