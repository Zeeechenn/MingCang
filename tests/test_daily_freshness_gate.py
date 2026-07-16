"""新鲜度门测试：fetch_daily_with_fallback(expected_latest=...) 三条路径。

背景：tickflow 429 触发 30s 冷却后，后续股票静默落到备用源的滞后数据上
（07-06/07-09/07-16 三次「失败 0 但半池旧 bar」）。新鲜度门要求：
- 陈旧成功不立即采用、继续尝试下一家（且不罚 cooldown）；
- 任一源给出 >= expected_latest 的 bar 即采用；
- 全链皆陈旧则 fail-open 返回其中最新一份并打 WARNING；
- expected_latest 缺省时行为与旧版完全一致（首个非空即返回）。
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.data.providers import (
    fetch_daily_with_fallback,
    get_provider_health,
    register_daily_provider,
    reset_provider_health,
    reset_provider_registry,
)


def _frame(last_date: str) -> pd.DataFrame:
    idx = pd.date_range(end=last_date, periods=3, freq="D")
    return pd.DataFrame({"close": range(1, len(idx) + 1)}, index=idx)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_provider_registry()
    reset_provider_health()
    yield
    reset_provider_registry()
    reset_provider_health()


def test_no_expected_latest_keeps_legacy_first_success():
    register_daily_provider("stale_first", {"CN"}, lambda s, d: _frame("2026-07-15"), priority=0)
    register_daily_provider("fresh_second", {"CN"}, lambda s, d: _frame("2026-07-16"), priority=10)
    df, provider = fetch_daily_with_fallback("600000", "CN", 30)
    assert provider == "stale_first"


def test_stale_provider_skipped_until_fresh_found():
    register_daily_provider("stale_first", {"CN"}, lambda s, d: _frame("2026-07-15"), priority=0)
    register_daily_provider("fresh_second", {"CN"}, lambda s, d: _frame("2026-07-16"), priority=10)
    df, provider = fetch_daily_with_fallback("600000", "CN", 30, expected_latest="2026-07-16")
    assert provider == "fresh_second"
    assert df.index.max().date().isoformat() == "2026-07-16"


def test_stale_success_does_not_trigger_cooldown():
    register_daily_provider(
        "stale_first", {"CN"}, lambda s, d: _frame("2026-07-15"), priority=0, cooldown_seconds=30
    )
    register_daily_provider("fresh_second", {"CN"}, lambda s, d: _frame("2026-07-16"), priority=10)
    fetch_daily_with_fallback("600000", "CN", 30, expected_latest="2026-07-16")
    health = get_provider_health()["stale_first"]
    assert health["cooldown_until"] is None
    assert health["successes"] == 1


def test_all_stale_fails_open_with_newest(caplog):
    register_daily_provider("older", {"CN"}, lambda s, d: _frame("2026-07-14"), priority=0)
    register_daily_provider("newer", {"CN"}, lambda s, d: _frame("2026-07-15"), priority=10)
    with caplog.at_level("WARNING", logger="backend.data.providers"):
        df, provider = fetch_daily_with_fallback("600000", "CN", 30, expected_latest="2026-07-16")
    assert provider == "newer"
    assert df.index.max().date().isoformat() == "2026-07-15"
    assert any("fail-open" in r.message for r in caplog.records)


def test_error_then_stale_then_fresh():
    def _boom(s, d):
        raise RuntimeError("429 Too Many Requests")

    register_daily_provider("broken", {"CN"}, _boom, priority=0, cooldown_seconds=30)
    register_daily_provider("stale", {"CN"}, lambda s, d: _frame("2026-07-15"), priority=10)
    register_daily_provider("fresh", {"CN"}, lambda s, d: _frame("2026-07-16"), priority=20)
    df, provider = fetch_daily_with_fallback("600000", "CN", 30, expected_latest="2026-07-16")
    assert provider == "fresh"


def test_all_failed_still_raises():
    def _boom(s, d):
        raise RuntimeError("down")

    register_daily_provider("broken", {"CN"}, _boom, priority=0)
    with pytest.raises(RuntimeError, match="daily data unavailable"):
        fetch_daily_with_fallback("600000", "CN", 30, expected_latest="2026-07-16")
