"""额度耗尽必须 fail-fast 并熔断，不得退化成重试风暴。

2026-08-20 事故：claude CLI 额度耗尽时秒回一句 "You've reached your usage limit"，
provider 只把它当成"输出非 JSON"的软失败 → _cli_retry 重试满 3 次 → 且无全局熔断，
于是为每一个标的重复付出 3 次子进程 + 6s sleep。m63_postmarket 因此空转 3 小时
（572 次徒劳调用），同期的标签作业"跑完"25 支但其中 131 次调用是失败降级值。
"""
import logging
import subprocess

import pytest

from backend.llm import local_cli_provider as provider_mod
from backend.llm.local_cli_provider import LocalCLIProvider

QUOTA_STDOUT = "You've reached your usage limit. Your limit will reset at 3am (Asia/Shanghai)."
TOOL = {"name": "score", "input_schema": {"type": "object", "properties": {"s": {"type": "number"}}}}


@pytest.fixture
def no_codex(monkeypatch):
    monkeypatch.setenv("LOCAL_CLI_NO_CODEX_FALLBACK", "true")
    monkeypatch.setattr(provider_mod.settings, "local_cli_prefer_codex", False)
    monkeypatch.setattr(provider_mod.time, "sleep", lambda *_: None)
    provider_mod.reset_quota_guard()
    yield
    provider_mod.reset_quota_guard()


def _fake_claude(calls, stdout):
    def run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr="")
    return run


def test_quota_reply_is_not_retried(no_codex, monkeypatch):
    """额度耗尽是不可恢复错误 → 单次调用，不重试。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, QUOTA_STDOUT))

    assert LocalCLIProvider(timeout=5).complete_structured("打分", TOOL) == {}
    assert len(calls) == 1, f"额度耗尽仍重试了 {len(calls)} 次"


def test_quota_trips_process_wide_breaker(no_codex, monkeypatch):
    """熔断后续调用直接短路，不再 spawn 子进程。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, QUOTA_STDOUT))
    p = LocalCLIProvider(timeout=5)

    for _ in range(10):
        assert p.complete_structured("打分", TOOL) == {}

    assert len(calls) == 1, f"熔断未生效：10 个调用发出了 {len(calls)} 次子进程"
    assert provider_mod.quota_guard_tripped() is True


def test_reset_clears_breaker(no_codex, monkeypatch):
    """额度恢复后可重置，不需要重启进程。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, QUOTA_STDOUT))
    p = LocalCLIProvider(timeout=5)
    p.complete_structured("打分", TOOL)
    assert provider_mod.quota_guard_tripped() is True

    provider_mod.reset_quota_guard()
    assert provider_mod.quota_guard_tripped() is False
    p.complete_structured("打分", TOOL)
    assert len(calls) == 2


def test_ordinary_bad_json_still_retries(no_codex, monkeypatch):
    """普通格式错误仍是可恢复的 → 保留 3 次重试，不被本次修复误伤。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, "抱歉，我不太确定"))

    assert LocalCLIProvider(timeout=5).complete_structured("打分", TOOL) == {}
    assert len(calls) == 3
    assert provider_mod.quota_guard_tripped() is False


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_expired_oauth_fails_once_and_breaks_later_calls(no_codex, monkeypatch, caplog, stream):
    calls = []
    error = "Failed to authenticate: OAuth session expired and could not be refreshed"

    def run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.CompletedProcess(
            cmd, 1,
            stdout=error if stream == "stdout" else "",
            stderr=error if stream == "stderr" else "",
        )

    monkeypatch.setattr(provider_mod.subprocess, "run", run)
    with caplog.at_level(logging.WARNING, logger=provider_mod.logger.name):
        p = LocalCLIProvider(timeout=5)
        for _ in range(5):
            assert p.complete_structured("打分", TOOL) == {}

    assert calls == ["claude"]
    assert provider_mod.calls_made() == 1
    assert provider_mod.quota_guard_reason() == "auth"
    assert provider_mod.AUTH_MARKER in caplog.text
    assert provider_mod.QUOTA_MARKER not in caplog.text
    assert "返回空结果" not in caplog.text


def test_force_fast_tier_downgrades_capable(monkeypatch):
    """跑批降档开关：capable → fast，默认关闭。"""
    monkeypatch.delenv("LOCAL_CLI_FORCE_FAST_TIER", raising=False)
    assert provider_mod._model_for_tier("capable") == provider_mod.settings.local_cli_model_capable

    monkeypatch.setenv("LOCAL_CLI_FORCE_FAST_TIER", "true")
    assert provider_mod._model_for_tier("capable") == provider_mod.settings.local_cli_model_fast
    assert provider_mod._model_for_tier("fast") == provider_mod.settings.local_cli_model_fast


def test_call_budget_trips_breaker(no_codex, monkeypatch):
    """预算上限：跑批吃不到底，给 20 日门和对话留余量。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, '{"s": 1}'))
    monkeypatch.setenv("LOCAL_CLI_CALL_BUDGET", "3")
    p = LocalCLIProvider(timeout=5)

    for _ in range(10):
        p.complete_structured("打分", TOOL)

    assert len(calls) == 3, f"预算 3 次，实际发出 {len(calls)} 次"
    assert provider_mod.quota_guard_tripped() is True
    assert provider_mod.calls_made() == 3


def test_no_budget_by_default(no_codex, monkeypatch):
    """默认不限制 —— 生产与单跑研究不受影响。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, '{"s": 1}'))
    monkeypatch.delenv("LOCAL_CLI_CALL_BUDGET", raising=False)
    p = LocalCLIProvider(timeout=5)

    for _ in range(10):
        p.complete_structured("打分", TOOL)

    assert len(calls) == 10
    assert provider_mod.quota_guard_tripped() is False


def test_budget_exhaustion_logs_distinct_marker(no_codex, monkeypatch, caplog):
    """本进程自设预算用尽 ≠ 账号真额度耗尽：日志身份必须可区分，不能被上层误判。

    2026-08-25 bug：两种熔断都打 LLM_QUOTA_EXHAUSTED / 含「额度耗尽」，上层跑批
    脚本按关键字抓这条日志，于是"预算用尽"（正常纪律）被误判成"账号没额度了"，
    导致整轮流水线被错误中止。
    """
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, '{"s": 1}'))
    monkeypatch.setenv("LOCAL_CLI_CALL_BUDGET", "2")
    p = LocalCLIProvider(timeout=5)

    with caplog.at_level(logging.WARNING, logger=provider_mod.logger.name):
        for _ in range(5):
            p.complete_structured("打分", TOOL)

    assert len(calls) == 2
    log_text = caplog.text
    assert provider_mod.BUDGET_MARKER in log_text
    assert provider_mod.QUOTA_MARKER not in log_text
    assert "额度耗尽" not in log_text
    assert provider_mod.quota_guard_reason() == "budget"


def test_real_quota_exhaustion_logs_quota_marker(no_codex, monkeypatch, caplog):
    """真账号额度耗尽必须仍走 LLM_QUOTA_EXHAUSTED / 含「额度耗尽」的原有告警路径。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, QUOTA_STDOUT))

    with caplog.at_level(logging.WARNING, logger=provider_mod.logger.name):
        assert LocalCLIProvider(timeout=5).complete_structured("打分", TOOL) == {}

    log_text = caplog.text
    assert provider_mod.QUOTA_MARKER in log_text
    assert "额度耗尽" in log_text
    assert provider_mod.BUDGET_MARKER not in log_text
    assert provider_mod.quota_guard_reason() == "quota"


def test_reset_clears_reason(no_codex, monkeypatch):
    """reset_quota_guard() 后 quota_guard_reason() 回到 None。"""
    calls = []
    monkeypatch.setattr(provider_mod.subprocess, "run", _fake_claude(calls, QUOTA_STDOUT))
    p = LocalCLIProvider(timeout=5)
    p.complete_structured("打分", TOOL)
    assert provider_mod.quota_guard_reason() == "quota"

    provider_mod.reset_quota_guard()
    assert provider_mod.quota_guard_reason() is None
