from __future__ import annotations

from copy import deepcopy

import pytest

from backend.evidence.daily_panel_sources import apply_daily_sources, bind_daily_sources


def _run():
    return {"run_id": "today", "as_of": "2026-09-16", "status": "complete",
            "freshness": {"input_coverage": {"llm_enabled": False}}}


def _workflow(day="2026-09-16", triggers=None):
    return {"date": day, "steps": [{"name": "m60_watchtower", "ok": True,
            "result": {"as_of": day, "summary": {"n_symbols_scanned": 2},
                       "triggers": triggers or [], "watchlist_errors": [],
                       "coverage": {"status": "complete"}}}]}


def _previous():
    return {"as_of": "2026-09-15", "run_envelope": {"run_id": "yesterday"},
            "cards": [{"card_type": "candidate", "payload": {"items": [{"symbol": "600001"}]}},
                      {"card_type": "position_health", "payload": {"items": []}}]}


def test_same_run_zero_watchtower_and_structured_delta():
    source = bind_daily_sources(envelope=_run(), workflow_result=_workflow(),
                                postmarket={"buy_candidates": {"items": [{"symbol": "600002"}]},
                                            "position_health": {"items": []}}, previous=_previous())
    assert source["watchtower"]["status"] == "ready_zero"
    assert source["watchtower"]["reason"]
    assert source["daily_delta"]["candidate_added"] == ["600002"]
    assert source["daily_delta"]["candidate_removed"] == ["600001"]
    panel, news = apply_daily_sources({}, {"status": "missing"}, source, _run())
    assert panel["watchtower_followups"]["run_id"] == "today"
    assert news["status"] == "not_applicable"
    assert news["reason"]


@pytest.mark.parametrize("mutation", ["stale", "coverage", "failed", "empty"])
def test_missing_or_incomplete_scan_never_becomes_no_risk(mutation):
    workflow = _workflow()
    report = workflow["steps"][0]["result"]
    if mutation == "stale":
        report["as_of"] = "2026-09-15"
    elif mutation == "coverage":
        report["coverage"] = {"status": "partial"}
    elif mutation == "failed":
        workflow["steps"][0]["ok"] = False
    else:
        report["summary"]["n_symbols_scanned"] = 0
    source = bind_daily_sources(envelope=_run(), workflow_result=workflow, postmarket={}, previous=None)
    assert source["watchtower"]["status"] in {"missing", "degraded"}
    assert source["daily_delta"]["no_previous_reason"]
    assert source["daily_delta"]["status"] == "missing"


def test_source_cannot_cross_run_or_rewrite_frozen_days():
    source = bind_daily_sources(envelope=_run(), workflow_result=_workflow(), postmarket={}, previous=None)
    other = deepcopy(_run())
    other["run_id"] = "other"
    assert apply_daily_sources({}, {"status": "missing"}, source, other) == ({}, {"status": "missing"})
    old = {**_run(), "as_of": "2026-09-15"}
    assert bind_daily_sources(envelope=old, workflow_result=_workflow(), postmarket={}, previous=None) is None
