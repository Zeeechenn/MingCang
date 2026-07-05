"""Request/run correlation helpers for MingCang observability.

structlog 为可选依赖:系统 Python(无 venv)缺 structlog 时退化到 stdlib
contextvars 实现,行为等价——修复小白测试发现的 CLI 路径硬崩溃
(agent cli action → api.routes.exports → 本模块,2026-07-05)。
"""
from __future__ import annotations

import contextvars
import logging
from types import ModuleType
from uuid import uuid4

_structlog_contextvars: ModuleType | None
try:  # pragma: no cover - exercised via tests that simulate absence
    import structlog.contextvars as _structlog_contextvars
except ImportError:  # 非致命:退化到 stdlib contextvars
    _structlog_contextvars = None
    logging.getLogger(__name__).debug(
        "structlog 不可用,observability 使用 stdlib contextvars 退化实现"
    )

CORRELATION_ID_HEADER = "X-Correlation-ID"
_CONTEXT_KEY = "correlation_id"
_MAX_CORRELATION_ID_LENGTH = 128

# stdlib 退化实现的存储(structlog 缺席时使用)
_FALLBACK_CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mingcang_correlation_id", default=None
)


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
    """Bind a correlation id into context (structlog or stdlib fallback) and return it."""
    correlation_id = _clean_correlation_id(value) or new_correlation_id()
    if _structlog_contextvars is not None:
        _structlog_contextvars.bind_contextvars(correlation_id=correlation_id)
    else:
        _FALLBACK_CORRELATION_ID.set(correlation_id)
    return correlation_id


def get_correlation_id() -> str | None:
    """Return the currently bound correlation id, if any."""
    if _structlog_contextvars is not None:
        value = _structlog_contextvars.get_contextvars().get(_CONTEXT_KEY)
    else:
        value = _FALLBACK_CORRELATION_ID.get()
    return str(value) if value else None


def clear_correlation_id() -> None:
    """Remove the bound correlation id from the current context."""
    if _structlog_contextvars is not None:
        _structlog_contextvars.unbind_contextvars(_CONTEXT_KEY)
    else:
        _FALLBACK_CORRELATION_ID.set(None)


def correlation_headers() -> dict[str, str]:
    """Return HTTP headers that expose the active correlation id."""
    correlation_id = get_correlation_id()
    if not correlation_id:
        return {}
    return {CORRELATION_ID_HEADER: correlation_id}
