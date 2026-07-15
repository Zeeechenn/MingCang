"""Research state and deep-research routes."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.agent.security import agent_mode
from backend.api.schemas import (
    BeneficiaryTiersRequest,
    CaseViewOut,
    DeepResearchRequest,
    DeepResearchResponse,
    DossierAdapterReviewOut,
    ForwardEvidenceRequest,
    ForwardThesisConfidenceRequest,
    ForwardThesisCreateRequest,
    ForwardThesisEvidenceRequest,
    ForwardThesisListOut,
    ForwardThesisOut,
    ForwardThesisStatusRequest,
    HypothesisCreateRequest,
    HypothesisListOut,
    HypothesisOut,
    HypothesisStatusRequest,
    MemoryArchiveRequest,
    MemoryCandidateCreateRequest,
    MemoryCandidateListOut,
    MemoryCandidateOut,
    MemoryPromoteRequest,
    MemoryRejectRequest,
    ResearchDossierOut,
    ResearchStateOut,
    ReviewCaseCreateRequest,
    ReviewCaseListOut,
    ReviewCaseOut,
    StressTestResponse,
    ThemeCreateRequest,
    ThemeListOut,
    ThemeOut,
    ThesisAttachReviewRequest,
    ThesisConfidenceOut,
    ThesisConfidenceRequest,
    ThesisCreateRequest,
    ThesisListOut,
    ThesisOut,
    ThesisStatusRequest,
    UniverseSnapshotListOut,
    UniverseSnapshotOut,
    UniverseSnapshotRequest,
)
from backend.config import settings
from backend.data.database import get_db
from backend.llm import runtime_readiness

router = APIRouter()


@router.get("/research/{symbol}/financials")
def get_symbol_financial_metrics(
    symbol: str,
    market: str = "CN",
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Return market-scoped, PIT-auditable financial rows for the frontend."""
    from backend.data.database import FinancialMetric
    from backend.data.market_profiles import (
        get_market_profile,
        instrument_key,
        normalize_market,
        normalize_symbol,
    )

    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    key = instrument_key(normalized_market, normalized_symbol)
    rows = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.asset_key == key)
        .order_by(FinancialMetric.report_date.desc())
        .limit(limit)
        .all()
    )
    fields = (
        "report_date", "disclosure_date", "period_type", "revenue", "revenue_yoy",
        "net_profit", "net_profit_yoy", "total_assets", "total_equity", "long_term_debt",
        "current_ratio", "operating_cf", "gross_margin", "roe", "asset_turnover", "source",
    )
    return {
        "asset_key": key,
        "symbol": normalized_symbol,
        "market": normalized_market,
        "currency": get_market_profile(normalized_market).currency,
        "rows": [{field: getattr(row, field) for field in fields} for row in rows],
    }


def _merge_template_list(explicit: list | None, generated: list) -> list | None:
    if explicit is None:
        return generated
    result = list(explicit)
    for item in generated:
        if item not in result:
            result.append(item)
    return result


def _normalize_template_payload(template: str | None, payload: dict | None) -> dict | None:
    if template is None and payload is None:
        return None
    if template not in (None, "ai_supply_chain"):
        raise ValueError(f"unsupported template: {template}")
    from backend.research.ai_supply_chain_template import normalize_ai_supply_chain_payload
    return normalize_ai_supply_chain_payload(payload)


def local_human_memory_gate(request: Request) -> None:
    """Allow memory trust decisions only from local human-operated paths."""
    if agent_mode() == "remote":
        raise HTTPException(
            status_code=403,
            detail="memory promote/reject is local human gated and unavailable to remote agents",
        )


def atlas_dormant_guard() -> None:
    """Keep Atlas research architecture dormant unless explicitly enabled."""
    if not settings.atlas_enabled:
        raise HTTPException(status_code=503, detail="atlas feature is disabled")


@router.get("/research/{symbol}/dossier", response_model=ResearchDossierOut)
def get_symbol_research_dossier(symbol: str, db: Session = Depends(get_db)):
    """Return the unified research dossier for one symbol."""
    from backend.research.dossier import build_research_dossier

    return build_research_dossier(db, symbol)


@router.get(
    "/research/{symbol}/adapter-review",
    response_model=DossierAdapterReviewOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_symbol_adapter_review(
    symbol: str,
    as_of: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Return the Phase 4 minimal read-only dossier adapter review.

    This endpoint maps the existing dossier into L1 evidence cards, an L2
    ResearchCase, and an L0 memory-candidate preview. It does not create memory
    candidates or promote trusted memory.
    """
    from backend.research.case import build_dossier_adapter_review
    from backend.research.dossier import build_research_dossier

    dossier = build_research_dossier(db, symbol)
    return build_dossier_adapter_review(dossier, as_of=as_of)


@router.post(
    "/research/{symbol}/prepare",
    dependencies=[Depends(agent_write_guard("research.prepare"))],
)
def prepare_symbol_research(
    symbol: str,
    name: str | None = None,
    market: str = "CN",
    db: Session = Depends(get_db),
):
    """Best-effort public first-run path: make one symbol researchable and return its dossier."""
    from backend.data.database import Stock
    from backend.data.market_profiles import instrument_key, normalize_market, normalize_symbol
    from backend.decision.market_policy import signal_scope_for
    from backend.research.dossier import build_research_dossier

    if market not in ("CN", "HK", "US"):
        raise HTTPException(400, "market must be CN, HK, or US")

    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    key = instrument_key(market, symbol)
    stock = db.query(Stock).filter(Stock.asset_key == key).first()
    if stock is None:
        stock = Stock(
            symbol=symbol,
            name=name or symbol,
            market=market,
            active=True,
        )
        db.add(stock)
    else:
        stock.active = True
        if name:
            stock.name = name
        stock.market = stock.market or market
    db.commit()

    steps: dict[str, dict] = {}
    try:
        from backend.data.market import backfill_if_needed
        rows = backfill_if_needed(symbol, stock.market, db, refresh_today=True)
        steps["prices"] = {"ok": True, "rows": rows}
    except Exception as exc:
        steps["prices"] = {"ok": False, "error": str(exc)}

    try:
        from backend.data.fundamentals import sync_financial_metrics_for_market

        rows = sync_financial_metrics_for_market(symbol, stock.market, db)
        steps["financials"] = {"ok": True, "rows": rows}
    except Exception as exc:
        steps["financials"] = {"ok": False, "error": str(exc)}

    try:
        from backend.data.news import fetch_stock_news, save_news_to_db

        news = fetch_stock_news(symbol, stock.name, stock.market)
        rows = save_news_to_db(news, db, market=stock.market)
        steps["news"] = {"ok": True, "rows": rows}
    except Exception as exc:
        steps["news"] = {"ok": False, "error": str(exc)}

    try:
        from backend.data.market import sync_market_index_to_db

        rows = sync_market_index_to_db(db, stock.market)
        steps["benchmark"] = {"ok": True, "rows": rows}
    except Exception as exc:
        steps["benchmark"] = {"ok": False, "error": str(exc)}

    if stock.market in {"HK", "US"}:
        try:
            from backend.data.global_disclosures import sync_global_disclosures

            rows = sync_global_disclosures(stock, db)
            steps["filings"] = {"ok": True, "rows": rows}
        except Exception as exc:
            steps["filings"] = {"ok": False, "error": str(exc)}

    dossier = build_research_dossier(db, symbol)
    return {
        "status": "prepared",
        "symbol": symbol,
        "asset_key": stock.asset_key,
        "market": stock.market,
        "currency": stock.currency,
        "signal_scope": signal_scope_for(stock.market, stock.symbol),
        "steps": steps,
        "runtime_readiness": runtime_readiness(),
        "missing": dossier.get("missing", []),
        "dossier": dossier,
    }


@router.post(
    "/research/{symbol}/review",
    dependencies=[Depends(agent_write_guard("research.review"))],
)
def review_symbol_latest_signal(symbol: str, db: Session = Depends(get_db)):
    """Run a lightweight attribution review for the latest evaluable signal."""
    from backend.decision.harness import review_latest_signal

    review = review_latest_signal(db, symbol)
    if review is None:
        raise HTTPException(404, "No evaluable signal found")
    return review


@router.post(
    "/research/{symbol}/copilot",
    dependencies=[Depends(agent_write_guard("research.copilot"))],
)
def refresh_symbol_copilot(symbol: str, db: Session = Depends(get_db)):
    """Generate a manual LLM shadow research copilot card.

    This calls the runtime LLM and writes ``ResearchState.copilot_json``; in
    remote agent mode it is gated by the ``research.copilot`` write action.
    """
    from backend.research.copilot import (
        CopilotInputError,
        CopilotUnavailable,
        generate_symbol_copilot,
    )

    try:
        return generate_symbol_copilot(symbol, db)
    except CopilotInputError as e:
        raise HTTPException(404, str(e)) from e
    except CopilotUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.post(
    "/research/deep/run",
    response_model=DeepResearchResponse,
    dependencies=[Depends(agent_write_guard("research.deep.run"))],
)
def run_deep_research_endpoint(
    request: DeepResearchRequest,
    db: Session = Depends(get_db),
):
    """Run a manual deep research report. This never creates daily signals.

    Deep research fans out to LLM and search providers; in remote agent mode it
    is gated by the ``research.deep.run`` write action.
    """
    from backend.research.deep_research import run_deep_research

    if not request.topic.strip():
        raise HTTPException(400, "topic is required")
    report = run_deep_research(
        topic=request.topic.strip(),
        symbols=request.symbols,
        db=db,
        as_of=request.as_of,
        seed_queries=request.seed_queries,
        persist=True,
    )
    readiness = runtime_readiness()
    is_blocked = getattr(report, "gate_status", None) == "blocked"
    return DeepResearchResponse(
        topic=report.topic,
        symbols=report.symbols,
        as_of=report.as_of,
        summary=report.summary,
        # F2: blocked reports must NOT expose the unwritten path to callers.
        report_path=None if is_blocked else (str(report.path) if report.path else None),
        source_count=report.source_count,
        risk_flags=report.risk_flags,
        readiness={
            "llm": readiness,
            "search_configured": bool(readiness.get("search", {}).get("tavily") or readiness.get("search", {}).get("anspire")),
        },
        gate_status=getattr(report, "gate_status", "gate_disabled"),
        gate_reasons=list(getattr(report, "gate_reasons", ())),
        gate_warnings=list(getattr(report, "gate_warnings", ())),
    )


@router.post(
    "/research/{symbol}/stress-test",
    response_model=StressTestResponse,
    dependencies=[Depends(agent_write_guard("research.stress_test")), Depends(atlas_dormant_guard)],
)
def run_stress_test_endpoint(symbol: str, db: Session = Depends(get_db)):
    """Run a single-pass red-team stress test against the ResearchCase. Advisory only.

    Builds the dossier and case envelope then calls run_stress_test; the result is
    never written to Signal, DecisionRun, or trusted ai_memory rows.
    In remote agent mode this is gated by the ``research.stress_test`` write action.
    """
    from backend.research.case import build_case
    from backend.research.dossier import build_research_dossier
    from backend.research.stress_test import (
        StressTestInputError,
        StressTestUnavailable,
        run_stress_test,
    )

    try:
        dossier = build_research_dossier(db, symbol)
        case = build_case(dossier)
        result = run_stress_test(case)
    except StressTestInputError as e:
        raise HTTPException(404, str(e)) from e
    except StressTestUnavailable as e:
        raise HTTPException(503, str(e)) from e

    readiness = runtime_readiness()
    return StressTestResponse(
        symbol=result["symbol"],
        as_of=result.get("as_of"),
        used_llm=result["used_llm"],
        llm_valid=result["llm_valid"],
        overall_severity=result["overall_severity"],
        blockers=result["blockers"],
        decision_deltas=result["decision_deltas"],
        follow_up_questions=result["follow_up_questions"],
        confidence_adjustments=result["confidence_adjustments"],
        role_outputs=result["role_outputs"],
        fallback_reason=result.get("fallback_reason"),
        generated_at=result["generated_at"],
        readiness={"llm": readiness},
    )


# ── M40 Thesis Ledger routes ──────────────────────────────────────────────────

@router.get(
    "/research/{symbol}/theses",
    response_model=ThesisListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_symbol_theses(symbol: str, db: Session = Depends(get_db)):
    """List all theses for a symbol."""
    from backend.research.thesis_ledger import list_theses
    items = list_theses(db, symbol=symbol)
    return {"symbol": symbol, "items": items, "total": len(items)}


@router.get(
    "/research/theses/{thesis_id}",
    response_model=ThesisOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_thesis_by_id(thesis_id: int, db: Session = Depends(get_db)):
    """Return a single thesis by id."""
    from backend.research.thesis_ledger import get_thesis
    result = get_thesis(db, thesis_id)
    if result is None:
        raise HTTPException(404, f"thesis {thesis_id} not found")
    return result


@router.post(
    "/research/{symbol}/theses",
    response_model=ThesisOut,
    dependencies=[Depends(agent_write_guard("research.thesis.create")), Depends(atlas_dormant_guard)],
)
def create_symbol_thesis(
    symbol: str,
    request: ThesisCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a new thesis for a symbol."""
    from backend.research.thesis_ledger import create_thesis
    try:
        return create_thesis(
            db,
            symbol=symbol,
            title=request.title,
            kill_conditions=request.kill_conditions,
            update_cadence_days=request.update_cadence_days,
            research_case_as_of=request.research_case_as_of,
            status=request.status,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post(
    "/research/theses/{thesis_id}/status",
    response_model=ThesisOut,
    dependencies=[Depends(agent_write_guard("research.thesis.update_status")), Depends(atlas_dormant_guard)],
)
def update_thesis_status_endpoint(
    thesis_id: int,
    request: ThesisStatusRequest,
    db: Session = Depends(get_db),
):
    """Transition a thesis to a new status."""
    from backend.research.thesis_ledger import update_thesis_status
    try:
        return update_thesis_status(db, thesis_id, request.new_status, note=request.note)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/theses/{thesis_id}/confidence",
    response_model=ThesisConfidenceOut,
    dependencies=[Depends(agent_write_guard("research.thesis.append_confidence")), Depends(atlas_dormant_guard)],
)
def append_thesis_confidence(
    thesis_id: int,
    request: ThesisConfidenceRequest,
    db: Session = Depends(get_db),
):
    """Append a confidence entry to a thesis."""
    from backend.research.thesis_ledger import append_confidence
    try:
        return append_confidence(
            db, thesis_id, score=request.score, as_of=request.as_of, note=request.note
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/theses/{thesis_id}/attach-review-case",
    response_model=ThesisOut,
    dependencies=[Depends(agent_write_guard("research.thesis.attach_review")), Depends(atlas_dormant_guard)],
)
def attach_review_case_to_thesis(
    thesis_id: int,
    request: ThesisAttachReviewRequest,
    db: Session = Depends(get_db),
):
    """Attach a review case payload to a thesis."""
    from backend.research.thesis_ledger import attach_review_case
    try:
        return attach_review_case(
            db, thesis_id, review_payload=request.review_payload, as_of=request.as_of
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


# ── M40 Theme Hypothesis Engine routes ───────────────────────────────────────

@router.get(
    "/research/themes",
    response_model=ThemeListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_themes_endpoint(db: Session = Depends(get_db)):
    """List all themes."""
    from backend.research.theme_hypothesis_engine import list_themes
    items = list_themes(db)
    return {"items": items, "total": len(items)}


@router.get(
    "/research/themes/{theme_id}",
    response_model=ThemeOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_theme_endpoint(theme_id: int, db: Session = Depends(get_db)):
    """Return a single theme by id."""
    from backend.research.theme_hypothesis_engine import get_theme
    result = get_theme(db, theme_id)
    if result is None:
        raise HTTPException(404, f"theme {theme_id} not found")
    return result


@router.post(
    "/research/themes",
    response_model=ThemeOut,
    dependencies=[Depends(agent_write_guard("research.theme.create")), Depends(atlas_dormant_guard)],
)
def create_theme_endpoint(request: ThemeCreateRequest, db: Session = Depends(get_db)):
    """Create a new theme."""
    from backend.research.theme_hypothesis_engine import create_theme
    try:
        return create_theme(
            db,
            theme_name=request.theme_name,
            description=request.description,
            status=request.status,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get(
    "/research/themes/{theme_id}/hypotheses",
    response_model=HypothesisListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_theme_hypotheses(theme_id: int, db: Session = Depends(get_db)):
    """List hypotheses for a theme."""
    from backend.research.theme_hypothesis_engine import list_hypotheses
    items = list_hypotheses(db, theme_id=theme_id)
    return {"theme_id": theme_id, "items": items, "total": len(items)}


@router.get(
    "/research/hypotheses/{hypothesis_id}",
    response_model=HypothesisOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_hypothesis_endpoint(hypothesis_id: int, db: Session = Depends(get_db)):
    """Return a single hypothesis by id."""
    from backend.research.theme_hypothesis_engine import get_hypothesis
    result = get_hypothesis(db, hypothesis_id)
    if result is None:
        raise HTTPException(404, f"hypothesis {hypothesis_id} not found")
    return result


@router.post(
    "/research/themes/{theme_id}/hypotheses",
    response_model=HypothesisOut,
    dependencies=[Depends(agent_write_guard("research.hypothesis.create")), Depends(atlas_dormant_guard)],
)
def create_hypothesis_endpoint(
    theme_id: int,
    request: HypothesisCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a new hypothesis under a theme."""
    from backend.research.theme_hypothesis_engine import create_hypothesis
    try:
        ai_supply_chain = _normalize_template_payload(request.template, request.template_payload)
        beneficiary_tiers = request.beneficiary_tiers
        evidence_gaps = request.evidence_gaps
        invalidation_conditions = request.invalidation_conditions
        if ai_supply_chain is not None:
            from backend.research.ai_supply_chain_template import hypothesis_fields_from_payload
            mapped = hypothesis_fields_from_payload(ai_supply_chain)
            beneficiary_tiers = _merge_template_list(beneficiary_tiers, mapped["beneficiary_tiers"])
            evidence_gaps = _merge_template_list(evidence_gaps, mapped["evidence_gaps"])
            invalidation_conditions = _merge_template_list(
                invalidation_conditions,
                mapped["invalidation_conditions"],
            )
        return create_hypothesis(
            db,
            theme_id=theme_id,
            statement=request.statement,
            beneficiary_tiers=beneficiary_tiers,
            evidence_gaps=evidence_gaps,
            invalidation_conditions=invalidation_conditions,
            ai_supply_chain=ai_supply_chain,
            status=request.status,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/hypotheses/{hypothesis_id}/status",
    response_model=HypothesisOut,
    dependencies=[Depends(agent_write_guard("research.hypothesis.update_status")), Depends(atlas_dormant_guard)],
)
def update_hypothesis_status_endpoint(
    hypothesis_id: int,
    request: HypothesisStatusRequest,
    db: Session = Depends(get_db),
):
    """Transition a hypothesis to a new status."""
    from backend.research.theme_hypothesis_engine import update_hypothesis_status
    try:
        return update_hypothesis_status(db, hypothesis_id, request.new_status, note=request.note)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/hypotheses/{hypothesis_id}/beneficiary-tiers",
    response_model=HypothesisOut,
    dependencies=[Depends(agent_write_guard("research.hypothesis.set_tiers")), Depends(atlas_dormant_guard)],
)
def set_hypothesis_tiers(
    hypothesis_id: int,
    request: BeneficiaryTiersRequest,
    db: Session = Depends(get_db),
):
    """Set advisory beneficiary tiers on a hypothesis.

    NOTE: tiers are advisory display metadata ONLY — must NOT feed
    aggregate/aggregate_v2/run_pipeline/apply_research_constraints.
    """
    from backend.research.theme_hypothesis_engine import set_beneficiary_tiers
    try:
        return set_beneficiary_tiers(db, hypothesis_id, tiers=request.tiers)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/hypotheses/{hypothesis_id}/forward-evidence",
    response_model=HypothesisOut,
    dependencies=[Depends(agent_write_guard("research.hypothesis.attach_evidence")), Depends(atlas_dormant_guard)],
)
def attach_forward_evidence_endpoint(
    hypothesis_id: int,
    request: ForwardEvidenceRequest,
    db: Session = Depends(get_db),
):
    """Attach forward evidence to a hypothesis."""
    from backend.research.theme_hypothesis_engine import attach_forward_evidence
    try:
        return attach_forward_evidence(
            db, hypothesis_id, evidence_payload=request.evidence_payload, as_of=request.as_of
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


# ── M40 Review Loop routes ────────────────────────────────────────────────────

@router.get(
    "/research/{symbol}/review-cases",
    response_model=ReviewCaseListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_symbol_review_cases(symbol: str, db: Session = Depends(get_db)):
    """List review cases for a symbol."""
    from backend.research.review_loop import list_review_cases
    items = list_review_cases(db, symbol=symbol)
    return {"symbol": symbol, "items": items, "total": len(items)}


@router.get(
    "/research/review-cases/{review_case_id}",
    response_model=ReviewCaseOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_review_case_endpoint(review_case_id: int, db: Session = Depends(get_db)):
    """Return a single review case by id."""
    from backend.research.review_loop import get_review_case
    result = get_review_case(db, review_case_id)
    if result is None:
        raise HTTPException(404, f"review case {review_case_id} not found")
    return result


@router.post(
    "/research/{symbol}/review-cases",
    response_model=ReviewCaseOut,
    dependencies=[Depends(agent_write_guard("research.review_case.create")), Depends(atlas_dormant_guard)],
)
def create_review_case_endpoint(
    symbol: str,
    request: ReviewCaseCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a review case for a symbol."""
    from backend.research.review_loop import create_review_case
    try:
        return create_review_case(
            db,
            symbol=symbol,
            as_of=request.as_of,
            signal_id=request.signal_id,
            thesis_id=request.thesis_id,
            research_case_as_of=request.research_case_as_of,
            review_payload=request.review_payload,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get(
    "/research/memory-candidates",
    response_model=MemoryCandidateListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_memory_candidates_endpoint(
    symbol: str | None = Query(default=None),
    source_trust: str | None = Query(default=None),
    review_case_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List memory candidates, optionally filtered."""
    from backend.research.review_loop import list_memory_candidates
    items = list_memory_candidates(
        db, symbol=symbol, source_trust=source_trust,
        review_case_id=review_case_id, limit=limit,
    )
    return {"items": items, "total": len(items)}


@router.get(
    "/research/memory-candidates/{candidate_id}",
    response_model=MemoryCandidateOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_memory_candidate_endpoint(candidate_id: int, db: Session = Depends(get_db)):
    """Return a single memory candidate by id."""
    from backend.research.review_loop import get_memory_candidate
    result = get_memory_candidate(db, candidate_id)
    if result is None:
        raise HTTPException(404, f"memory candidate {candidate_id} not found")
    return result


@router.post(
    "/research/memory-candidates",
    response_model=MemoryCandidateOut,
    dependencies=[Depends(agent_write_guard("research.memory_candidate.create")), Depends(atlas_dormant_guard)],
)
def create_memory_candidate_endpoint(
    request: MemoryCandidateCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a memory candidate. source_trust is always 'pending' — not caller-settable."""
    from backend.research.review_loop import create_memory_candidate
    try:
        return create_memory_candidate(
            db,
            symbol=request.symbol,
            summary=request.summary,
            memory_type=request.memory_type,
            importance=request.importance,
            confidence=request.confidence,
            review_case_id=request.review_case_id,
            source_ref=request.source_ref,
            note=request.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post(
    "/research/memory-candidates/{candidate_id}/promote",
    response_model=MemoryCandidateOut,
    dependencies=[
        Depends(local_human_memory_gate),
        Depends(agent_write_guard("research.memory.promote")),
        Depends(atlas_dormant_guard),
    ],
)
def promote_memory_candidate(
    candidate_id: int,
    request: MemoryPromoteRequest,
    db: Session = Depends(get_db),
):
    """HUMAN-GATED: must never be called from any LLM agent or automated code path.

    Promote a pending memory candidate to 'trusted' and materialise a StockMemoryItem.
    confirmed_by must be a non-empty string identifying the human actor.
    """
    if not request.confirmed_by or not request.confirmed_by.strip():
        raise HTTPException(400, "confirmed_by must be a non-empty string")
    from backend.research.review_loop import promote_memory
    try:
        return promote_memory(db, candidate_id, confirmed_by=request.confirmed_by)
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


@router.post(
    "/research/memory-candidates/{candidate_id}/reject",
    response_model=MemoryCandidateOut,
    dependencies=[
        Depends(local_human_memory_gate),
        Depends(agent_write_guard("research.memory.reject")),
        Depends(atlas_dormant_guard),
    ],
)
def reject_memory_candidate_endpoint(
    candidate_id: int,
    request: MemoryRejectRequest,
    db: Session = Depends(get_db),
):
    """HUMAN-GATED: must never be called from any LLM agent or automated code path.

    Reject a pending memory candidate. confirmed_by must be a non-empty string.
    """
    if not request.confirmed_by or not request.confirmed_by.strip():
        raise HTTPException(400, "confirmed_by must be a non-empty string")
    from backend.research.review_loop import reject_memory_candidate
    try:
        return reject_memory_candidate(
            db, candidate_id, confirmed_by=request.confirmed_by, note=request.note
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _candidate_target(db: Session, source_ref: str | None) -> dict | None:
    if not source_ref:
        return None
    atom = db.execute(text("""
        SELECT id, scope_type, scope_key, memory_type, summary, evidence_json,
               source_type, source_ref, trust_state, created_at, updated_at
        FROM memory_atoms
        WHERE source_ref = :source_ref
        ORDER BY id ASC
        LIMIT 1
    """), {"source_ref": source_ref}).mappings().first()
    if atom is not None:
        row = dict(atom)
        row["target_type"] = "memory_atoms"
        row["evidence"] = _json_dict(row.pop("evidence_json"))
        return row
    profile = db.execute(text("""
        SELECT id, profile_type, profile_key, summary, atom_ids_json,
               trust_state, source_type, source_ref, created_at, updated_at
        FROM memory_profiles
        WHERE source_ref = :source_ref
        ORDER BY id ASC
        LIMIT 1
    """), {"source_ref": source_ref}).mappings().first()
    if profile is not None:
        row = dict(profile)
        row["target_type"] = "memory_profiles"
        row["evidence"] = _json_dict(row.pop("atom_ids_json"))
        return row
    scenario = db.execute(text("""
        SELECT id, scope_type, scope_key, title, summary, atom_ids_json,
               trust_state, source_type, source_ref, created_at, updated_at
        FROM memory_scenarios
        WHERE source_ref = :source_ref
        ORDER BY id ASC
        LIMIT 1
    """), {"source_ref": source_ref}).mappings().first()
    if scenario is not None:
        row = dict(scenario)
        row["target_type"] = "memory_scenarios"
        row["evidence"] = _json_dict(row.pop("atom_ids_json"))
        return row
    return None


def _source_events(db: Session, event_ids: list[int]) -> list[dict]:
    if not event_ids:
        return []
    rows = db.execute(text("""
        SELECT id, trace_type, namespace, subject, symbols_json, themes_json,
               content, source_type, source_ref, as_of, event_time, ingestion_time
        FROM evolution_traces
        WHERE id IN :ids
        ORDER BY id ASC
    """).bindparams(bindparam("ids", expanding=True)), {"ids": event_ids}).mappings().all()
    events = []
    for row in rows:
        item = dict(row)
        item["symbols"] = _json_list(item.pop("symbols_json"))
        item["themes"] = _json_list(item.pop("themes_json"))
        events.append(item)
    return events


def _memory_diff(db: Session, candidate: dict, target: dict | None) -> dict:
    existing: list[dict] = []
    symbol = candidate.get("symbol")
    memory_type = candidate.get("memory_type")
    if symbol and symbol != "__GLOBAL__":
        rows = db.execute(text("""
            SELECT 'memory_atoms' AS source, id, summary, trust_state AS status
            FROM memory_atoms
            WHERE scope_key = :symbol AND memory_type = :memory_type
              AND trust_state = 'trusted'
            UNION ALL
            SELECT 'stock_memory_items' AS source, id, summary, status
            FROM stock_memory_items
            WHERE symbol = :symbol AND memory_type = :memory_type
              AND status != 'archived'
            ORDER BY id DESC
            LIMIT 5
        """), {"symbol": symbol, "memory_type": memory_type}).mappings().all()
        existing = [dict(row) for row in rows]
    elif target and target.get("target_type") == "memory_profiles":
        rows = db.execute(text("""
            SELECT 'memory_profiles' AS source, id, summary, trust_state AS status
            FROM memory_profiles
            WHERE profile_type = :profile_type AND profile_key = :profile_key
              AND trust_state = 'trusted'
            ORDER BY id DESC
            LIMIT 5
        """), {
            "profile_type": target.get("profile_type"),
            "profile_key": target.get("profile_key"),
        }).mappings().all()
        existing = [dict(row) for row in rows]
    return {"candidate": candidate.get("summary"), "existing": existing}


@router.get("/memory/evolution/candidates")
def list_memory_evolution_candidates(
    status: str | None = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List memory-evolution candidates with pagination and status filter."""
    from backend.data.database import MemoryPromotionCandidate
    from backend.research.review_loop import _cand_to_dict

    q = db.query(MemoryPromotionCandidate)
    if status:
        q = q.filter(MemoryPromotionCandidate.source_trust == status)
    total = q.count()
    rows = (
        q.order_by(MemoryPromotionCandidate.created_at.desc(), MemoryPromotionCandidate.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": [_cand_to_dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/memory/evolution/candidates/{candidate_id}")
def get_memory_evolution_candidate_detail(candidate_id: int, db: Session = Depends(get_db)):
    """Return one candidate with sanitized source-event evidence and existing-memory diff."""
    from backend.research.review_loop import get_memory_candidate

    candidate = get_memory_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(404, f"memory candidate {candidate_id} not found")
    target = _candidate_target(db, candidate.get("source_ref"))
    evidence = (target or {}).get("evidence") or {}
    source_event_ids = [int(item) for item in evidence.get("source_event_ids", []) if str(item).isdigit()]
    return {
        "candidate": candidate,
        "target": target,
        "source_events": _source_events(db, source_event_ids),
        "diff": _memory_diff(db, candidate, target),
        "shadow_eval": {"enabled": False, "reason": "shadow evaluator is a later M57 phase"},
    }


@router.post(
    "/memory/evolution/candidates/{candidate_id}/promote",
    response_model=MemoryCandidateOut,
    dependencies=[Depends(local_human_memory_gate), Depends(agent_write_guard("research.memory.promote"))],
)
def promote_memory_evolution_candidate(
    candidate_id: int,
    request: MemoryPromoteRequest,
    db: Session = Depends(get_db),
):
    """HUMAN-GATED: promote through the existing M37 memory gate."""
    return promote_memory_candidate(candidate_id=candidate_id, request=request, db=db)


@router.post(
    "/memory/evolution/candidates/{candidate_id}/reject",
    response_model=MemoryCandidateOut,
    dependencies=[Depends(local_human_memory_gate), Depends(agent_write_guard("research.memory.reject"))],
)
def reject_memory_evolution_candidate(
    candidate_id: int,
    request: MemoryRejectRequest,
    db: Session = Depends(get_db),
):
    """HUMAN-GATED: reject with a required reason and trace the reason."""
    if not request.note or not request.note.strip():
        raise HTTPException(400, "reject reason is required")
    result = reject_memory_candidate_endpoint(candidate_id=candidate_id, request=request, db=db)
    from backend.memory.evolution_trace import NAMESPACE_OPERATION_REVIEW, record_trace

    record_trace(
        db,
        trace_type="memory_evolution.reject",
        namespace=NAMESPACE_OPERATION_REVIEW,
        subject=str(candidate_id),
        content=f"Memory evolution candidate {candidate_id} rejected: {request.note.strip()}",
        payload={"candidate_id": candidate_id, "reason": request.note.strip(), "confirmed_by": request.confirmed_by},
        source_type="memory_evolution_api",
        source_ref=f"memory_evolution:{candidate_id}:reject",
    )
    return result


@router.post(
    "/memory/evolution/candidates/{candidate_id}/archive",
    response_model=MemoryCandidateOut,
    dependencies=[Depends(local_human_memory_gate), Depends(agent_write_guard("research.memory.archive"))],
)
def archive_memory_evolution_candidate(
    candidate_id: int,
    request: MemoryArchiveRequest,
    db: Session = Depends(get_db),
):
    """HUMAN-GATED: archive a pending candidate without promoting it."""
    from backend.data.database import MemoryPromotionCandidate
    from backend.memory.audit_log import audit_write
    from backend.memory.evolution_trace import NAMESPACE_OPERATION_REVIEW, record_trace
    from backend.research.review_loop import _cand_to_dict

    row = db.query(MemoryPromotionCandidate).filter(MemoryPromotionCandidate.id == candidate_id).first()
    if row is None:
        raise HTTPException(404, f"memory candidate {candidate_id} not found")
    if row.source_trust != "pending":
        raise HTTPException(400, f"candidate {candidate_id} is already in state {row.source_trust!r}")
    row.source_trust = "archived"
    row.note = request.reason.strip()
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()
    audit_write(
        db,
        "memory_evolution.archive",
        f"candidate {candidate_id} archived by {request.confirmed_by!r}; reason={request.reason!r}",
        related_symbol=None if row.symbol == "__GLOBAL__" else row.symbol,
    )
    record_trace(
        db,
        trace_type="memory_evolution.archive",
        namespace=NAMESPACE_OPERATION_REVIEW,
        subject=str(candidate_id),
        content=f"Memory evolution candidate {candidate_id} archived: {request.reason.strip()}",
        payload={"candidate_id": candidate_id, "reason": request.reason.strip(), "confirmed_by": request.confirmed_by},
        source_type="memory_evolution_api",
        source_ref=f"memory_evolution:{candidate_id}:archive",
    )
    return _cand_to_dict(row)


# ── M40 Universe Guard routes ─────────────────────────────────────────────────

@router.get(
    "/research/universe-snapshots",
    response_model=UniverseSnapshotListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_universe_snapshots(db: Session = Depends(get_db)):
    """List universe snapshots. Returns 503 if universe_guard_enabled=False."""
    from backend.config import settings
    if not settings.universe_guard_enabled:
        raise HTTPException(503, "universe_guard feature is disabled")
    from backend.research.universe_guard import list_snapshots
    items = list_snapshots(db)
    return {"items": items, "total": len(items)}


@router.get(
    "/research/universe-snapshots/by-cutoff",
    response_model=UniverseSnapshotOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_snapshot_by_cutoff(
    cutoff_date: str = Query(...),
    market_filter: str = Query(default="ALL"),
    db: Session = Depends(get_db),
):
    """Return the nearest universe snapshot on or before cutoff_date."""
    from backend.research.universe_guard import get_snapshot_for_cutoff
    result = get_snapshot_for_cutoff(db, cutoff_date, market_filter)
    if result is None:
        raise HTTPException(404, f"no snapshot found for cutoff_date={cutoff_date}")
    return result


@router.get(
    "/research/universe-snapshots/{snapshot_id}",
    response_model=UniverseSnapshotOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_universe_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    """Return a single universe snapshot by id."""
    from backend.research.universe_guard import get_snapshot
    result = get_snapshot(db, snapshot_id)
    if result is None:
        raise HTTPException(404, f"snapshot {snapshot_id} not found")
    return result


@router.get("/research/universe-provenance", dependencies=[Depends(atlas_dormant_guard)])
def get_universe_provenance(
    symbols: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
):
    """Return provenance completeness report for the given symbols."""
    from backend.research.universe_guard import provenance_completeness_report
    return provenance_completeness_report(db, symbols=symbols if symbols else None)


@router.post(
    "/research/universe-snapshots",
    response_model=UniverseSnapshotOut,
    dependencies=[Depends(agent_write_guard("research.universe.snapshot")), Depends(atlas_dormant_guard)],
)
def snapshot_universe_endpoint(
    request: UniverseSnapshotRequest,
    db: Session = Depends(get_db),
):
    """Create a universe snapshot. Returns 503 if universe_guard_enabled=False."""
    from backend.config import settings
    if not settings.universe_guard_enabled:
        raise HTTPException(503, "universe_guard feature is disabled")
    from backend.research.universe_guard import snapshot_universe
    try:
        result = snapshot_universe(
            db,
            symbols=request.symbols,
            cutoff_date=request.cutoff_date,
            market_filter=request.market_filter,
            context=request.context,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not result:
        raise HTTPException(503, "universe_guard feature is disabled")
    return result


# ── M40 Forward Thesis routes ─────────────────────────────────────────────────

@router.get(
    "/research/{symbol}/forward-theses",
    response_model=ForwardThesisListOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def list_symbol_forward_theses(symbol: str, db: Session = Depends(get_db)):
    """List forward theses for a symbol."""
    from backend.research.forward_thesis import list_forward_theses
    items = list_forward_theses(db, symbol=symbol)
    return {"symbol": symbol, "items": items, "total": len(items)}


@router.get(
    "/research/forward-theses/{forward_thesis_id}",
    response_model=ForwardThesisOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_forward_thesis_endpoint(forward_thesis_id: int, db: Session = Depends(get_db)):
    """Return a single forward thesis by id."""
    from backend.research.forward_thesis import get_forward_thesis
    result = get_forward_thesis(db, forward_thesis_id)
    if result is None:
        raise HTTPException(404, f"forward thesis {forward_thesis_id} not found")
    return result


@router.post(
    "/research/{symbol}/forward-theses",
    response_model=ForwardThesisOut,
    dependencies=[Depends(agent_write_guard("research.forward_thesis.create")), Depends(atlas_dormant_guard)],
)
def create_forward_thesis_endpoint(
    symbol: str,
    request: ForwardThesisCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a forward thesis for a symbol. Returns 503 if forward_thesis_enabled=False."""
    from backend.config import settings
    if not settings.forward_thesis_enabled:
        raise HTTPException(503, "forward_thesis feature is disabled")
    from backend.research.forward_thesis import create_forward_thesis
    try:
        ai_supply_chain = _normalize_template_payload(request.template, request.template_payload)
        invalidation_conditions = request.invalidation_conditions
        follow_up_metrics = request.follow_up_metrics
        evidence_manifest = request.evidence_manifest
        if ai_supply_chain is not None:
            from backend.research.ai_supply_chain_template import forward_thesis_fields_from_payload
            mapped = forward_thesis_fields_from_payload(ai_supply_chain)
            invalidation_conditions = _merge_template_list(
                invalidation_conditions,
                mapped["invalidation_conditions"],
            )
            follow_up_metrics = _merge_template_list(follow_up_metrics, mapped["follow_up_metrics"])
            evidence_manifest = _merge_template_list(evidence_manifest, mapped["evidence_manifest"])
        result = create_forward_thesis(
            db,
            statement=request.statement,
            symbol=symbol,
            horizon_date=request.horizon_date,
            thesis_id=request.thesis_id,
            theme_hypothesis_id=request.theme_hypothesis_id,
            universe_snapshot_id=request.universe_snapshot_id,
            confidence_low=request.confidence_low,
            confidence_high=request.confidence_high,
            invalidation_conditions=invalidation_conditions,
            follow_up_metrics=follow_up_metrics,
            evidence_manifest=evidence_manifest,
            next_review_date=request.next_review_date,
            review_cadence_days=request.review_cadence_days,
            status=request.status,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not result:
        raise HTTPException(503, "forward_thesis feature is disabled")
    return result


@router.post(
    "/research/forward-theses/{forward_thesis_id}/status",
    response_model=ForwardThesisOut,
    dependencies=[Depends(agent_write_guard("research.forward_thesis.update_status")), Depends(atlas_dormant_guard)],
)
def update_forward_thesis_status_endpoint(
    forward_thesis_id: int,
    request: ForwardThesisStatusRequest,
    db: Session = Depends(get_db),
):
    """Transition a forward thesis to a new status. Returns 503 if forward_thesis_enabled=False."""
    from backend.config import settings
    if not settings.forward_thesis_enabled:
        raise HTTPException(503, "forward_thesis feature is disabled")
    from backend.research.forward_thesis import update_forward_thesis_status
    try:
        result = update_forward_thesis_status(
            db, forward_thesis_id, request.new_status, note=request.note
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e
    if not result:
        raise HTTPException(503, "forward_thesis feature is disabled")
    return result


@router.post(
    "/research/forward-theses/{forward_thesis_id}/confidence-band",
    response_model=ForwardThesisOut,
    dependencies=[Depends(agent_write_guard("research.forward_thesis.update_confidence")), Depends(atlas_dormant_guard)],
)
def update_forward_thesis_confidence(
    forward_thesis_id: int,
    request: ForwardThesisConfidenceRequest,
    db: Session = Depends(get_db),
):
    """Update the confidence band of a forward thesis. Returns 503 if forward_thesis_enabled=False."""
    from backend.config import settings
    if not settings.forward_thesis_enabled:
        raise HTTPException(503, "forward_thesis feature is disabled")
    from backend.research.forward_thesis import update_confidence_band
    try:
        result = update_confidence_band(
            db,
            forward_thesis_id,
            confidence_low=request.confidence_low,
            confidence_high=request.confidence_high,
            as_of=request.as_of,
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e
    if not result:
        raise HTTPException(503, "forward_thesis feature is disabled")
    return result


@router.post(
    "/research/forward-theses/{forward_thesis_id}/evidence",
    response_model=ForwardThesisOut,
    dependencies=[Depends(agent_write_guard("research.forward_thesis.attach_evidence")), Depends(atlas_dormant_guard)],
)
def attach_forward_thesis_evidence(
    forward_thesis_id: int,
    request: ForwardThesisEvidenceRequest,
    db: Session = Depends(get_db),
):
    """Attach an evidence manifest to a forward thesis. Returns 503 if forward_thesis_enabled=False."""
    from backend.config import settings
    if not settings.forward_thesis_enabled:
        raise HTTPException(503, "forward_thesis feature is disabled")
    from backend.research.forward_thesis import attach_evidence_manifest
    try:
        result = attach_evidence_manifest(
            db, forward_thesis_id, manifest=request.manifest, as_of=request.as_of
        )
    except ValueError as e:
        detail = str(e)
        if "not found" in detail:
            raise HTTPException(404, detail) from e
        raise HTTPException(400, detail) from e
    if not result:
        raise HTTPException(503, "forward_thesis feature is disabled")
    return result


# ── M40 Case View route ───────────────────────────────────────────────────────

@router.get(
    "/research/{symbol}/case-view",
    response_model=CaseViewOut,
    dependencies=[Depends(atlas_dormant_guard)],
)
def get_symbol_case_view(
    symbol: str,
    include_dossier: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Return the unified per-symbol cross-module case view (read-only).

    Aggregates M35-M39 records for the symbol without altering /dossier contract.
    Set ?include_dossier=false to skip the dossier sub-call when already cached.
    """
    from backend.research.case_view import build_case_view
    from backend.research.dossier import build_research_dossier

    dossier = build_research_dossier(db, symbol) if include_dossier else {
        "symbol": symbol, "stock": None, "latest_signal": None,
        "long_term_label": None, "research_state": {
            "symbol": symbol, "thesis": "", "risks": [],
            "open_questions": [], "copilot": None,
            "last_signal_summary": "", "last_review": None, "updated_at": None,
        },
        "evidence": [], "stock_memory": [], "deep_research": [],
        "pending_questions": [], "conflicts": [], "official_action": {},
        "missing": [], "case": None,
    }
    case_view = build_case_view(db, symbol)
    return {"symbol": symbol, "dossier": dossier, "case_view": case_view}


# NOTE: this catch-all single-segment route MUST stay registered LAST — after the
# static /research/<name> routes (themes, memory-candidates, universe-snapshots).
# FastAPI matches routes in declaration order, so if this were defined earlier it
# would shadow those static routes (treating e.g. "themes" as a {symbol}).
@router.get("/research/{symbol}", response_model=ResearchStateOut)
def get_symbol_research_state(symbol: str, db: Session = Depends(get_db)):
    """Return the persistent research state for a symbol."""
    from backend.decision.harness import get_research_state

    return get_research_state(db, symbol)
