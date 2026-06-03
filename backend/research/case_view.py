"""
M40 Case View helper — pure read-only aggregation of per-symbol M35-M39 records.

Called only by GET /research/{symbol}/case-view.
No writes, no side-effects, no LLM calls.
"""
from __future__ import annotations

import datetime

from sqlalchemy.orm import Session


def build_case_view(
    db: Session,
    symbol: str,
    *,
    theses_limit: int = 20,
    review_cases_limit: int = 20,
    forward_theses_limit: int = 20,
) -> dict:
    """Aggregate M35-M39 records for a symbol into a CaseViewInner envelope.

    Returns a dict with keys:
      theses, review_cases, forward_theses, theme_hypotheses, generated_at

    Known gap: ForwardThesis.symbol is nullable; rows created without the symbol
    field will not appear in forward_theses — documented, not an error.

    Theme hypotheses: no direct symbol column exists; the function filters
    Python-side on beneficiary_tiers for mentions of the symbol. This is safe
    for small hypothesis tables and avoids SQLite JSON function portability issues.
    """
    from backend.research.forward_thesis import list_forward_theses
    from backend.research.review_loop import list_review_cases
    from backend.research.theme_hypothesis_engine import list_hypotheses
    from backend.research.thesis_ledger import list_theses

    theses = list_theses(db, symbol=symbol, limit=theses_limit)
    review_cases = list_review_cases(db, symbol=symbol, limit=review_cases_limit)
    forward_theses = list_forward_theses(db, symbol=symbol, limit=forward_theses_limit)

    # Theme hypotheses: filter Python-side on beneficiary_tiers for the quoted symbol
    all_hypotheses = list_hypotheses(db)
    theme_hypotheses = [
        h for h in all_hypotheses
        if _symbol_in_tiers(h.get("beneficiary_tiers", []), symbol)
    ]

    return {
        "theses": theses,
        "review_cases": review_cases,
        "forward_theses": forward_theses,
        "theme_hypotheses": theme_hypotheses,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _symbol_in_tiers(tiers: list, symbol: str) -> bool:
    """Return True if any tier entry has a 'symbol' key matching the given symbol."""
    if not tiers:
        return False
    for t in tiers:
        if isinstance(t, dict) and t.get("symbol") == symbol:
            return True
    return False
