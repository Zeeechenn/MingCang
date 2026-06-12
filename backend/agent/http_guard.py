"""FastAPI dependencies for remote agent HTTP guardrails."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from backend.agent.security import AgentSecurityError, require_agent_access


def _api_key_from_request(request: Request) -> str | None:
    return (
        request.headers.get("x-mingcang-agent-api-key")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or None
    )


def _to_http_error(exc: AgentSecurityError) -> HTTPException:
    message = str(exc)
    status = 401 if "key" in message.lower() else 403
    return HTTPException(status_code=status, detail=message)


def agent_write_guard(action: str) -> Callable[[Request], None]:
    """Return a dependency that validates a remote write action."""
    def dependency(request: Request) -> None:
        try:
            require_agent_access(
                "write",
                api_key=_api_key_from_request(request),
                action=action,
            )
        except AgentSecurityError as exc:
            raise _to_http_error(exc) from exc

    return dependency


def require_http_agent_write(request: Request, action: str) -> None:
    """Validate a dynamic write action inside a route body."""
    require_http_agent_write_key(
        action,
        api_key=_api_key_from_request(request),
    )


def require_http_agent_write_key(
    action: str,
    *,
    api_key: str | None = None,
    authorization: str | None = None,
) -> None:
    """Validate a dynamic write action from explicit HTTP auth values."""
    effective_key = api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    try:
        require_agent_access(
            "write",
            api_key=effective_key,
            action=action,
        )
    except AgentSecurityError as exc:
        raise _to_http_error(exc) from exc
