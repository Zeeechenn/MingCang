from __future__ import annotations

import copy
from dataclasses import asdict

import pytest

from backend.backtest.nav_replay import ReplayConfig, ReplayCostModel
from backend.evidence.model_comparison import build_model_comparison_report, content_hash


def fixture_bundle():
    days = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"]
    bundle = {
        "schema_version": "matched_model_replay.v1",
        "report_at": "2026-09-23T16:00:00+08:00",
        "calendar": days,
        "universe": ["600036"],
        "sectors": {"600036": "bank"},
        "models": {"gpt6": "gpt-6-astra", "claude": "claude-opus-5"},
        "scheduled_sessions": ["2026-09-19"],
        "execution_config": asdict(
            ReplayConfig(
                initial_cash=100000, entry_threshold=0.000001, reversal_threshold=0, max_positions=5
            )
        ),
        "cost_model": asdict(ReplayCostModel.for_market("CN")),
        "bars": [
            dict(symbol="600036", date=d, open=10, high=12, low=9, close=11, volume=1000000)
            for d in days
        ],
        "corporate_actions": [],
        "sessions": [],
        "provenance": {
            "price_basis": "raw",
            "volume_unit": "shares",
            "currency": "CNY",
            "price_source": "synthetic-fixture",
            "calendar_source": "fixture",
            "corporate_action_source": "fixture",
            "reviewed_by": "fixture-only",
            "source_receipt_sha256": "0" * 64,
            "action_coverage": {"600036": {"start": days[0], "end": days[-1]}},
        },
    }
    answer = {
        "as_of": days[0],
        "portfolio_rationale": "fixture",
        "decisions": [
            {
                "symbol": "600036",
                "action": "buy",
                "score": 20,
                "reason": "fixture",
                "risk": "fixture",
                "evidence_refs": ["source:600036"],
            }
        ],
    }
    session = {
        "session_id": "2026-09-19",
        "as_of": days[0],
        "cutoff": "2026-09-19T15:00:00+08:00",
        "shared_input_sha256": "a" * 64,
        "arms": {},
    }
    for arm, model in bundle["models"].items():
        session["arms"][arm] = {
            "status": "recorded",
            "resolved_model": model,
            "completed_at": "2026-09-19T15:01:00+08:00",
            "shared_input_sha256": "a" * 64,
            "request_sha256": "b" * 64,
            "response_sha256": "c" * 64,
            "receipt_sha256": "d" * 64,
            "answer": copy.deepcopy(answer),
            "answer_sha256": content_hash(answer),
            "billed_cost_cny": None,
        }
    bundle["sessions"].append(session)
    rebind(bundle)
    return bundle


def rebind(bundle):
    for name in ("calendar", "bars", "corporate_actions", "sectors"):
        bundle["provenance"][name + "_sha256"] = content_hash(bundle[name])


def left(bundle):
    return bundle["sessions"][0]["arms"]["gpt6"]


def test_actual_saturday_completion_queues_for_monday_open_and_keeps_timestamp():
    result = build_model_comparison_report(fixture_bundle())
    arm = result["arms"]["gpt6"]
    assert arm["replay"]["fills"][0]["date"] == "2026-09-21"
    assert arm["attempts"][0]["completed_at"].startswith("2026-09-19")
    assert arm["attempts"][0]["engine_queue_date"] == "2026-09-18"
    assert result["paired_decisions"] == 1
    assert result["comparison"]["trading_net_return_difference_pp"] == 0
    assert result["comparison"]["total_net_return_difference_pp"] is None
    assert not result["certifies_returns"]
    assert not arm["billing_complete"]


def test_delayed_answer_after_monday_open_cannot_fill_monday():
    b = fixture_bundle()
    left(b)["completed_at"] = "2026-09-21T02:00:00+00:00"
    r = build_model_comparison_report(b)
    assert r["arms"]["gpt6"]["replay"]["fills"][0]["date"] == "2026-09-22"


def test_no_future_open_keeps_pending_decision_without_fill():
    b = fixture_bundle()
    left(b)["completed_at"] = b["report_at"]
    r = build_model_comparison_report(b)["arms"]["gpt6"]
    assert r["replay"]["fills"] == []
    assert r["attempts"][0]["pending_future_open"]


def test_failed_and_missing_sessions_remain_in_fixed_denominator():
    b = fixture_bundle()
    b["scheduled_sessions"].append("2026-09-21")
    left(b).update(status="failed")
    r = build_model_comparison_report(b)
    assert r["scheduled_count"] == 2
    assert r["paired_decisions"] == 0
    assert r["arms"]["gpt6"]["failure_or_missing_rate"] == 1
    assert r["arms"]["claude"]["failure_or_missing_rate"] == 0.5
    assert not r["arms"]["gpt6"]["replay"]["fills"]
    assert r["arms"]["claude"]["replay"]["fills"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("price_basis", "qfq"),
        ("volume_unit", "lots"),
        ("corporate_action_source", ""),
        ("action_coverage", {}),
        ("bars_sha256", "bad"),
    ],
)
def test_unverified_execution_inputs_block_both_arms(field, value):
    b = fixture_bundle()
    b["provenance"][field] = value
    r = build_model_comparison_report(b)
    assert r["status"] == "blocked" and r["execution_blockers"]
    assert all(a["replay"] is None for a in r["arms"].values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("resolved_model", "fallback"),
        ("shared_input_sha256", "f" * 64),
        ("answer_sha256", "e" * 64),
        ("completed_at", "2026-09-19T15:01:00"),
        ("completed_at", "2026-09-24T01:00:00+08:00"),
        ("completed_at", "2026-09-18T01:00:00+08:00"),
    ],
)
def test_invalid_attempt_never_produces_an_order(field, value):
    b = fixture_bundle()
    left(b)[field] = value
    r = build_model_comparison_report(b)["arms"]["gpt6"]
    assert r["attempts"][0]["status"] == "invalid"
    assert r["replay"]["fills"] == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_invalid_price_numbers_rejected(value):
    b = fixture_bundle()
    b["bars"][0]["open"] = value
    with pytest.raises(ValueError):
        build_model_comparison_report(b)


def test_missing_bar_not_silently_marked_at_previous_close():
    b = fixture_bundle()
    b["bars"].pop()
    rebind(b)
    with pytest.raises(ValueError, match="price grid"):
        build_model_comparison_report(b)


def test_unclosed_prices_rejected():
    b = fixture_bundle()
    b["report_at"] = "2026-09-23T14:59:00+08:00"
    with pytest.raises(ValueError, match="unclosed"):
        build_model_comparison_report(b)


def test_duplicate_sessions_rejected_not_overwritten():
    b = fixture_bundle()
    b["sessions"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        build_model_comparison_report(b)


def test_hold_is_no_buy_and_bad_score_is_invalid():
    for score, action, status in [
        (0, "hold", "recorded"),
        (-1, "buy", "invalid"),
        (1e-9, "buy", "invalid"),
    ]:
        b = fixture_bundle()
        a = left(b)
        a["answer"]["decisions"][0].update(score=score, action=action)
        a["answer_sha256"] = content_hash(a["answer"])
        arm = build_model_comparison_report(b)["arms"]["gpt6"]
        assert arm["attempts"][0]["status"] == status
        assert arm["replay"]["fills"] == []


def test_actual_costs_include_failed_attempt_but_need_receipt():
    b = fixture_bundle()
    for arm in b["sessions"][0]["arms"].values():
        arm.update(billed_cost_cny=20, billing_receipt_sha256="e" * 64)
    r = build_model_comparison_report(b)
    arm = r["arms"]["gpt6"]
    assert arm["return_after_model_billing_pct"] == pytest.approx(
        (arm["replay"]["summary"]["ending_nav"] - 20 - 100000) / 1000
    )
    del left(b)["billing_receipt_sha256"]
    with pytest.raises(ValueError, match="receipt"):
        build_model_comparison_report(b)


def test_corporate_action_cash_conservation_and_same_policy():
    b = fixture_bundle()
    b["corporate_actions"] = [
        {"symbol": "600036", "date": "2026-09-22", "cash_dividend_per_share": 0.5}
    ]
    rebind(b)
    r = build_model_comparison_report(b)
    a = r["arms"]["gpt6"]["replay"]
    c = r["arms"]["claude"]["replay"]
    assert a == c
    event = a["corporate_actions"][0]
    assert event["cash_amount"] == event["shares_before"] * 0.5
    assert all(
        row["cash"] + row["market_value"] == pytest.approx(row["nav"], abs=0.02)
        for row in a["equity_curve"]
    )


def test_missing_sector_cannot_bypass_sector_limit():
    b = fixture_bundle()
    b["sectors"] = {}
    with pytest.raises(ValueError, match="sector"):
        build_model_comparison_report(b)


def test_two_answers_eligible_for_same_open_are_not_silently_overwritten():
    b = fixture_bundle()
    second = copy.deepcopy(b["sessions"][0])
    second.update(session_id="2026-09-20", cutoff="2026-09-20T15:00:00+08:00")
    for a in second["arms"].values():
        a["completed_at"] = "2026-09-20T15:01:00+08:00"
    b["sessions"].append(second)
    b["scheduled_sessions"].append("2026-09-20")
    r = build_model_comparison_report(b)
    assert r["paired_decisions"] == 1
    assert r["arms"]["gpt6"]["attempts"][1]["status"] == "invalid"


def test_account_retains_cash_positions_and_only_own_visible_history():
    from backend.evidence.model_comparison import build_model_account_context

    b = fixture_bundle()
    other = b["sessions"][0]["arms"]["claude"]
    other["answer"]["portfolio_rationale"] = "OTHER_ARM_PRIVATE_MARKER"
    other["answer_sha256"] = content_hash(other["answer"])
    import json

    before = build_model_account_context(b, arm="gpt6", cutoff="2026-09-19T16:00:00+08:00")
    after = build_model_account_context(b, arm="gpt6", cutoff="2026-09-21T16:00:00+08:00")
    assert before["cash"] == 100000 and before["holdings"] == []
    assert after["cash"] < 100000 and len(after["holdings"]) == 1
    assert after["own_fills"][0]["date"] == "2026-09-21"
    assert "OTHER_ARM_PRIVATE_MARKER" not in json.dumps(after)
    assert after["valuation_as_of"] == "2026-09-21"


def test_future_prices_actions_and_answers_cannot_change_visible_account():
    from backend.evidence.model_comparison import build_model_account_context

    b = fixture_bundle()
    at = "2026-09-21T16:00:00+08:00"
    original = build_model_account_context(b, arm="gpt6", cutoff=at)
    for bar in b["bars"]:
        if bar["date"] > "2026-09-21":
            bar.update(open=100, high=120, low=90, close=110)
    b["corporate_actions"] = [
        {"symbol": "600036", "date": "2026-09-23", "cash_dividend_per_share": 10}
    ]
    future = copy.deepcopy(b["sessions"][0])
    future.update(session_id="2026-09-22", cutoff="2026-09-22T16:00:00+08:00", as_of="2026-09-22")
    b["scheduled_sessions"].append("2026-09-22")
    b["sessions"].append(future)
    rebind(b)
    assert build_model_account_context(b, arm="gpt6", cutoff=at) == original


def test_late_response_excluded_from_account_history_and_orders():
    from backend.evidence.model_comparison import build_model_account_context

    b = fixture_bundle()
    left(b)["completed_at"] = "2026-09-22T10:00:00+08:00"
    r = build_model_account_context(b, arm="gpt6", cutoff="2026-09-21T16:00:00+08:00")
    assert r["own_prior_decisions"] == [] and r["own_fills"] == [] and r["cash"] == 100000


def test_account_blocks_unverified_action_coverage():
    from backend.evidence.model_comparison import build_model_account_context

    b = fixture_bundle()
    b["provenance"]["action_coverage"] = {}
    with pytest.raises(ValueError, match="account blocked"):
        build_model_account_context(b, arm="gpt6", cutoff="2026-09-21T16:00:00+08:00")


@pytest.mark.parametrize("answer", [[], "bad", {"as_of": "2026-09-18", "decisions": [None]}])
def test_malformed_recorded_answer_is_retained_as_invalid_attempt(answer):
    b = fixture_bundle()
    left(b)["answer"] = answer
    left(b)["answer_sha256"] = content_hash(answer)
    r = build_model_comparison_report(b)
    assert r["arms"]["gpt6"]["attempts"][0]["status"] == "invalid"
    assert r["scheduled_count"] == 1 and r["paired_decisions"] == 0


def test_request_context_carries_only_closed_own_account_and_frozen_costs():
    from backend.evidence.model_comparison import build_model_trial_request_context

    b = fixture_bundle()
    other = b["sessions"][0]["arms"]["claude"]
    other["answer"]["portfolio_rationale"] = "OTHER_ARM_PRIVATE_MARKER"
    other["answer_sha256"] = content_hash(other["answer"])
    proposal = build_model_trial_request_context(
        b, arm="gpt6", cutoff="2026-09-21T16:00:00+08:00"
    )
    assert proposal["status"] == "diagnostic_request_context_execution_blocked"
    assert proposal["economic_trial_activated"] is False
    assert proposal["account"]["cash"] < 100000
    assert proposal["account"]["holdings"]
    assert proposal["account"]["prior_fills"] == 1
    assert proposal["account"]["valuation_as_of"] == "2026-09-21"
    assert proposal["costs"] == b["cost_model"]
    assert "OTHER_ARM_PRIVATE_MARKER" not in str(proposal)


def test_request_context_requires_proven_raw_execution_inputs():
    from backend.evidence.model_comparison import build_model_trial_request_context

    b = fixture_bundle()
    b["provenance"]["price_basis"] = "forward_additive"
    with pytest.raises(ValueError, match="account blocked"):
        build_model_trial_request_context(
            b, arm="gpt6", cutoff="2026-09-21T16:00:00+08:00"
        )


def test_request_context_hash_is_independent_of_future_bars():
    from backend.evidence.model_comparison import build_model_trial_request_context

    b = fixture_bundle()
    cutoff = "2026-09-21T16:00:00+08:00"
    before = build_model_trial_request_context(b, arm="gpt6", cutoff=cutoff)
    for bar in b["bars"]:
        if bar["date"] > "2026-09-21":
            bar.update(open=100, high=120, low=90, close=110)
    rebind(b)
    after = build_model_trial_request_context(b, arm="gpt6", cutoff=cutoff)
    assert after == before
