from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _stage4_dossier() -> dict:
    return {
        "symbol": "300308",
        "latest_signal": {
            "date": "2026-06-01",
            "recommendation": "观察",
            "composite_score": 12,
        },
        "long_term_label": {
            "date": "2026-06-01",
            "label": "值得持有",
            "quality": "trusted",
            "constraint_eligible": True,
            "expires_at": "2026-09-01",
            "key_findings": ["研发平台有韧性"],
        },
        "research_state": {
            "thesis": "新业务放量支撑长期成长",
            "risks": ["订单验证不及预期"],
            "open_questions": ["若毛利率跌破阈值则证伪"],
            "copilot": {"status": "present"},
        },
        "forward_thesis": {
            "base_case": "收入稳步兑现",
            "bull_case": "大客户订单超预期",
            "bear_case": "竞争压价",
            "management": {"capital_allocation": "needs review"},
            "moat": {"switching_cost": "medium"},
            "falsification_conditions": ["连续两个季度订单弱于同业"],
        },
        "evidence": [
            {
                "run_id": "run-1",
                "run_type": "daily",
                "as_of": "2026-06-01",
                "recommendation": "观察",
                "input_snapshot": {
                    "data_source": "sqlite",
                    "fetched_at": "2026-06-01T16:00:00Z",
                    "adjustment": "qfq",
                    "universe_hash": "abc",
                },
            }
        ],
        "deep_research": [{"source_ref": "research-1", "summary": "行业对照"}],
    }


def test_research_case_stage4_structure_is_api_compatible() -> None:
    from backend.api.schemas import ResearchCaseOut
    from backend.research.case import build_case

    case = build_case(_stage4_dossier(), as_of="2026-06-01")
    parsed = ResearchCaseOut(**case)
    stage4 = parsed.stage4_research_structure

    assert stage4["schema_version"] == "stage4_research_structure.v1"
    assert stage4["signal_impact"] == "none"
    assert stage4["thesis"]["status"] == "present"
    assert {scenario["scenario"] for scenario in stage4["scenarios"]} == {"base", "bull", "bear"}
    assert all(item["scoring_policy"] == "not_scored" for item in stage4["management_moat_checklist"])
    assert stage4["governance"]["owner_domain"] == "backend.research"


def test_run_card_links_refs_without_writes() -> None:
    from backend.evidence.run_card import build_run_card

    card = build_run_card(
        as_of="2026-06-01",
        symbol="300308",
        run_envelope={"run_id": "env-1", "as_of": "2026-06-01"},
        decision_run={"run_id": "decision-1", "symbol": "300308"},
        evidence_cards=[{"source_ref": "evidence-1", "as_of": "2026-06-01"}],
        pit_audit={"id": "pit-1", "pit_ok": True},
        trade_journal_ref={"id": "tj-1"},
        review_case_ref={"id": "rc-1"},
    )

    assert card["schema_version"] == "run_card.v1"
    assert card["read_only"] is True
    assert card["missing_refs"] == []
    assert card["refs"]["decision_run"]["ref"] == "decision-1"
    assert card["governance"]["rollback"].startswith("drop Run Card")


def test_run_card_missing_refs_catches_none_ref_and_bad_evidence_item() -> None:
    from backend.evidence.run_card import build_run_card

    card = build_run_card(
        as_of="2026-06-01",
        run_envelope={},
        decision_run={"run_id": "decision-1", "symbol": "300308"},
        evidence_cards=[None, {"source_ref": "evidence-1"}],
        pit_audit={"id": "pit-1", "pit_ok": True},
        trade_journal_ref={"id": "tj-1"},
        review_case_ref={"id": "rc-1"},
    )

    assert card["status"] == "degraded"
    assert "run_envelope" in card["missing_refs"]
    assert "evidence_cards[0]" in card["missing_refs"]


def test_notification_contract_shadow_preserves_bark_send_behavior() -> None:
    from backend.notification.contract import evaluate_notification_contract

    now = datetime(2026, 6, 1, 10, tzinfo=UTC)
    event = {
        "channel": "bark",
        "symbol": "300308",
        "event_type": "stop",
        "dedupe_key": "300308:stop:2026-06-01",
    }
    history = [{**event, "sent_at": (now - timedelta(minutes=5)).isoformat()}]

    shadow = evaluate_notification_contract(event, history=history, now=now)
    enforce = evaluate_notification_contract(event, history=history, now=now, enforcement_mode="enforce")

    assert shadow["would_suppress"] is True
    assert shadow["should_send"] is True
    assert "duplicate_in_window" in shadow["suppression_reasons"]
    assert shadow["silently_dropped"] is False
    assert enforce["should_send"] is False


def test_news_event_risk_facade_blocks_direction_weights() -> None:
    from backend.data.news_event_risk import build_news_event_risk_facade

    facade = build_news_event_risk_facade(
        as_of="2026-06-01",
        rows=[
            {
                "symbol": "300308",
                "as_of": "2026-06-01",
                "run_id": "m68-1",
                "status": "ok",
                "event_risk_level": "high",
                "event_risk_reasons_json": '["policy shock"]',
                "would_change_action": True,
                "evidence_json": '{"source": "m68"}',
                "degradation_flags_json": "[]",
            }
        ],
        m54_summary={"sample_count": 12},
        direction_experiment={"ic": 0.05},
    )

    assert facade["schema_version"] == "news_event_risk_facade.v1"
    assert facade["panel_payload"]["attention_count"] == 1
    assert facade["direction_experiment"]["direction_weights_allowed"] is False
    assert facade["direction_experiment"]["status"] == "blocked"
    assert facade["event_risk_cards"][0]["signal_impact"] == "none"


def test_exit_adjudication_contract_locks_shortlist_and_production() -> None:
    from backend.portfolio.exit_adjudication import (
        CURRENT_EXIT_VARIANT,
        LOCKED_SHORTLIST,
        SHADOW_EXIT_VARIANT,
        build_exit_adjudication_contract,
    )

    contract = build_exit_adjudication_contract(
        shadow_report={
            "meta": {
                "schema_version": "m58_exit_shadow.v1",
                "current_variant": CURRENT_EXIT_VARIANT,
                "shadow_variant": SHADOW_EXIT_VARIANT,
                "window": {"start": "2026-07-03", "end": "2026-08-01"},
            },
            "trade_differences": [{"symbol": "300308"}],
            "open_position_count": 2,
        },
        holdout_report={
            "meta": {
                "schema_version": "m58_exit_sweep.holdout_adjudication.v1",
                "baseline_variant": CURRENT_EXIT_VARIANT,
                "shortlist": list(LOCKED_SHORTLIST),
                "start": "2025-01-01",
                "end": "2026-07-02",
            },
            "entry_count": 40,
            "trial_count": 4,
            "results": [
                {
                    "variant": {"key": CURRENT_EXIT_VARIANT},
                    "net_return_pct": 14.78,
                    "max_drawdown_pct": -27.50,
                    "drawdown_violation": True,
                },
                {
                    "variant": {"key": "trailing_3__none"},
                    "net_return_pct": -20.92,
                    "max_drawdown_pct": -47.22,
                    "drawdown_violation": True,
                },
                {
                    "variant": {"key": SHADOW_EXIT_VARIANT},
                    "net_return_pct": -25.84,
                    "max_drawdown_pct": -49.29,
                    "drawdown_violation": True,
                },
                {
                    "variant": {"key": "trailing_2_5__drawdown_10"},
                    "net_return_pct": -28.38,
                    "max_drawdown_pct": -48.10,
                    "drawdown_violation": True,
                },
            ],
        },
    )

    assert contract["status"] == "adjudicated_no_promotion"
    assert contract["production_change_allowed"] is False
    assert contract["real_trading_allowed"] is False
    assert contract["locked_shortlist"]["locked"] is True
    assert contract["promotion_gate"]["status"] == "blocked"
    assert contract["promotion_gate"]["verdict"] == "retain_baseline_no_promotion"
    assert contract["holdout_verdict"]["shadow_variant_verdict"] == "reject_shadow_variants"
    assert contract["holdout_verdict"]["production_change_allowed"] is False
    assert len(contract["holdout_verdict"]["rejected_shadow_variants"]) == 3
    assert contract["governance"]["baseline"] == CURRENT_EXIT_VARIANT


def test_exit_adjudication_fail_closed_on_incomplete_holdout_results() -> None:
    from backend.portfolio.exit_adjudication import (
        CURRENT_EXIT_VARIANT,
        LOCKED_SHORTLIST,
        SHADOW_EXIT_VARIANT,
        build_exit_adjudication_contract,
    )

    contract = build_exit_adjudication_contract(
        shadow_report={
            "meta": {
                "current_variant": CURRENT_EXIT_VARIANT,
                "shadow_variant": SHADOW_EXIT_VARIANT,
            },
        },
        holdout_report={
            "meta": {"baseline_variant": CURRENT_EXIT_VARIANT, "shortlist": list(LOCKED_SHORTLIST)},
            "results": [
                {"variant": {"key": CURRENT_EXIT_VARIANT}, "net_return_pct": 14.78},
                {"variant": {"key": SHADOW_EXIT_VARIANT}, "net_return_pct": -25.84},
            ],
        },
    )

    assert contract["status"] == "blocked"
    assert contract["promotion_gate"]["verdict"] == "insufficient_evidence_no_promotion"
    assert contract["holdout_verdict"]["fail_closed"] is True
    assert "holdout_result_integrity_failed" in contract["blockers"]
    assert contract["holdout_verdict"]["rejected_shadow_variants"] == []


def test_exit_adjudication_fail_closed_on_duplicate_holdout_results() -> None:
    from backend.portfolio.exit_adjudication import (
        CURRENT_EXIT_VARIANT,
        LOCKED_SHORTLIST,
        SHADOW_EXIT_VARIANT,
        build_exit_adjudication_contract,
    )

    contract = build_exit_adjudication_contract(
        shadow_report={
            "meta": {
                "current_variant": CURRENT_EXIT_VARIANT,
                "shadow_variant": SHADOW_EXIT_VARIANT,
            },
        },
        holdout_report={
            "meta": {"baseline_variant": CURRENT_EXIT_VARIANT, "shortlist": list(LOCKED_SHORTLIST)},
            "results": [
                {"variant": {"key": CURRENT_EXIT_VARIANT}, "net_return_pct": 14.78},
                {"variant": {"key": "trailing_3__none"}, "net_return_pct": -20.92},
                {"variant": {"key": SHADOW_EXIT_VARIANT}, "net_return_pct": -25.84},
                {"variant": {"key": SHADOW_EXIT_VARIANT}, "net_return_pct": -25.84},
            ],
        },
    )

    integrity = contract["holdout_verdict"]["result_integrity"]
    assert contract["status"] == "blocked"
    assert contract["holdout_verdict"]["fail_closed"] is True
    assert SHADOW_EXIT_VARIANT in integrity["duplicate_or_wrong_count"]
    assert "trailing_2_5__drawdown_10" in integrity["missing"]


def test_memory_decision_context_remains_shadow_only_by_default(monkeypatch) -> None:
    from backend.config import settings
    from backend.memory.stock_memory import build_decision_memory_context

    monkeypatch.setattr(settings, "memory_decision_context_enabled", False)
    context = build_decision_memory_context(object(), symbol="300308", record_usage=False)

    assert context["memory_mode"] == "shadow_only"
    assert context["decision_context_enabled"] is False
    assert context["text"] == ""
    assert context["used_stock_memory_ids"] == []
