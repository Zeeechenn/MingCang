"""Research state and deep-research routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.api.schemas import (
    DeepResearchRequest,
    DeepResearchResponse,
    ResearchStateOut,
)
from backend.data.database import get_db

router = APIRouter()


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
        persist=True,
    )
    return DeepResearchResponse(
        topic=report.topic,
        symbols=report.symbols,
        as_of=report.as_of,
        summary=report.summary,
        report_path=str(report.path) if report.path else None,
        source_count=report.source_count,
        risk_flags=report.risk_flags,
    )
