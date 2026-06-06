import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import settings
from backend.data.database import init_db
from backend.logging_config import configure_logging
from backend.scheduler import start as scheduler_start
from backend.scheduler import stop as scheduler_stop

# 模块级最早配置中心化结构化日志，确保在 app 创建及后续 import 前生效。
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


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
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """Simple liveness check endpoint."""
    return {"status": "ok"}
