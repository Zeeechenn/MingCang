"""FastAPI dependency providers for the MingCang backend.

These callables are designed to be passed to ``fastapi.Depends()`` so that
route handlers receive configured objects through FastAPI's DI system rather
than importing module-level globals directly.  This makes routes easier to
test (swap providers via ``app.dependency_overrides``) and keeps the seam
explicit.

Usage example::

    from fastapi import Depends
    from backend.api.deps import get_settings
    from backend.config import Settings

    @router.get("/foo")
    def my_route(settings: Settings = Depends(get_settings)):
        return {"db": settings.database_url}
"""
from __future__ import annotations

from backend.config import Settings, settings as _settings


def get_settings() -> Settings:
    """Return the process-wide Settings singleton.

    Expose the global settings object via FastAPI's Depends mechanism so
    individual route handlers do not need to import it directly.  Tests can
    override this with ``app.dependency_overrides[get_settings] = lambda: my_test_settings``.
    """
    return _settings
