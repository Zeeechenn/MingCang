"""Tests for backend.ops.llm_budget (M54 阶段7c 预算护栏)."""
from __future__ import annotations

from unittest.mock import patch

from backend.ops.llm_budget import BudgetStatus, check_budget, get_today_spend


def _fake_summary(buckets: dict) -> dict:
    return {"days": 1, "daily": [], "buckets": buckets, "total": {}}


class TestGetTodaySpend:
    def test_no_usage_rows_returns_zero(self):
        with patch(
            "backend.ops.llm_usage.get_usage_summary",
            return_value=_fake_summary({}),
        ):
            spent, unknown = get_today_spend("news_v2")
        assert spent == 0
        assert unknown is False

    def test_sums_tokens_in_and_out_for_bucket(self):
        summary = _fake_summary(
            {"news_v2": {"tokens_in": 1000, "tokens_out": 500, "cost_estimate_cny": 0.01, "calls": 3}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            spent, unknown = get_today_spend("news_v2")
        assert spent == 1500
        assert unknown is False

    def test_db_exception_is_fault_tolerant(self):
        with patch(
            "backend.ops.llm_usage.get_usage_summary",
            side_effect=RuntimeError("db exploded"),
        ):
            spent, unknown = get_today_spend("news_v2")
        assert spent == 0
        assert unknown is True


class TestCheckBudget:
    def test_limit_zero_means_unlimited(self):
        summary = _fake_summary(
            {"news_v2": {"tokens_in": 999_999, "tokens_out": 999_999, "cost_estimate_cny": 1.0, "calls": 1}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            status = check_budget("news_v2", limit_tokens=0)
        assert isinstance(status, BudgetStatus)
        assert status.exceeded is False
        assert status.unknown is False
        assert status.limit_tokens == 0

    def test_limit_negative_means_unlimited(self):
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=_fake_summary({})):
            status = check_budget("news_v2", limit_tokens=-10)
        assert status.exceeded is False

    def test_under_limit_not_exceeded(self):
        summary = _fake_summary(
            {"news_v2": {"tokens_in": 100, "tokens_out": 50, "cost_estimate_cny": 0.001, "calls": 1}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            status = check_budget("news_v2", limit_tokens=1000)
        assert status.spent_tokens == 150
        assert status.exceeded is False
        assert status.unknown is False

    def test_at_or_over_limit_exceeded(self):
        summary = _fake_summary(
            {"news_v2": {"tokens_in": 800, "tokens_out": 200, "cost_estimate_cny": 0.01, "calls": 5}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            status = check_budget("news_v2", limit_tokens=1000)
        assert status.spent_tokens == 1000
        assert status.exceeded is True

    def test_over_limit_exceeded(self):
        summary = _fake_summary(
            {"news_v2": {"tokens_in": 5000, "tokens_out": 5000, "cost_estimate_cny": 0.5, "calls": 20}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            status = check_budget("news_v2", limit_tokens=1000)
        assert status.exceeded is True
        assert status.spent_tokens == 10000

    def test_db_exception_fails_open_not_exceeded(self):
        with patch(
            "backend.ops.llm_usage.get_usage_summary",
            side_effect=RuntimeError("db exploded"),
        ):
            status = check_budget("news_v2", limit_tokens=100)
        assert status.exceeded is False
        assert status.unknown is True
        assert status.spent_tokens == 0

    def test_different_bucket_not_counted(self):
        summary = _fake_summary(
            {"sentiment": {"tokens_in": 10_000, "tokens_out": 10_000, "cost_estimate_cny": 1.0, "calls": 50}}
        )
        with patch("backend.ops.llm_usage.get_usage_summary", return_value=summary):
            status = check_budget("news_v2", limit_tokens=1000)
        assert status.spent_tokens == 0
        assert status.exceeded is False
