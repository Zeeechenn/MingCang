"""FastAPI routes aggregated from per-domain submodules.

Each submodule owns its own ``APIRouter`` and is mounted here in
registration order. ``backend.main`` imports the aggregated ``router`` and
mounts it under ``/api`` exactly as before, so the external URL contract is
unchanged.

A handful of endpoint functions are re-exported at module level for tests
that call them directly (e.g. ``from backend.api.routes import
dashboard_summary``).
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.routes import (
    ai,
    dashboard,
    exports,
    m63,
    memory,
    model,
    news,
    positions,
    prices,
    research,
    reviews,
    signals,
    skills,
    stocks,
    system,
    watchlist,
)

router = APIRouter()

# Order matters within signals.py (latest before {symbol}); router-level
# include order between modules does not, since each module's paths are
# disjoint.
router.include_router(watchlist.router)
router.include_router(positions.router)
router.include_router(stocks.router)
router.include_router(signals.router)
router.include_router(prices.router)
router.include_router(model.router)
router.include_router(system.router)
router.include_router(dashboard.router)
router.include_router(news.router)
router.include_router(research.router)
router.include_router(reviews.router)
router.include_router(skills.router)
router.include_router(ai.router)
router.include_router(memory.router)
router.include_router(exports.router)
router.include_router(m63.router)


# Re-exports for tests that import endpoint functions directly.
dashboard_summary = dashboard.dashboard_summary
data_coverage = system.data_coverage
external_data_sources = system.external_data_sources
get_runtime_config = system.get_runtime_config
update_runtime_config = system.update_runtime_config
run_deep_research_endpoint = research.run_deep_research_endpoint
get_watch_events_endpoint = skills.get_watch_events_endpoint
run_daily_review_endpoint = skills.run_daily_review_endpoint
list_positions = positions.list_positions
create_position = positions.create_position
ensure_daily_review = reviews.ensure_daily_review
search_stocks = stocks.search_stocks
ai_chat = ai.chat
confirm_ai_action = ai.confirm_action

__all__ = [
    "router",
    "dashboard_summary",
    "data_coverage",
    "external_data_sources",
    "get_runtime_config",
    "update_runtime_config",
    "run_deep_research_endpoint",
    "get_watch_events_endpoint",
    "run_daily_review_endpoint",
    "list_positions",
    "create_position",
    "ensure_daily_review",
    "search_stocks",
    "ai_chat",
    "confirm_ai_action",
]
