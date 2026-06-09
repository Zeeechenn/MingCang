import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import settings
from backend.data.database import init_db
from backend.logging_config import configure_logging
from backend.observability import (
    CORRELATION_ID_HEADER,
    bind_correlation_id,
    clear_correlation_id,
)
from backend.scheduler import start as scheduler_start
from backend.scheduler import stop as scheduler_stop

# 模块级最早配置中心化结构化日志，确保在 app 创建及后续 import 前生效。
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)
request_logger = structlog.get_logger("backend.request")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: initialize DB and scheduler on startup, shut down on exit."""
    init_db()
    from backend.config import settings
    os.environ.setdefault("MPLCONFIGDIR", str(Path.home() / ".matplotlib"))
    logger.info("MingCang DB: %s", settings.database_url)
    if settings.scheduler_enabled:
        scheduler_start()
    yield
    if settings.scheduler_enabled:
        scheduler_stop()


app = FastAPI(title="MingCang API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,   # env: CORS_ORIGINS（逗号分隔，默认 Vite dev server）
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[CORRELATION_ID_HEADER],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Bind a request correlation id into logs and echo it to callers."""
    correlation_id = bind_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    try:
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        request_logger.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
    except Exception:
        request_logger.exception(
            "http.request.failed",
            method=request.method,
            path=request.url.path,
        )
        raise
    finally:
        clear_correlation_id()

app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """Simple liveness check endpoint."""
    return {"status": "ok"}
