from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


def _seed_shadow_inputs(db, *, symbol: str = "603986") -> None:
    from backend.data.database import NewsItem, Price, Signal, Stock

    db.add(Stock(symbol=symbol, name="兆易创新", market="CN", active=True))
    start = datetime(2026, 6, 10)
    for index in range(21):
        day = (start + timedelta(days=index)).date().isoformat()
        db.add(
            Price(
                symbol=symbol,
                date=day,
                open=100 + index,
                high=101 + index,
                low=99 + index,
                close=100 + index,
                volume=1000 if index < 20 else 3000,
            )
        )
    db.add(
        NewsItem(
            symbol=symbol,
            title="兆易创新签署重要采购合同",
            url=f"https://example.com/{symbol}",
            published_at=datetime(2026, 6, 30, 9),
            source="证券时报",
            provider="eastmoney",
            content="公司公告签署重要采购合同，交付节奏仍待观察。",
        )
    )
    db.add(
        Signal(
            symbol=symbol,
            date="2026-06-30",
            quant_score=0,
            technical_score=10,
            sentiment_score=10,
            composite_score=10,
            recommendation="观望",
            confidence="中",
        )
    )
    db.commit()


def _mock_signal():
    from backend.data.news_fusion import NewsSignalV2
    from backend.data.news_trigger import AttributionCard

    return NewsSignalV2(
        composite=0.8,
        news_score=0.75,
        flow_score=0.2,
        confidence=0.82,
        degradation_flags=[],
        contributing_clusters=["cluster-1"],
        attribution_card=AttributionCard(
            symbol="603986",
            as_of=datetime(2026, 6, 30, 23, 59, 59),
            main_cause="company_event",
            thesis_recheck=True,
        ),
        trigger_reasons=["new_announcement_event", "volume_anomaly"],
    )


def test_production_mirror_is_idempotent_and_never_mutates_official_signal(test_db, monkeypatch):
    from backend.data.database import NewsShadowRun, Signal
    from backend.data.news_shadow import run_production_mirror

    _seed_shadow_inputs(test_db)
    scorer = MagicMock(return_value=_mock_signal())
    monkeypatch.setattr("backend.data.news_shadow.score_news_v2", scorer)
    monkeypatch.setattr("backend.data.news_shadow.get_today_spend", lambda *_, **__: (100, False))
    before = test_db.query(Signal).one()
    official_snapshot = (
        before.id,
        before.sentiment_score,
        before.composite_score,
        before.recommendation,
    )

    first = run_production_mirror(
        as_of="2026-06-30",
        db=test_db,
        symbols=["603986"],
        collection_outcomes={"603986": "success"},
    )
    second = run_production_mirror(
        as_of="2026-06-30",
        db=test_db,
        symbols=["603986"],
        collection_outcomes={"603986": "success"},
    )

    assert first["counts"]["evidence"] == 1
    assert first["event_risk_counts"]["high"] == 1
    assert first["attention"][0]["symbol"] == "603986"
    assert second["counts"]["cache_hit"] == 1
    assert scorer.call_count == 1
    assert test_db.query(NewsShadowRun).count() == 1
    row = test_db.query(NewsShadowRun).one()
    assert row.price_change_pct == pytest.approx((120 / 119 - 1) * 100)
    assert row.volume_ratio == pytest.approx(3.0)
    assert row.pyramid_sentiment_score == 80
    assert row.event_risk_level == "high"
    assert row.counterfactual_composite == 38
    assert row.would_change_action is True
    after = test_db.query(Signal).one()
    assert (after.id, after.sentiment_score, after.composite_score, after.recommendation) == official_snapshot


def test_no_evidence_status_distinguishes_not_run_success_and_failure(test_db):
    from backend.data.database import Stock
    from backend.data.news_shadow import run_production_mirror

    for symbol in ("600001", "600002", "600003"):
        test_db.add(Stock(symbol=symbol, name=symbol, market="CN", active=True))
    test_db.commit()

    result = run_production_mirror(
        as_of="2026-06-30",
        db=test_db,
        symbols=["600001", "600002", "600003"],
        collection_outcomes={"600002": "success", "600003": "failed"},
    )

    assert result["counts"]["no_evidence"] == 1
    assert result["counts"]["verified_no_news"] == 1
    assert result["counts"]["fetch_failed"] == 1


def test_score_failure_is_persisted_without_aborting_other_symbols(test_db, monkeypatch):
    from backend.data.database import NewsShadowRun, Signal
    from backend.data.news_shadow import run_production_mirror

    _seed_shadow_inputs(test_db)
    monkeypatch.setattr(
        "backend.data.news_shadow.score_news_v2",
        MagicMock(side_effect=RuntimeError("provider unavailable")),
    )

    result = run_production_mirror(
        as_of="2026-06-30",
        db=test_db,
        symbols=["603986"],
        force=True,
    )

    assert result["ok"] is False
    row = test_db.query(NewsShadowRun).one()
    assert row.status == "score_failed"
    assert "provider unavailable" in row.error
    assert test_db.query(Signal).count() == 1


def test_stale_official_signal_is_not_used_for_action_comparison(test_db, monkeypatch):
    from backend.data.database import NewsShadowRun
    from backend.data.news_shadow import run_production_mirror

    _seed_shadow_inputs(test_db)
    monkeypatch.setattr("backend.data.news_shadow.score_news_v2", MagicMock(return_value=_mock_signal()))
    monkeypatch.setattr("backend.data.news_shadow.get_today_spend", lambda *_, **__: (0, False))

    run_production_mirror(as_of="2026-07-01", db=test_db, symbols=["603986"])

    row = test_db.query(NewsShadowRun).one()
    assert row.legacy_signal_date == "2026-06-30"
    assert row.counterfactual_composite is None
    assert row.would_change_action is False
    assert "stale" in row.counterfactual_note


def test_high_materiality_untriggered_is_a_review_queue_error_sample(test_db, monkeypatch):
    from backend.data.database import NewsShadowRun
    from backend.data.news_fusion import NewsSignalV2
    from backend.data.news_shadow import list_shadow_runs, run_production_mirror, shadow_summary

    _seed_shadow_inputs(test_db)
    untriggered = NewsSignalV2(
        composite=0.05,
        news_score=0.05,
        flow_score=0.0,
        confidence=0.3,
        degradation_flags=["low_confidence"],
        contributing_clusters=["cluster-1"],
        attribution_card=None,
        trigger_reasons=[],
    )
    monkeypatch.setattr("backend.data.news_shadow.score_news_v2", MagicMock(return_value=untriggered))
    monkeypatch.setattr("backend.data.news_shadow.get_today_spend", lambda *_, **__: (0, False))

    run_production_mirror(as_of="2026-06-30", db=test_db, symbols=["603986"])

    row = test_db.query(NewsShadowRun).one()
    assert row.event_risk_level == "high"
    assert "high_importance_untriggered" in row.event_risk_reasons_json
    assert shadow_summary(test_db)["review_queue"]["high_importance_untriggered"] == [row.run_id]
    assert list_shadow_runs(test_db)[0]["review_bucket"] == "high_importance_untriggered"


def test_stable_review_control_selection_is_restart_deterministic(test_db):
    import json

    from backend.data.database import NewsShadowRun
    from backend.data.news_shadow import list_shadow_runs, shadow_summary

    for symbol in ("600001", "600002", "600003", "600004", "600005", "600006"):
        test_db.add(
            NewsShadowRun(
                run_id=f"m68:production_mirror:2026-06-30:{symbol}",
                symbol=symbol,
                as_of="2026-06-30",
                profile="production_mirror",
                status="evidence",
                evidence_json=json.dumps({"max_l0_materiality": 0.4}),
                would_change_action=False,
            )
        )
    test_db.commit()

    first = shadow_summary(test_db)["review_queue"]["stable_control"]
    second = shadow_summary(test_db)["review_queue"]["stable_control"]

    assert first == second
    assert len(first) == 5
    all_runs = list_shadow_runs(test_db)
    assert {item["run_id"] for item in all_runs if item["review_bucket"] == "stable_control"} == set(first)
    excluded = next(item for item in all_runs if item["run_id"] not in first)
    filtered = list_shadow_runs(test_db, symbol=excluded["symbol"])
    assert filtered[0]["review_bucket"] == "routine"


def test_news_shadow_api_lists_details_and_feedback(test_db, monkeypatch):
    from backend.api.news_shadow_schemas import NewsShadowFeedbackCreate
    from backend.api.routes.news_shadow import (
        get_news_shadow_run,
        get_news_shadow_runs,
        get_news_shadow_summary,
        post_news_shadow_feedback,
    )
    from backend.data.news_shadow import run_production_mirror

    _seed_shadow_inputs(test_db)
    monkeypatch.setattr("backend.data.news_shadow.score_news_v2", MagicMock(return_value=_mock_signal()))
    monkeypatch.setattr("backend.data.news_shadow.get_today_spend", lambda *_, **__: (0, False))
    run_production_mirror(as_of="2026-06-30", db=test_db, symbols=["603986"])

    runs = get_news_shadow_runs(as_of="2026-06-30", db=test_db)
    assert len(runs) == 1
    run_id = runs[0]["run_id"]
    summary = get_news_shadow_summary(as_of="2026-06-30", db=test_db)
    assert summary["with_evidence"] == 1

    feedback = post_news_shadow_feedback(
        run_id=run_id,
        payload=NewsShadowFeedbackCreate(
            category="wrong_event_class",
            preferred_path="legacy",
            evidence_ref=runs[0]["evidence"]["cluster_audits"][0]["cluster_id"],
            note="归因忽略了公告正文",
        ),
        db=test_db,
    )
    assert feedback["category"] == "wrong_event_class"
    assert feedback["evidence_ref"] == runs[0]["evidence"]["cluster_audits"][0]["cluster_id"]
    detail = get_news_shadow_run(run_id=run_id, db=test_db)
    assert detail["evidence"]["items"][0]["content_status"] == "full"
    assert detail["feedback"][0]["note"] == "归因忽略了公告正文"


def test_news_shadow_routes_are_registered_under_api_prefix():
    from backend.main import app

    paths = {route.path for route in app.routes}
    assert "/api/news-shadow/runs" in paths
    assert "/api/news-shadow/summary" in paths
    assert "/api/news-shadow/runs/{run_id}/feedback" in paths
