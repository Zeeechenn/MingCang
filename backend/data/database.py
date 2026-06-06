"""Database facade — preserves the historic ``from backend.data.database import X``
import surface.

The engine / session / declarative ``Base`` now live in :mod:`backend.data.orm`
and the 31 ORM models in the :mod:`backend.data.models` package.  This module
re-exports them and owns runtime schema migration + ``init_db``.
"""
import re
from typing import Any, cast

from sqlalchemy import text

from backend.config import settings  # noqa: F401  re-exported for backward compatibility
from backend.data.orm import (  # noqa: F401  re-exported for backward compatibility
    Base,
    SessionLocal,
    _DEFAULT_DB_PATH,
    _utcnow,
    engine,
)
from backend.data.models import (  # noqa: F401  re-exported for backward compatibility
    ChatMessage,
    ChatSession,
    DecisionMemoryLayered,
    DecisionRun,
    FinancialMetric,
    ForwardThesis,
    GateBObservation,
    IndexPrice,
    LlmUsageLog,
    LongTermLabel,
    MarketSnapshot,
    MemoryAtom,
    MemoryProfile,
    MemoryPromotionCandidate,
    MemoryScenario,
    NewsItem,
    PendingAIAction,
    Position,
    Price,
    ResearchState,
    ReviewCase,
    ReviewRun,
    SentimentCache,
    Signal,
    Stock,
    StockMemoryItem,
    ThemeHypothesis,
    ThemeRecord,
    ThesisConfidenceEntry,
    ThesisRecord,
    UniverseSnapshot,
)


_FORWARD_THESES_LEGACY_UNIQUE_RE = re.compile(
    r"\bunique\s*\(\s*statement\s*,\s*horizon_date\s*\)"
)
_FORWARD_THESES_SYMBOL_UNIQUE_RE = re.compile(
    r"\bunique\s*\(\s*symbol\s*,\s*statement\s*,\s*horizon_date\s*\)"
)


def _quote_sqlite_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalise_sqlite_schema_sql(schema_sql: str | None) -> str:
    if not schema_sql:
        return ""
    unquoted = (
        schema_sql
        .replace('"', "")
        .replace("`", "")
        .replace("[", "")
        .replace("]", "")
        .lower()
    )
    return re.sub(r"\s+", " ", unquoted)


def _forward_theses_has_legacy_unique(create_sql: str | None) -> bool:
    normalised = _normalise_sqlite_schema_sql(create_sql)
    if not normalised:
        return False
    return (
        bool(_FORWARD_THESES_LEGACY_UNIQUE_RE.search(normalised))
        and not _FORWARD_THESES_SYMBOL_UNIQUE_RE.search(normalised)
    )


def _sqlite_column_definition_from_pragma(row: Any, create_sql: str) -> str:
    name = str(row[1])
    column_type = str(row[2] or "").strip()
    not_null = bool(row[3])
    default = row[4]
    primary_key_order = int(row[5] or 0)

    parts = [_quote_sqlite_identifier(name)]
    if column_type:
        parts.append(column_type)
    if primary_key_order:
        parts.append("PRIMARY KEY")
        if column_type.upper() == "INTEGER" and "autoincrement" in create_sql.lower():
            parts.append("AUTOINCREMENT")
    if not_null and not primary_key_order:
        parts.append("NOT NULL")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


def _migrate_forward_theses_legacy_unique(conn: Any) -> None:
    """Move old forward_theses unique key to include symbol without dropping data.

    This only fixes the non-NULL unique key shape. SQLite still permits multiple
    NULL horizon_date rows under UNIQUE constraints; create_forward_thesis keeps
    the explicit NULL-horizon lookup for application-level idempotency.
    """
    create_sql = conn.execute(text("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'forward_theses'
    """)).scalar()
    if not _forward_theses_has_legacy_unique(create_sql):
        return

    columns = conn.execute(text("PRAGMA table_info(forward_theses)")).fetchall()
    if not columns:
        return

    temp_table = "forward_theses__symbol_unique_migration"
    column_names = [str(row[1]) for row in columns]
    column_defs = [
        _sqlite_column_definition_from_pragma(row, str(create_sql or ""))
        for row in columns
    ]
    if "symbol" not in column_names:
        insert_at = column_names.index("id") + 1 if "id" in column_names else 0
        column_defs.insert(insert_at, f"{_quote_sqlite_identifier('symbol')} TEXT")

    column_defs.append(
        "CONSTRAINT uq_forward_theses_symbol_statement_horizon "
        'UNIQUE("symbol", "statement", "horizon_date")'
    )

    conn.execute(text(f"DROP TABLE IF EXISTS {_quote_sqlite_identifier(temp_table)}"))
    conn.execute(text(
        f"CREATE TABLE {_quote_sqlite_identifier(temp_table)} (\n"
        + ",\n".join(f"                {definition}" for definition in column_defs)
        + "\n            )"
    ))

    copy_cols = ", ".join(_quote_sqlite_identifier(name) for name in column_names)
    conn.execute(text(
        f"INSERT INTO {_quote_sqlite_identifier(temp_table)} ({copy_cols}) "
        f"SELECT {copy_cols} FROM {_quote_sqlite_identifier('forward_theses')}"
    ))
    conn.execute(text(f"DROP TABLE {_quote_sqlite_identifier('forward_theses')}"))
    conn.execute(text(
        f"ALTER TABLE {_quote_sqlite_identifier(temp_table)} "
        f"RENAME TO {_quote_sqlite_identifier('forward_theses')}"
    ))


def _forward_theses_normalized_duplicate_rows(conn: Any) -> list[Any]:
    return list(conn.execute(text("""
        SELECT
            CASE WHEN symbol IS NULL THEN 1 ELSE 0 END AS symbol_is_null,
            COALESCE(symbol, '') AS normalized_symbol,
            statement,
            CASE WHEN horizon_date IS NULL THEN 1 ELSE 0 END AS horizon_is_null,
            COALESCE(horizon_date, '') AS normalized_horizon,
            COUNT(*) AS n_rows,
            GROUP_CONCAT(id) AS ids
        FROM forward_theses
        GROUP BY
            CASE WHEN symbol IS NULL THEN 1 ELSE 0 END,
            COALESCE(symbol, ''),
            statement,
            CASE WHEN horizon_date IS NULL THEN 1 ELSE 0 END,
            COALESCE(horizon_date, '')
        HAVING COUNT(*) > 1
        ORDER BY n_rows DESC, statement
        LIMIT 10
    """)).fetchall())


def _ensure_forward_theses_normalized_unique_index(conn: Any) -> None:
    """Enforce forward thesis uniqueness even when symbol/horizon_date are NULL."""
    duplicate_rows = _forward_theses_normalized_duplicate_rows(conn)
    if duplicate_rows:
        examples = []
        for row in duplicate_rows:
            symbol = "<NULL>" if int(row[0]) else str(row[1])
            horizon = "<NULL>" if int(row[3]) else str(row[4])
            examples.append(
                f"(symbol={symbol}, statement={row[2]}, horizon_date={horizon}, ids={row[6]})"
            )
        raise RuntimeError(
            "forward_theses has duplicate normalized keys; merge or delete duplicates "
            "before runtime schema migration: " + "; ".join(examples)
        )

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forward_theses_symbol_statement_horizon_norm
        ON forward_theses (
            CASE WHEN symbol IS NULL THEN 1 ELSE 0 END,
            COALESCE(symbol, ''),
            statement,
            CASE WHEN horizon_date IS NULL THEN 1 ELSE 0 END,
            COALESCE(horizon_date, '')
        )
    """))


def get_latest_price_date(symbol: str, db) -> str | None:
    """返回该股最新一条价格记录的日期字符串，无数据时返回 None"""
    result = db.query(Price.date).filter(Price.symbol == symbol)\
               .order_by(Price.date.desc()).first()
    return result[0] if result else None


def _ensure_runtime_schema(runtime_engine: Any | None = None) -> None:
    """Compatibility wrapper for runtime schema patches."""
    from backend.data.schema_runtime import _ensure_runtime_schema as ensure_runtime_schema

    target_engine = runtime_engine or engine
    ensure_runtime_schema(target_engine)

    with target_engine.begin() as conn:
        theme_hypothesis_cols = [
            r[1] for r in conn.execute(text("PRAGMA table_info(theme_hypotheses)")).fetchall()
        ]
        if theme_hypothesis_cols and "ai_supply_chain_json" not in theme_hypothesis_cols:
            conn.execute(text("ALTER TABLE theme_hypotheses ADD COLUMN ai_supply_chain_json TEXT"))

        # M38 Dynamic Universe / Survivorship Guard
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS universe_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                universe_hash TEXT NOT NULL,
                cutoff_date TEXT NOT NULL,
                market_filter TEXT NOT NULL DEFAULT 'ALL',
                symbols_json TEXT NOT NULL,
                n_symbols INTEGER NOT NULL,
                provenance_completeness_json TEXT,
                context TEXT,
                created_at DATETIME,
                UNIQUE(cutoff_date, market_filter, universe_hash)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_universe_snapshots_hash
            ON universe_snapshots(universe_hash)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_universe_snapshots_cutoff_market
            ON universe_snapshots(cutoff_date, market_filter)
        """))

        # M39 Forward Thesis Beta
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS forward_theses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                statement TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                horizon_date TEXT,
                confidence_low REAL,
                confidence_high REAL,
                evidence_manifest_json TEXT,
                invalidation_conditions_json TEXT,
                follow_up_metrics_json TEXT,
                next_review_date TEXT,
                review_cadence_days INTEGER,
                thesis_id INTEGER,
                theme_hypothesis_id INTEGER,
                universe_snapshot_id INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(symbol, statement, horizon_date)
            )
        """))
        _migrate_forward_theses_legacy_unique(conn)
        _ensure_forward_theses_normalized_unique_index(conn)
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_forward_theses_symbol
            ON forward_theses(symbol)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_forward_theses_status
            ON forward_theses(status)
        """))

        # M40 Gate-B prospective tracker
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS gate_b_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                as_of TEXT NOT NULL,
                signal_id INTEGER,
                label_id INTEGER,
                gate_pass_full INTEGER NOT NULL,
                gate_pass_variant INTEGER NOT NULL,
                card_pass INTEGER NOT NULL,
                ready_variant INTEGER NOT NULL,
                recommendation TEXT,
                composite_score REAL,
                entry_close REAL,
                horizon_days INTEGER NOT NULL DEFAULT 5,
                forward_status TEXT NOT NULL DEFAULT 'pending',
                realized_at TEXT,
                forward_return_raw REAL,
                forward_return_net REAL,
                blockers_json TEXT,
                blockers_variant_json TEXT,
                checks_json TEXT,
                gate_b_tracker_version TEXT,
                recorded_at DATETIME,
                updated_at DATETIME,
                UNIQUE(signal_id, as_of)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gate_b_obs_symbol
            ON gate_b_observations(symbol)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gate_b_obs_signal_date
            ON gate_b_observations(signal_date)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_gate_b_obs_as_of
            ON gate_b_observations(as_of)
        """))


def _verify_schema_consistency() -> list[str]:
    """
    M21.4 schema 单一化：检查 ORM 模型列与 PRAGMA table_info 的差异，
    以日志警告形式暴露"meta vs PRAGMA diff"问题，不阻断启动。

    返回所有差异描述列表（空列表表示一致）。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    diffs: list[str] = []
    try:
        from sqlalchemy import inspect as _inspect
        inspector = _inspect(engine)
        for mapper in Base.registry.mappers:
            table = cast(Any, mapper.local_table)
            table_name = table.name
            try:
                pragma_cols = {r["name"] for r in inspector.get_columns(table_name)}
            except Exception:
                continue
            orm_cols = {c.name for c in table.columns}
            extra_in_pragma = pragma_cols - orm_cols
            missing_in_pragma = orm_cols - pragma_cols
            if extra_in_pragma:
                msg = f"[schema] {table_name}: PRAGMA 有但 ORM 无 → {extra_in_pragma}"
                _log.debug(msg)
                diffs.append(msg)
            if missing_in_pragma:
                msg = f"[schema] {table_name}: ORM 有但 PRAGMA 无 → {missing_in_pragma}"
                _log.warning(msg)
                diffs.append(msg)
    except Exception as e:
        diffs.append(f"[schema] consistency check 失败: {e}")
    return diffs


def init_db() -> None:
    """Create all ORM tables and apply runtime schema patches."""
    Base.metadata.create_all(engine)
    _ensure_runtime_schema()
    _verify_schema_consistency()
    _seed_default_memory()


def _seed_default_memory() -> None:
    """Compatibility wrapper for default seed routines."""
    from backend.data.seed import _seed_default_memory as seed_default_memory

    seed_default_memory()


def _should_migrate_local_memory() -> bool:
    """Compatibility wrapper for seed migration gating."""
    from backend.data.seed import _should_migrate_local_memory as should_migrate_local_memory

    return should_migrate_local_memory()


def get_db():
    """FastAPI dependency: yield a DB session and close it when done.

    Resolves ``SessionLocal`` from this module's namespace at call time so that
    tests may monkeypatch ``backend.data.database.SessionLocal``.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
