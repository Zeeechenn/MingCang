"""Alembic environment for MingCang.

Target metadata is ``backend.data.orm.Base.metadata`` (all 31 ORM models, which
register on it via the ``backend.data.models`` package).  The DB URL comes from
``backend.config.settings.database_url`` unless overridden by the standard
``-x dburl=...`` flag or the ``ALEMBIC_DB_URL`` env var — used to point at a
throwaway DB copy during verification so we never touch production in place.

``include_object`` restricts Alembic to tables Base knows about, so non-ORM
tables managed elsewhere (ai_memory, audit_log_fts*, sqlite_sequence) do not
show up as spurious autogenerate diffs.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import models package so every ORM model registers on Base.metadata.
from backend.config import settings
from backend.data import models as _models  # noqa: F401  (registers models on Base)
from backend.data.orm import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """DB URL precedence: -x dburl=... > ALEMBIC_DB_URL env > settings."""
    x_args = context.get_x_argument(as_dictionary=True)
    return x_args.get("dburl") or os.environ.get("ALEMBIC_DB_URL") or settings.database_url


_ORM_INDEX_NAMES = {
    ix.name for table in target_metadata.tables.values() for ix in table.indexes
}


def include_object(object_, name, type_, reflected, compare_to):
    """Only manage objects that belong to the ORM metadata.

    Tables not in Base.metadata (ai_memory, audit_log_fts*, sqlite_sequence) and
    runtime-only indexes created by ``_ensure_runtime_schema`` (the ``idx_*``
    family) are owned outside Alembic and must not be dropped by autogenerate.
    """
    if type_ == "table":
        return name in target_metadata.tables
    if type_ == "index":
        return name in _ORM_INDEX_NAMES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=False,  # SQLite type affinity makes TEXT/String comparison noisy
        render_as_batch=True,  # SQLite-safe ALTER via batch mode
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=False,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
