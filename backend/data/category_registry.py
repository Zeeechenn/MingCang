"""Generic category provider registry for M61 data categories."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from time import time

from backend.data.degradation import emit_degradation
from backend.data.global_data import CANONICAL_SCHEMAS

logger = logging.getLogger(__name__)

CATEGORIES = frozenset({
    "quotes",
    "financials",
    "announcements",
    "research_reports",
    "fund_flow",
    "lhb",
    "corporate_events",
    "holders",
    "sector",
    "news",
    "f10",
    "overseas",
})

_CATEGORY_SCHEMA_KEYS: dict[str, str] = {
    "quotes": "quote",
    "financials": "fundamentals",
    "announcements": "filings",
    "fund_flow": "capital_flow",
}
_LOGGED_MISSING_SCHEMAS: set[str] = set()


@dataclass(frozen=True)
class FetchRequest:
    symbol: str | None
    start: date | None
    end: date | None
    limit: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CategoryProvider:
    name: str
    category: str
    fetch: Callable[[FetchRequest], list[dict]]
    probe: Callable[[], bool]
    priority: int = 100
    cooldown_seconds: int = 0
    observe_only: bool = False

    def __post_init__(self) -> None:
        if self.probe is None:
            raise TypeError("probe is required")


@dataclass
class FetchResult:
    ok: bool
    rows: list[dict]
    provider: str | None
    degradations: list[dict]


_CATEGORY_PROVIDERS: dict[str, list[CategoryProvider]] = {category: [] for category in CATEGORIES}
_PROVIDER_HEALTH: dict[str, dict] = {}


def _default_health() -> dict:
    return {"successes": 0, "failures": 0, "skipped": 0, "last_error": None, "cooldown_until": None}


def _provider_key(provider: CategoryProvider) -> str:
    return f"{provider.category}:{provider.name}"


def _health(provider: CategoryProvider) -> dict:
    return _PROVIDER_HEALTH.setdefault(_provider_key(provider), _default_health())


def _record_provider_success(provider: CategoryProvider) -> None:
    stats = _health(provider)
    stats["successes"] += 1
    stats["last_error"] = None
    stats["cooldown_until"] = None


def _record_provider_failure(provider: CategoryProvider, error: str) -> None:
    stats = _health(provider)
    stats["failures"] += 1
    stats["last_error"] = error
    if provider.cooldown_seconds > 0:
        stats["cooldown_until"] = time() + provider.cooldown_seconds


def _provider_in_cooldown(provider: CategoryProvider) -> bool:
    cooldown_until = _health(provider).get("cooldown_until")
    if cooldown_until is None:
        return False
    if float(cooldown_until) <= time():
        _health(provider)["cooldown_until"] = None
        return False
    _health(provider)["skipped"] += 1
    return True


def _degradation(provider: CategoryProvider, error: str, context: dict | None = None, db=None) -> dict:
    event = {
        "provider": provider.name,
        "category": provider.category,
        "error": str(error),
        "ts": time(),
    }
    if context:
        event.update(context)
    emit_degradation(
        "category_registry",
        provider.category,
        provider.name,
        str(error),
        context=context,
        db=db,
    )
    return event


def register_category_provider(provider: CategoryProvider) -> None:
    """Register or replace one category provider."""
    if provider.category not in CATEGORIES:
        raise ValueError(f"unknown category: {provider.category}")
    if provider.probe is None:
        raise TypeError("probe is required")
    providers = [p for p in _CATEGORY_PROVIDERS[provider.category] if p.name != provider.name]
    providers.append(provider)
    providers.sort(key=lambda p: p.priority)
    _CATEGORY_PROVIDERS[provider.category] = providers
    _health(provider)


def reset_category_registry() -> None:
    """Clear category providers and health for deterministic tests."""
    for category in CATEGORIES:
        _CATEGORY_PROVIDERS[category] = []
    _PROVIDER_HEALTH.clear()
    _LOGGED_MISSING_SCHEMAS.clear()


def _schema_for_category(category: str) -> dict | None:
    schema_key = _CATEGORY_SCHEMA_KEYS.get(category, category)
    schema = CANONICAL_SCHEMAS.get(schema_key)
    if schema is None and category not in _LOGGED_MISSING_SCHEMAS:
        logger.debug("no canonical schema for category=%s", category)
        _LOGGED_MISSING_SCHEMAS.add(category)
    return schema


def _row_satisfies_schema(row: dict, schema: dict) -> bool:
    required_fields = schema.get("required_fields") or []
    for field_name in required_fields:
        if field_name not in row:
            return False
    pit_date_field = schema.get("pit_date_field")
    if pit_date_field and not row.get(pit_date_field):
        return False
    return True


def _validate_contract(category: str, provider: CategoryProvider, rows: list[dict], db=None) -> tuple[list[dict], dict | None]:
    schema = _schema_for_category(category)
    if schema is None:
        return rows, None

    valid_rows = [row for row in rows if _row_satisfies_schema(row, schema)]
    dropped = len(rows) - len(valid_rows)
    if dropped == 0:
        return valid_rows, None

    event = _degradation(
        provider,
        "contract_violation",
        context={"dropped": dropped, "schema": _CATEGORY_SCHEMA_KEYS.get(category, category)},
        db=db,
    )
    return valid_rows, event


def fetch_by_category(category: str, request: FetchRequest, db=None) -> FetchResult:
    """Fetch rows from the first healthy provider for a category."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category: {category}")

    degradations: list[dict] = []
    for provider in _CATEGORY_PROVIDERS[category]:
        if provider.observe_only:
            _health(provider)["skipped"] += 1
            event = _degradation(provider, "observe_only", db=db)
            degradations.append(event)
            continue
        if _provider_in_cooldown(provider):
            event = _degradation(provider, "cooling", db=db)
            degradations.append(event)
            continue

        try:
            rows = provider.fetch(request)
            if not rows:
                _record_provider_failure(provider, "empty")
                degradations.append(_degradation(provider, "empty", db=db))
                continue

            valid_rows, contract_event = _validate_contract(category, provider, rows, db=db)
            if contract_event is not None:
                degradations.append(contract_event)
            if not valid_rows:
                _record_provider_failure(provider, "contract_violation")
                continue

            _record_provider_success(provider)
            return FetchResult(ok=True, rows=valid_rows, provider=provider.name, degradations=degradations)
        except Exception as exc:
            error = str(exc)
            _record_provider_failure(provider, error)
            degradations.append(_degradation(provider, error, db=db))
            continue

    return FetchResult(ok=False, rows=[], provider=None, degradations=degradations)


def list_capability_gaps() -> dict:
    """Return provider coverage for every M61 category."""
    return {
        category: {
            "providers": [provider.name for provider in _CATEGORY_PROVIDERS[category]],
            "has_provider": bool(_CATEGORY_PROVIDERS[category]),
        }
        for category in sorted(CATEGORIES)
    }
