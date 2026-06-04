from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _install_temp_session(monkeypatch, tmp_path):
    from backend.data import database

    engine = create_engine(f"sqlite:///{tmp_path / 'stocksage-test.db'}", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    return Session


def test_seed_default_memory_skips_home_migration_for_non_default_db(monkeypatch, tmp_path):
    from backend.data import database
    from backend.decision import memory_layered
    from backend.memory import bias_override

    _install_temp_session(monkeypatch, tmp_path)
    called = {"migrated": False}
    monkeypatch.delenv("STOCKSAGE_MIGRATE_LOCAL_MEMORY", raising=False)
    monkeypatch.setattr(database.settings, "database_url", f"sqlite:///{tmp_path / 'isolated.db'}")
    monkeypatch.setattr(bias_override, "seed_default_overrides", lambda db: None)
    monkeypatch.setattr(memory_layered, "migrate_layered_files_to_db", lambda db: called.update(migrated=True))

    database._seed_default_memory()

    assert called["migrated"] is False


def test_seed_default_memory_honors_explicit_migration_flag(monkeypatch, tmp_path):
    from backend.data import database
    from backend.decision import memory_layered
    from backend.memory import bias_override

    _install_temp_session(monkeypatch, tmp_path)
    called = {"migrated": False}
    monkeypatch.setenv("STOCKSAGE_MIGRATE_LOCAL_MEMORY", "1")
    monkeypatch.setattr(database.settings, "database_url", f"sqlite:///{tmp_path / 'isolated.db'}")
    monkeypatch.setattr(bias_override, "seed_default_overrides", lambda db: None)
    monkeypatch.setattr(memory_layered, "migrate_layered_files_to_db", lambda db: called.update(migrated=True))

    database._seed_default_memory()

    assert called["migrated"] is True


def test_should_not_migrate_local_memory_for_default_database_path_without_flag(monkeypatch):
    from backend.data import database

    monkeypatch.delenv("STOCKSAGE_MIGRATE_LOCAL_MEMORY", raising=False)
    monkeypatch.setattr(database.settings, "database_url", f"sqlite:///{database._DEFAULT_DB_PATH}")

    assert database._should_migrate_local_memory() is False


def test_runtime_schema_adds_l0_memory_tables_and_legacy_candidate_column(tmp_path):
    from backend.data.database import Base, _ensure_runtime_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE memory_atoms"))
        conn.execute(text("DROP TABLE memory_scenarios"))
        conn.execute(text("DROP TABLE memory_profiles"))
        conn.execute(text("DROP TABLE memory_promotion_candidates"))
        conn.execute(text("""
            CREATE TABLE memory_promotion_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_case_id INTEGER,
                stock_memory_item_id INTEGER,
                symbol TEXT,
                summary TEXT,
                memory_type TEXT,
                source_trust TEXT DEFAULT 'pending',
                source_ref TEXT,
                importance INTEGER DEFAULT 3,
                confidence REAL DEFAULT 0.5,
                promoted_at DATETIME,
                rejected_at DATETIME,
                note TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))

    _ensure_runtime_schema(engine)

    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )).fetchall()
        }
        assert {"memory_atoms", "memory_scenarios", "memory_profiles"} <= tables
        atom_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(memory_atoms)")).fetchall()
        }
        assert {
            "scope_type",
            "scope_key",
            "memory_type",
            "summary",
            "trust_state",
            "review_case_id",
            "stock_memory_item_id",
            "last_used_at",
        } <= atom_cols
        candidate_cols = {
            row[1]
            for row in conn.execute(text(
                "PRAGMA table_info(memory_promotion_candidates)"
            )).fetchall()
        }
        assert "memory_atom_id" in candidate_cols
        indexes = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list(memory_atoms)")).fetchall()
        }
        assert {
            "idx_memory_atoms_scope_trust",
            "idx_memory_atoms_source_ref",
            "idx_memory_atoms_review_case",
        } <= indexes
