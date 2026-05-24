from __future__ import annotations

from sqlalchemy import create_engine
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
