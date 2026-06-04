"""Runtime schema patches for SQLite deployments."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


def _ensure_runtime_schema(runtime_engine: Any | None = None) -> None:
    """SQLite create_all 不会补既有表字段，这里做轻量幂等迁移。"""
    if runtime_engine is None:
        from backend.data.database import engine

        runtime_engine = engine

    with runtime_engine.begin() as conn:
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


__all__ = ["_ensure_runtime_schema"]
