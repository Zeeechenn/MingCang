"""Runtime schema patches for SQLite deployments."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_columns(conn: Any, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _add_columns(conn: Any, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    if not existing:
        return
    for name, ddl_type in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def _primary_key_columns(conn: Any, table: str) -> list[str]:
    rows = conn.execute(text(f"PRAGMA table_info({_quote(table)})")).fetchall()
    return [str(row[1]) for row in sorted(rows, key=lambda row: int(row[5] or 0)) if row[5]]


def _unique_index_signatures(conn: Any, table: str) -> set[tuple[str, ...]]:
    signatures: set[tuple[str, ...]] = set()
    for row in conn.execute(text(f"PRAGMA index_list({_quote(table)})")).fetchall():
        if not bool(row[2]):
            continue
        name = str(row[1])
        columns = conn.execute(text(f"PRAGMA index_info({_quote(name)})")).fetchall()
        signatures.add(tuple(str(column[2]) for column in columns))
    return signatures


def _column_definition(row: Any, create_sql: str, *, primary_key: str | None) -> str:
    name = str(row[1])
    column_type = str(row[2] or "").strip()
    parts = [_quote(name)]
    if column_type:
        parts.append(column_type)
    if name == primary_key:
        parts.append("PRIMARY KEY")
        if column_type.upper() == "INTEGER" and "autoincrement" in create_sql.lower():
            parts.append("AUTOINCREMENT")
    elif bool(row[3]):
        parts.append("NOT NULL")
    if row[4] is not None:
        parts.append(f"DEFAULT {row[4]}")
    return " ".join(parts)


def _rebuild_table_with_primary_key(conn: Any, table: str, *, primary_key: str) -> None:
    """Rebuild one SQLite table while preserving data, explicit indexes and triggers."""
    create_sql = str(conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=:table"
    ), {"table": table}).scalar() or "")
    rows = conn.execute(text(f"PRAGMA table_info({_quote(table)})")).fetchall()
    if not rows:
        return
    indexes = [
        str(row[0])
        for row in conn.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name=:table AND sql IS NOT NULL"
        ), {"table": table}).fetchall()
        if row[0]
    ]
    triggers = [
        str(row[0])
        for row in conn.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name=:table AND sql IS NOT NULL"
        ), {"table": table}).fetchall()
        if row[0]
    ]
    temp = f"{table}__m67_asset_key"
    conn.execute(text(f"DROP TABLE IF EXISTS {_quote(temp)}"))
    definitions = [
        _column_definition(row, create_sql, primary_key=primary_key)
        for row in rows
    ]
    conn.execute(text(
        f"CREATE TABLE {_quote(temp)} (" + ", ".join(definitions) + ")"
    ))
    columns = ", ".join(_quote(str(row[1])) for row in rows)
    conn.execute(text(
        f"INSERT INTO {_quote(temp)} ({columns}) SELECT {columns} FROM {_quote(table)}"
    ))
    conn.execute(text(f"DROP TABLE {_quote(table)}"))
    conn.execute(text(f"ALTER TABLE {_quote(temp)} RENAME TO {_quote(table)}"))
    for ddl in indexes:
        conn.execute(text(ddl))
    for ddl in triggers:
        conn.execute(text(ddl))


def _ensure_market_scoped_uniqueness(conn: Any) -> None:
    """Replace legacy symbol-only keys with canonical market-scoped keys."""
    if _table_columns(conn, "stocks") and _primary_key_columns(conn, "stocks") != ["asset_key"]:
        _rebuild_table_with_primary_key(conn, "stocks", primary_key="asset_key")

    contracts = {
        "prices": (("symbol", "date"), ("asset_key", "date"), "uq_prices_asset_date"),
        "market_snapshots": (("symbol", "date"), ("asset_key", "date"), "uq_ms_asset_date"),
        "financial_metrics": (
            ("symbol", "report_date"),
            ("asset_key", "report_date"),
            "uq_fm_asset_date",
        ),
        "long_term_labels": (("symbol", "date"), ("asset_key", "date"), "uq_ltl_asset_date"),
    }
    for table, (legacy, desired, index_name) in contracts.items():
        if not _table_columns(conn, table):
            continue
        signatures = _unique_index_signatures(conn, table)
        if legacy in signatures and desired not in signatures:
            primary_key = _primary_key_columns(conn, table)
            if len(primary_key) != 1:
                raise RuntimeError(f"cannot migrate {table}: expected one primary key")
            _rebuild_table_with_primary_key(conn, table, primary_key=primary_key[0])
        if desired not in _unique_index_signatures(conn, table):
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_quote(index_name)} "
                f"ON {_quote(table)} ({', '.join(_quote(column) for column in desired)})"
            ))

    if _table_columns(conn, "signals"):
        if ("asset_key", "date") not in _unique_index_signatures(conn, "signals"):
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_asset_date "
                "ON signals(asset_key, date)"
            ))


def _ensure_market_identity_schema(conn: Any) -> None:
    """Add and backfill M67 market-scoped identity without breaking legacy symbol APIs."""
    table_columns = {
        "stocks": {
            "asset_key": "TEXT",
            "exchange": "TEXT",
            "currency": "TEXT",
            "timezone": "TEXT",
            "lot_size": "INTEGER",
        },
        "positions": {"asset_key": "TEXT", "currency": "TEXT"},
        "prices": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'", "currency": "TEXT"},
        "news": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'"},
        "index_prices": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'", "currency": "TEXT"},
        "market_snapshots": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'", "currency": "TEXT"},
        "financial_metrics": {
            "asset_key": "TEXT",
            "market": "TEXT DEFAULT 'CN'",
            "currency": "TEXT",
            "source": "TEXT",
        },
        "signals": {
            "asset_key": "TEXT",
            "market": "TEXT DEFAULT 'CN'",
            "signal_scope": "TEXT DEFAULT 'production'",
        },
        "long_term_labels": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'"},
        "announcements": {"asset_key": "TEXT", "market": "TEXT DEFAULT 'CN'", "currency": "TEXT"},
    }
    for table, columns in table_columns.items():
        _add_columns(conn, table, columns)

    for table in table_columns:
        existing_columns = _table_columns(conn, table)
        if not {"market", "symbol"} <= existing_columns:
            continue
        conn.execute(text(f"UPDATE {table} SET market='CN' WHERE market IS NULL OR market=''"))
        if "asset_key" in existing_columns:
            conn.execute(text(
                f"UPDATE {table} SET asset_key=UPPER(market) || ':' || UPPER(symbol) "
                "WHERE symbol IS NOT NULL AND symbol != '' AND (asset_key IS NULL OR asset_key='')"
            ))
        if "currency" in existing_columns:
            conn.execute(text(
                f"UPDATE {table} SET currency=CASE UPPER(market) "
                "WHEN 'HK' THEN 'HKD' WHEN 'US' THEN 'USD' ELSE 'CNY' END "
                "WHERE currency IS NULL OR currency=''"
            ))

    if _table_columns(conn, "stocks"):
        conn.execute(text("UPDATE stocks SET asset_key=UPPER(COALESCE(market,'CN')) || ':' || UPPER(symbol) WHERE asset_key IS NULL OR asset_key=''"))
        conn.execute(text("UPDATE stocks SET currency=CASE UPPER(COALESCE(market,'CN')) WHEN 'HK' THEN 'HKD' WHEN 'US' THEN 'USD' ELSE 'CNY' END WHERE currency IS NULL OR currency=''"))
        conn.execute(text("UPDATE stocks SET timezone=CASE UPPER(COALESCE(market,'CN')) WHEN 'HK' THEN 'Asia/Hong_Kong' WHEN 'US' THEN 'America/New_York' ELSE 'Asia/Shanghai' END WHERE timezone IS NULL OR timezone=''"))
        conn.execute(text("UPDATE stocks SET exchange=CASE UPPER(COALESCE(market,'CN')) WHEN 'HK' THEN 'HKEX' WHEN 'US' THEN 'NYSE/Nasdaq' ELSE 'SSE/SZSE/BSE' END WHERE exchange IS NULL OR exchange=''"))
        conn.execute(text("UPDATE stocks SET lot_size=100 WHERE UPPER(COALESCE(market,'CN'))='CN' AND lot_size IS NULL"))
        conn.execute(text("UPDATE stocks SET lot_size=1 WHERE UPPER(COALESCE(market,'CN'))='US' AND lot_size IS NULL"))

    for table in table_columns:
        existing_columns = _table_columns(conn, table)
        if "asset_key" in existing_columns:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_asset_key ON {table}(asset_key)"))
        if "market" in existing_columns:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{table}_market ON {table}(market)"))

    _ensure_market_scoped_uniqueness(conn)


def _ensure_memory_recall_schema(runtime_engine: Any) -> None:
    """Create the unified memory recall index and FTS5 table."""
    with runtime_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_recall_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                symbol TEXT,
                subject TEXT,
                title TEXT,
                body TEXT NOT NULL,
                tags TEXT,
                as_of TEXT,
                event_time TEXT,
                ingestion_time TEXT,
                invalidated_at TEXT,
                supports_as_of INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                UNIQUE(source, source_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_recall_index_filters
            ON memory_recall_index(namespace, symbol, supports_as_of)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_recall_index_time
            ON memory_recall_index(ingestion_time, invalidated_at, updated_at)
        """))
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_recall_fts USING fts5(
                title,
                body,
                namespace,
                symbol,
                tags,
                content='memory_recall_index',
                content_rowid='id'
            )
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS memory_recall_index_ai
            AFTER INSERT ON memory_recall_index BEGIN
                INSERT INTO memory_recall_fts(rowid, title, body, namespace, symbol, tags)
                VALUES (new.id, new.title, new.body, new.namespace, new.symbol, new.tags);
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS memory_recall_index_ad
            AFTER DELETE ON memory_recall_index BEGIN
                INSERT INTO memory_recall_fts(
                    memory_recall_fts, rowid, title, body, namespace, symbol, tags
                )
                VALUES (
                    'delete', old.id, old.title, old.body, old.namespace, old.symbol, old.tags
                );
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS memory_recall_index_au
            AFTER UPDATE ON memory_recall_index BEGIN
                INSERT INTO memory_recall_fts(
                    memory_recall_fts, rowid, title, body, namespace, symbol, tags
                )
                VALUES (
                    'delete', old.id, old.title, old.body, old.namespace, old.symbol, old.tags
                );
                INSERT INTO memory_recall_fts(rowid, title, body, namespace, symbol, tags)
                VALUES (new.id, new.title, new.body, new.namespace, new.symbol, new.tags);
            END
        """))


def _ensure_runtime_schema(runtime_engine: Any | None = None) -> None:
    """SQLite create_all 不会补既有表字段，这里做轻量幂等迁移。"""
    if runtime_engine is None:
        from backend.data.database import engine

        runtime_engine = engine

    _ensure_memory_recall_schema(runtime_engine)

    with runtime_engine.begin() as conn:
        _ensure_market_identity_schema(conn)
        price_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(prices)")).fetchall()]
        for col, ddl in {
            "source": "ALTER TABLE prices ADD COLUMN source TEXT",
            "fetched_at": "ALTER TABLE prices ADD COLUMN fetched_at DATETIME",
            "adjustment": "ALTER TABLE prices ADD COLUMN adjustment TEXT",
        }.items():
            if price_cols and col not in price_cols:
                conn.execute(text(ddl))

        index_price_cols = [
            r[1] for r in conn.execute(text("PRAGMA table_info(index_prices)")).fetchall()
        ]
        for col, ddl in {
            "source": "ALTER TABLE index_prices ADD COLUMN source TEXT",
            "fetched_at": "ALTER TABLE index_prices ADD COLUMN fetched_at DATETIME",
            "adjustment": "ALTER TABLE index_prices ADD COLUMN adjustment TEXT",
        }.items():
            if index_price_cols and col not in index_price_cols:
                conn.execute(text(ddl))

        news_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(news)")).fetchall()]
        for col, ddl in {
            "content": "ALTER TABLE news ADD COLUMN content TEXT",
            "provider": "ALTER TABLE news ADD COLUMN provider TEXT",
        }.items():
            if news_cols and col not in news_cols:
                conn.execute(text(ddl))

        signal_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(signals)")).fetchall()]
        if "rule_version" not in signal_cols:
            conn.execute(text("ALTER TABLE signals ADD COLUMN rule_version TEXT"))
        if "data_timestamp" not in signal_cols:
            conn.execute(text("ALTER TABLE signals ADD COLUMN data_timestamp TEXT"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sentiment_cache (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT,
                titles_hash TEXT,
                result_json TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_sentiment_cache_symbol_hash
            ON sentiment_cache(symbol, titles_hash)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS m59_discretion_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                symbol TEXT NOT NULL,
                slot TEXT NOT NULL,
                card_json TEXT NOT NULL,
                inputs_digest TEXT NOT NULL,
                provider TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(as_of, symbol, slot)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_m59_discretion_cards_as_of
            ON m59_discretion_cards(as_of)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_m59_discretion_cards_symbol
            ON m59_discretion_cards(symbol)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_temperature_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snap_date DATETIME NOT NULL,
                pool_type TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                price REAL,
                fields_json TEXT NOT NULL,
                fetched_at DATETIME,
                UNIQUE(snap_date, pool_type, code)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_market_temperature_snapshots_date
            ON market_temperature_snapshots(snap_date)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_market_temperature_snapshots_pool_code
            ON market_temperature_snapshots(pool_type, code)
        """))

        position_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(positions)")).fetchall()]
        for col, ddl in {
            "closed_at": "ALTER TABLE positions ADD COLUMN closed_at TEXT",
            "close_price": "ALTER TABLE positions ADD COLUMN close_price REAL",
            "realized_pnl": "ALTER TABLE positions ADD COLUMN realized_pnl REAL",
            "realized_pnl_pct": "ALTER TABLE positions ADD COLUMN realized_pnl_pct REAL",
        }.items():
            if col not in position_cols:
                conn.execute(text(ddl))

        fm_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(financial_metrics)")).fetchall()]
        if "disclosure_date" not in fm_cols:
            conn.execute(text("ALTER TABLE financial_metrics ADD COLUMN disclosure_date TEXT"))

        ltl_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(long_term_labels)")).fetchall()]
        if ltl_cols:
            if "quality" not in ltl_cols:
                conn.execute(text("ALTER TABLE long_term_labels ADD COLUMN quality TEXT DEFAULT 'degraded'"))
            if "constraint_eligible" not in ltl_cols:
                conn.execute(text("ALTER TABLE long_term_labels ADD COLUMN constraint_eligible BOOLEAN DEFAULT 0"))
            if "quality_notes_json" not in ltl_cols:
                conn.execute(text("ALTER TABLE long_term_labels ADD COLUMN quality_notes_json TEXT"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT,
                scope TEXT DEFAULT 'global',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(key, scope)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ai_memory_scope_cat
            ON ai_memory(scope, category)
        """))
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS audit_log_fts USING fts5(
                timestamp, event_type, content, related_symbol, related_scope
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                memory_type TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                ttl_days INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                last_used_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_symbol_type
            ON stock_memory_items(symbol, memory_type)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_stock_memory_status_updated
            ON stock_memory_items(status, updated_at)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_atoms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT,
                scope_key TEXT,
                memory_type TEXT,
                summary TEXT NOT NULL,
                evidence_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                trust_state TEXT DEFAULT 'raw',
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                valid_from TEXT,
                valid_to TEXT,
                ttl_days INTEGER,
                review_case_id INTEGER,
                stock_memory_item_id INTEGER,
                promoted_by TEXT,
                refuted_by TEXT,
                refutation_reason TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                last_used_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_scope_trust
            ON memory_atoms(scope_type, scope_key, trust_state)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_source_ref
            ON memory_atoms(source_ref)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_atoms_review_case
            ON memory_atoms(review_case_id)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_type TEXT,
                scope_key TEXT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                atom_ids_json TEXT,
                trust_state TEXT DEFAULT 'pending',
                source_type TEXT DEFAULT 'manual',
                source_ref TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_scenarios_scope_trust
            ON memory_scenarios(scope_type, scope_key, trust_state)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_type TEXT,
                profile_key TEXT,
                summary TEXT NOT NULL,
                atom_ids_json TEXT,
                trust_state TEXT DEFAULT 'pending',
                source_type TEXT DEFAULT 'manual',
                source_ref TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_memory_profiles_type_trust
            ON memory_profiles(profile_type, profile_key, trust_state)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS evolution_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_type TEXT NOT NULL,
                namespace TEXT NOT NULL,
                subject TEXT,
                symbols_json TEXT,
                themes_json TEXT,
                content TEXT NOT NULL,
                payload_json TEXT,
                source_type TEXT,
                source_ref TEXT,
                as_of TEXT,
                stale_after TEXT,
                event_time TEXT NOT NULL,
                ingestion_time TEXT NOT NULL,
                invalidated_at TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_namespace_as_of
            ON evolution_traces(namespace, as_of)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_type_ingestion
            ON evolution_traces(trace_type, ingestion_time)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_evolution_traces_invalidated
            ON evolution_traces(invalidated_at)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_capsules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capsule_id TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL,
                user_id TEXT DEFAULT 'owner',
                symbols_json TEXT NOT NULL,
                themes_json TEXT NOT NULL,
                goal TEXT NOT NULL,
                confirmed_facts TEXT,
                decisions TEXT,
                open_loops TEXT,
                next_actions TEXT,
                used_memory_refs TEXT,
                artifact_refs TEXT,
                trust_state TEXT DEFAULT 'draft',
                token_estimate INTEGER NOT NULL,
                as_of TEXT,
                event_time TEXT NOT NULL,
                ingestion_time TEXT NOT NULL,
                invalidated_at TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_task_capsules_user_created
            ON task_capsules(user_id, created_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_task_capsules_as_of
            ON task_capsules(as_of)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS decision_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                run_type TEXT,
                symbol TEXT,
                as_of TEXT,
                profile TEXT,
                rule_version TEXT,
                recommendation TEXT,
                composite_score REAL,
                input_snapshot_json TEXT,
                agent_outputs_json TEXT,
                risk_decision_json TEXT,
                final_action_json TEXT,
                eval_result_json TEXT,
                notes TEXT,
                created_at DATETIME,
                UNIQUE(run_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_decision_runs_symbol_as_of
            ON decision_runs(symbol, as_of)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS research_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE,
                thesis TEXT,
                risks_json TEXT,
                open_questions_json TEXT,
                copilot_json TEXT,
                last_signal_summary TEXT,
                last_review_json TEXT,
                updated_at DATETIME,
                created_at DATETIME
            )
        """))
        research_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(research_states)")).fetchall()]
        if "copilot_json" not in research_cols:
            conn.execute(text("ALTER TABLE research_states ADD COLUMN copilot_json TEXT"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                date TEXT,
                market_cap REAL,
                float_market_cap REAL,
                shares_outstanding REAL,
                north_net_buy REAL,
                margin_balance REAL,
                large_order_net_inflow REAL,
                source TEXT,
                fetched_at DATETIME,
                UNIQUE(symbol, date)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_date
            ON market_snapshots(symbol, date)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                name TEXT,
                market TEXT DEFAULT 'CN',
                quantity REAL,
                avg_cost REAL,
                opened_at TEXT,
                stop_loss REAL,
                take_profit REAL,
                closed_at TEXT,
                close_price REAL,
                realized_pnl REAL,
                realized_pnl_pct REAL,
                note TEXT,
                status TEXT DEFAULT 'open',
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_positions_symbol_status
            ON positions(symbol, status)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS review_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT,
                as_of TEXT,
                summary TEXT,
                path TEXT,
                status TEXT DEFAULT 'created',
                payload_json TEXT,
                created_at DATETIME,
                UNIQUE(kind, as_of)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_review_runs_kind_as_of
            ON review_runs(kind, as_of)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pending_ai_actions (
                action_id TEXT PRIMARY KEY,
                action TEXT,
                payload_json TEXT,
                status TEXT DEFAULT 'pending',
                result_json TEXT,
                user_message TEXT,
                created_at DATETIME,
                executed_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                mode TEXT DEFAULT 'general',
                archived_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        chat_session_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(chat_sessions)")).fetchall()]
        if "archived_at" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN archived_at DATETIME"))
        if "summary" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN summary TEXT"))
        if "summary_until_id" not in chat_session_cols:
            conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN summary_until_id INTEGER"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                payload_json TEXT,
                created_at DATETIME
            )
        """))
        candidate_cols = [
            r[1] for r in conn.execute(
                text("PRAGMA table_info(memory_promotion_candidates)")
            ).fetchall()
        ]
        if candidate_cols and "memory_atom_id" not in candidate_cols:
            conn.execute(text(
                "ALTER TABLE memory_promotion_candidates ADD COLUMN memory_atom_id INTEGER"
            ))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
            ON chat_messages(session_id, created_at)
        """))


__all__ = ["_ensure_runtime_schema", "_ensure_memory_recall_schema"]
