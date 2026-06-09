"""Request/run correlation helpers for MingCang observability."""
from __future__ import annotations

from uuid import uuid4

import structlog.contextvars

CORRELATION_ID_HEADER = "X-Correlation-ID"
_CONTEXT_KEY = "correlation_id"
_MAX_CORRELATION_ID_LENGTH = 128


def _clean_correlation_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_CORRELATION_ID_LENGTH]


def new_correlation_id() -> str:
    """Return a compact new correlation id for local request/run tracing."""
    return str(uuid4())


def bind_correlation_id(value: str | None = None) -> str:
    """Bind a correlation id into structlog contextvars and return it."""
    correlation_id = _clean_correlation_id(value) or new_correlation_id()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    return correlation_id


def get_correlation_id() -> str | None:
    """Return the currently bound correlation id, if any."""
    value = structlog.contextvars.get_contextvars().get(_CONTEXT_KEY)
    return str(value) if value else None


def clear_correlation_id() -> None:
    """Remove the bound correlation id from the current context."""
    structlog.contextvars.unbind_contextvars(_CONTEXT_KEY)


def correlation_headers() -> dict[str, str]:
    """Return HTTP headers that expose the active correlation id."""
    correlation_id = get_correlation_id()
    if not correlation_id:
        return {}
    return {CORRELATION_ID_HEADER: correlation_id}
