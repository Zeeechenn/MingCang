"""Research state and deep-research routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.api.schemas import (
    DeepResearchRequest,
    DeepResearchResponse,
    ResearchDossierOut,
    ResearchStateOut,
    StressTestResponse,
)
from backend.data.database import get_db
from backend.llm import runtime_readiness

router = APIRouter()


@router.get("/research/{symbol}/dossier", response_model=ResearchDossierOut)
def get_symbol_research_dossier(symbol: str, db: Session = Depends(get_db)):
    """Return the unified research dossier for one symbol."""
    from backend.research.dossier import build_research_dossier

    return build_research_dossier(db, symbol)


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
    from backend.decision.market_policy import is_production_signal_market
    from backend.research.dossier import build_research_dossier

    if market not in ("CN", "HK", "US"):
        raise HTTPException(400, "market must be CN, HK, or US")

    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if stock is None:
        stock = Stock(
            symbol=symbol,
            name=name or symbol,
            market=market,
            active=is_production_signal_market(market),
        )
        db.add(stock)
    else:
        if is_production_signal_market(stock.market or market):
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

    if stock.market == "CN":
        try:
            from backend.data.fundamentals import sync_financial_metrics
            rows = sync_financial_metrics(symbol, db)
            steps["financials"] = {"ok": True, "rows": rows}
        except Exception as exc:
            steps["financials"] = {"ok": False, "error": str(exc)}

    dossier = build_research_dossier(db, symbol)
    return {
        "status": "prepared",
        "symbol": symbol,
        "signal_scope": "production" if is_production_signal_market(stock.market) else "observe_only",
        "steps": steps,
        "runtime_readiness": runtime_readiness(),
        "missing": dossier.get("missing", []),
        "dossier": dossier,
    }


@router.get("/research/{symbol}", response_model=ResearchStateOut)
def get_symbol_research_state(symbol: str, db: Session = Depends(get_db)):
    """Return the persistent research state for a symbol."""
    from backend.decision.harness import get_research_state

    return get_research_state(db, symbol)


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
    return DeepResearchResponse(
        topic=report.topic,
        symbols=report.symbols,
        as_of=report.as_of,
        summary=report.summary,
        report_path=str(report.path) if report.path else None,
        source_count=report.source_count,
        risk_flags=report.risk_flags,
        readiness={
            "llm": readiness,
            "search_configured": bool(readiness.get("search", {}).get("tavily") or readiness.get("search", {}).get("anspire")),
        },
    )


@router.post(
    "/research/{symbol}/stress-test",
    response_model=StressTestResponse,
    dependencies=[Depends(agent_write_guard("research.stress_test"))],
)
def run_stress_test_endpoint(symbol: str, db: Session = Depends(get_db)):
    """Run a single-pass red-team stress test against the ResearchCase. Advisory only.

    Builds the dossier and case envelope then calls run_stress_test; the result is
    never written to Signal, DecisionRun, or trusted ai_memory rows.
    In remote agent mode this is gated by the ``research.stress_test`` write action.
    """
    from backend.research.dossier import build_research_dossier
    from backend.research.case import build_case
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
