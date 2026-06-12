"""Database seed/default data routines."""
from __future__ import annotations

import os


def _seed_default_memory() -> None:
    """M9.0/M9.1：种子默认 bias-override + 一次性迁移分层记忆文件入 DB。"""
    from backend.data import database
    from backend.decision.memory_layered import migrate_layered_files_to_db
    from backend.memory.bias_override import seed_default_overrides

    db = database.SessionLocal()
    try:
        seed_default_overrides(db)
        if _should_migrate_local_memory():
            migrate_layered_files_to_db(db)
    finally:
        db.close()


def _should_migrate_local_memory() -> bool:
    """Only ingest home-directory layered memory when explicitly requested."""
    flag = os.environ.get("MINGCANG_MIGRATE_LOCAL_MEMORY")
    if flag is not None:
        return flag.strip().lower() in {"1", "true", "yes"}
    return False


__all__ = ["_seed_default_memory", "_should_migrate_local_memory"]
