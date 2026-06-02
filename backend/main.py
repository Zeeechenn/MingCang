import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.data.database import init_db
from backend.scheduler import start as scheduler_start
from backend.scheduler import stop as scheduler_stop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: initialize DB and scheduler on startup, shut down on exit."""
    init_db()
    from backend.config import settings
    os.environ.setdefault("MPLCONFIGDIR", str(Path.home() / ".matplotlib"))
    logger.info("StockSage DB: %s", settings.database_url)
    if settings.scheduler_enabled:
        scheduler_start()
    yield
    if settings.scheduler_enabled:
        scheduler_stop()


app = FastAPI(title="StockSage API", version="0.2.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """Simple liveness check endpoint."""
    return {"status": "ok"}
