"""Kill Switch 单元测试（Tier 4）

状态文件用 tmp_path 隔离，避免污染用户家目录。
"""
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """每个测试用独立状态文件 + 默认不推 Bark"""
    from backend.ops import kill_switch
    monkeypatch.setattr(kill_switch, "STATE_PATH", tmp_path / "kill_switch.json")
    # 防止真实推 Bark
    from backend.notification import bark
    monkeypatch.setattr(bark, "send", lambda *a, **kw: False)
    yield


def test_no_state_means_inactive():
    from backend.ops import kill_switch
    assert kill_switch.is_active() is False
    assert kill_switch.current_state() is None


def test_trigger_then_active():
    from backend.ops import kill_switch
    state = kill_switch.trigger("测试原因", metadata={"x": 1}, push=False)
    assert state.active is True
    assert state.reason == "测试原因"
    assert kill_switch.is_active() is True
    cur = kill_switch.current_state()
    assert cur["reason"] == "测试原因"
    assert cur["metadata"] == {"x": 1}


def test_reset_clears_state():
    from backend.ops import kill_switch
    kill_switch.trigger("r", push=False)
    assert kill_switch.is_active()
    kill_switch.reset()
    assert kill_switch.is_active() is False
    assert kill_switch.current_state() is None


def test_corrupt_state_is_treated_as_active(tmp_path):
    from backend.ops import kill_switch

    kill_switch.STATE_PATH.write_text("{not json", encoding="utf-8")

    assert kill_switch.is_active() is True
    state = kill_switch.current_state()
    assert state["active"] is True
    assert "读取失败" in state["reason"]


def test_detect_consecutive_losses_counts_trailing_only():
    from backend.ops import kill_switch
    # 最后 3 笔亏损
    assert kill_switch.detect_consecutive_losses([0.01, -0.01, -0.02, -0.005]) == 3
    # 中间亏损不算（只看尾部）
    assert kill_switch.detect_consecutive_losses([-0.01, -0.02, 0.01]) == 0
    # 全空
    assert kill_switch.detect_consecutive_losses([]) == 0


def test_check_consecutive_losses_triggers_at_threshold():
    from backend.ops import kill_switch
    res = kill_switch.check_consecutive_losses(
        [-0.01, -0.02, -0.005, -0.01, -0.02], threshold=5
    )
    assert res is not None
    assert "连续 5 笔" in res.reason
    assert kill_switch.is_active()


def test_check_consecutive_losses_below_threshold():
    from backend.ops import kill_switch
    res = kill_switch.check_consecutive_losses(
        [-0.01, -0.02], threshold=5
    )
    assert res is None
    assert not kill_switch.is_active()


def test_check_daily_drawdown():
    from backend.ops import kill_switch
    res = kill_switch.check_daily_drawdown(6.5, threshold_pct=5.0)
    assert res is not None
    assert kill_switch.is_active()


def test_check_data_staleness_too_old():
    from backend.ops import kill_switch
    today = datetime(2026, 5, 15)
    res = kill_switch.check_data_staleness("2026-05-01", today=today, threshold_days=5)
    assert res is not None
    assert "陈旧" in res.reason


def test_check_data_staleness_fresh_passes():
    from backend.ops import kill_switch
    today = datetime(2026, 5, 15)
    res = kill_switch.check_data_staleness("2026-05-14", today=today, threshold_days=5)
    assert res is None


def test_check_data_staleness_none_triggers():
    from backend.ops import kill_switch
    res = kill_switch.check_data_staleness(None)
    assert res is not None


def test_run_all_checks_returns_first_trigger():
    from backend.ops import kill_switch
    datetime(2026, 5, 15)
    res = kill_switch.run_all_checks(
        trade_returns=[-0.01] * kill_switch.DEFAULT_CONSECUTIVE_LOSSES,
        drawdown_pct=10.0,
        latest_price_date="2025-01-01",
    )
    assert res is not None
    # 连亏先触发（顺序）
    assert "连续" in res.reason


def test_run_all_checks_idempotent_when_active():
    """已激活后再调 run_all_checks 不应改写原因"""
    from backend.ops import kill_switch
    kill_switch.trigger("first", push=False)
    res = kill_switch.run_all_checks(trade_returns=[-0.01] * 10)
    assert res.reason == "first"


def test_scheduler_guard_skips_when_active(monkeypatch):
    from backend import scheduler
    from backend.ops import kill_switch

    kill_switch.trigger("manual stop", push=False)

    called = {"premarket": False}

    def fake_inner():
        called["premarket"] = True

    # job_premarket 第一行是 guard，触发后应直接 return
    # 我们靠 guard 函数自身行为测试
    assert scheduler._kill_switch_guard("test") is True


def test_scheduler_guard_passes_when_inactive():
    from backend import scheduler
    assert scheduler._kill_switch_guard("test") is False
