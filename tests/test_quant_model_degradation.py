"""quant_score 静默降级回归测试（2026-07-03 事故）。

事故链：06-06 rebrand 把 MODEL_DIR 从 ~/.stock-sage 切到 ~/.mingcang，模型文件
未迁移 → _load_model() 对"文件不存在"静默返回 None → qlib_score 无警告退回
placeholder_v0 动量占位 → 信号侧无任何降级痕迹，近一个月无人察觉。

锁定两个防线：
1. 模型文件缺失必须发出一次性显式 WARNING（不刷屏，但必须可见）。
2. quant 模型溯源（lgbm_alpha_v1 / placeholder_v0）必须随信号落进
   decision_runs.input_snapshot_json，使降级在数据层可审计。
"""
import logging

import numpy as np
import pandas as pd
import pytest

from backend.analysis import qlib_engine


def _ohlcv(n: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 10 + rng.normal(0, 0.1, n).cumsum()
    return pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2026-05-01", periods=n).strftime("%Y-%m-%d"))


@pytest.fixture
def missing_model(monkeypatch, tmp_path):
    """把模型路径指向不存在的文件，并重置模块级缓存。"""
    monkeypatch.setattr(qlib_engine, "MODEL_PATH", tmp_path / "lgbm_alpha.pkl")
    monkeypatch.setattr(qlib_engine, "_MODEL_CACHE", {
        "path_mtime": None, "model": None,
        "feature_cols": None, "disabled_reason": None,
    })
    return tmp_path


def test_missing_model_falls_back_with_explicit_warning(missing_model, caplog):
    df = _ohlcv()
    with caplog.at_level(logging.WARNING, logger="backend.analysis.qlib_engine"):
        first = qlib_engine.qlib_score(df)
        second = qlib_engine.qlib_score(df)

    assert first["model"] == "placeholder_v0"
    assert second["model"] == "placeholder_v0"
    missing_warnings = [
        r for r in caplog.records if "placeholder_v0" in r.getMessage()
    ]
    # 必须告警，且同一缺失状态只告警一次（不随每次打分刷屏）
    assert len(missing_warnings) == 1
    assert qlib_engine._MODEL_CACHE["disabled_reason"] == "model_file_missing"


def test_save_signal_persists_quant_model_provenance(test_db):
    from backend.data.database import DecisionRun
    from backend.decision.aggregator import save_signal

    result = {
        "breakdown": {"quant": 12.3, "technical": 30.0, "sentiment": 10.0},
        "composite_score": 25.0,
        "recommendation": "观望",
        "confidence": "中",
        "stop_loss": 9.5,
        "take_profit": 11.5,
        "quant_model": "placeholder_v0",
    }
    save_signal("600519", "2026-07-03", result, test_db)

    run = test_db.query(DecisionRun).filter(
        DecisionRun.symbol == "600519", DecisionRun.as_of == "2026-07-03"
    ).first()
    assert run is not None
    import json
    snapshot = json.loads(run.input_snapshot_json)
    assert snapshot.get("quant_model") == "placeholder_v0"
