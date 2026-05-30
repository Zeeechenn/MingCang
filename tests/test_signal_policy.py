from datetime import date
from types import SimpleNamespace

import pandas as pd


def test_signal_policy_separates_watch_from_entry():
    from backend.decision.signal_policy import (
        is_entry_signal,
        is_watch_signal,
        should_send_signal_alert,
    )

    assert is_watch_signal("可关注")
    assert not is_entry_signal("可关注")

    assert is_entry_signal("可小仓试错")
    assert is_entry_signal("买入")
    assert should_send_signal_alert("可关注")
    assert should_send_signal_alert("可小仓试错")


def test_test1_uses_legacy_qlib_weights_and_test2_uses_new_weights():
    from backend.config import active_signal_weights

    test1_weights = active_signal_weights(date(2026, 5, 16))
    assert test1_weights.quant == 0.45
    assert test1_weights.technical == 0.40
    assert test1_weights.sentiment == 0.15
    assert test1_weights.entry_threshold == 20.0
    assert test1_weights.profile == "test1_legacy_qlib"
    assert test1_weights.use_multi_agent is False

    test2_weights = active_signal_weights(date(2026, 5, 21))
    assert test2_weights.quant == 0.0
    assert test2_weights.technical == 0.6
    assert test2_weights.sentiment == 0.4
    assert test2_weights.entry_threshold == 25.0
    assert test2_weights.profile == "new_framework"
    assert test2_weights.use_multi_agent is False


def test_scheduler_uses_simple_aggregate_for_daily_profiles(monkeypatch):
    from backend.config import settings
    from backend.scheduler import _use_multi_agent_decision

    monkeypatch.setattr(settings, "paper_trading_profile", "test1_legacy_qlib")
    assert _use_multi_agent_decision() is False

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "multi_agent_enabled", False)
    assert _use_multi_agent_decision() is False


def test_multi_agent_can_still_be_enabled_explicitly_for_research(monkeypatch):
    from backend.config import settings
    from backend.scheduler import _use_multi_agent_decision

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "multi_agent_enabled", True)

    assert _use_multi_agent_decision() is True


def test_postmarket_analysis_can_clip_to_as_of(monkeypatch):
    from backend import scheduler
    from backend.config import settings

    dates = pd.date_range("2026-03-01", periods=70, freq="D").strftime("%Y-%m-%d")
    df = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1000},
        index=dates,
    )

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "multi_agent_enabled", False)
    monkeypatch.setattr("backend.data.market.load_price_df", lambda *args, **kwargs: df)
    monkeypatch.setattr("backend.analysis.qlib_engine.qlib_score", lambda *args, **kwargs: {"score": 0.0})
    monkeypatch.setattr(scheduler, "_postmarket_news_sentiment", lambda *args, **kwargs: {"sentiment": 0.0})
    monkeypatch.setattr(
        "backend.memory.stock_memory.build_memory_context",
        lambda *args, **kwargs: {"text": ""},
    )
    monkeypatch.setattr(
        "backend.analysis.technical.technical_score",
        lambda clipped, **kwargs: {
            "score": 0.0,
            "latest": {"close": 1.5, "atr14": 0.1},
            "latest_date": clipped.index[-1],
        },
    )
    monkeypatch.setattr(
        "backend.decision.aggregator.aggregate",
        lambda **kwargs: {
            "composite_score": 0.0,
            "recommendation": "观望",
            "confidence": "低",
            "stop_loss": 1.0,
            "take_profit": 2.0,
            "breakdown": {"quant": 0.0, "technical": 0.0, "sentiment": 0.0},
        },
    )

    stock = SimpleNamespace(symbol="000001", name="测试股", market="CN")
    analysis = scheduler._analyze_postmarket_stock(
        stock,
        db=object(),
        context={"long_term_labels": {}},
        as_of_date="2026-05-05",
    )

    assert analysis["date"] == "2026-05-05"


def test_postmarket_read_only_context_disables_memory_usage_recording(monkeypatch):
    from backend import scheduler
    from backend.config import settings

    dates = pd.date_range("2026-03-01", periods=70, freq="D").strftime("%Y-%m-%d")
    df = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1000},
        index=dates,
    )
    seen = {}

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    monkeypatch.setattr(settings, "multi_agent_enabled", False)
    monkeypatch.setattr("backend.data.market.load_price_df", lambda *args, **kwargs: df)
    monkeypatch.setattr("backend.analysis.qlib_engine.qlib_score", lambda *args, **kwargs: {"score": 0.0})
    monkeypatch.setattr(scheduler, "_postmarket_news_sentiment", lambda *args, **kwargs: {"sentiment": 0.0})

    def fake_build_memory_context(*args, **kwargs):
        seen["record_usage"] = kwargs.get("record_usage")
        return {"text": "", "used_stock_memory_ids": [], "ai_memory_keys": []}

    monkeypatch.setattr("backend.memory.stock_memory.build_memory_context", fake_build_memory_context)
    monkeypatch.setattr(
        "backend.analysis.technical.technical_score",
        lambda clipped, **kwargs: {
            "score": 0.0,
            "latest": {"close": 1.5, "atr14": 0.1},
            "latest_date": clipped.index[-1],
        },
    )
    monkeypatch.setattr(
        "backend.decision.aggregator.aggregate",
        lambda **kwargs: {
            "composite_score": 0.0,
            "recommendation": "观望",
            "confidence": "低",
            "stop_loss": 1.0,
            "take_profit": 2.0,
            "breakdown": {"quant": 0.0, "technical": 0.0, "sentiment": 0.0},
        },
    )

    stock = SimpleNamespace(symbol="000001", name="测试股", market="CN")
    scheduler._analyze_postmarket_stock(
        stock,
        db=object(),
        context={"long_term_labels": {}, "read_only": True},
    )

    assert seen["record_usage"] is False


def test_bark_signal_alert_names_the_concrete_action(monkeypatch):
    from backend.notification import bark

    sent = []

    def fake_send(title, body, group="StockSage", sound="bark"):
        sent.append({"title": title, "body": body, "group": group, "sound": sound})
        return True

    monkeypatch.setattr(bark, "send", fake_send)

    assert bark.send_signal_alert("300308", "中际旭创", "可关注", 18, 990, 1120)
    assert "观察" in sent[-1]["title"]
    assert "不新开仓" in sent[-1]["body"]

    assert bark.send_signal_alert("300394", "天孚通信", "可小仓试错", 32, 358, 498, position_pct=0.05)
    assert "小仓试错" in sent[-1]["title"]
    assert "买入" in sent[-1]["body"]
    assert "5.0%" in sent[-1]["body"]


def test_position_sizing_uses_active_entry_threshold(monkeypatch):
    from backend.config import settings
    from backend.portfolio.single_position import suggest_position_pct

    monkeypatch.setattr(settings, "paper_trading_profile", "test1_legacy_qlib")
    assert suggest_position_pct(21, "低") == settings.new_signal_trial_pct

    monkeypatch.setattr(settings, "paper_trading_profile", "new_framework")
    assert suggest_position_pct(21, "低") == 0.0


def test_trailing_stop_does_not_force_timeout_by_default(monkeypatch):
    from backend.config import settings
    from backend.portfolio.trailing_stop import TrailingStopTracker, update_trailing_stop

    monkeypatch.setattr(settings, "time_exit_enabled", False)
    monkeypatch.setattr(settings, "max_hold_days", 1)

    pos = TrailingStopTracker.open("300308", "2026-05-18", 100.0, 5.0)
    updated = update_trailing_stop(
        pos,
        current_high=101.0,
        current_low=96.0,
        current_close=100.5,
        current_date="2026-05-19",
    )

    assert updated.status == "open"


def test_trailing_stop_is_enabled_by_default():
    from backend.config import settings

    assert settings.trailing_stop_enabled is True
    assert settings.trailing_atr_mult == 2.5


def test_take_profit_is_reference_by_default(monkeypatch):
    from backend.config import settings
    from backend.portfolio.trailing_stop import TrailingStopTracker, update_trailing_stop

    monkeypatch.setattr(settings, "take_profit_exit_enabled", False)
    monkeypatch.setattr(settings, "trailing_stop_enabled", True)

    pos = TrailingStopTracker.open("603986", "2026-05-19", 100.0, 5.0)
    updated = update_trailing_stop(
        pos,
        current_high=125.0,
        current_low=101.0,
        current_close=124.0,
        current_date="2026-05-20",
    )

    assert updated.status == "open"
    assert updated.current_stop == 111.5


def test_trailing_stop_timeout_can_be_enabled_for_experiments(monkeypatch):
    from backend.config import settings
    from backend.portfolio.trailing_stop import TrailingStopTracker, update_trailing_stop

    monkeypatch.setattr(settings, "time_exit_enabled", True)
    monkeypatch.setattr(settings, "max_hold_days", 1)

    pos = TrailingStopTracker.open("300308", "2026-05-18", 100.0, 5.0)
    updated = update_trailing_stop(
        pos,
        current_high=101.0,
        current_low=96.0,
        current_close=100.5,
        current_date="2026-05-19",
    )

    assert updated.status == "timeout"
    assert updated.exit_reason == "超时"
