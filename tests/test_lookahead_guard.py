import sqlite3

from backend.evidence import lookahead
from backend.evidence.lookahead import LOOKAHEAD_CHECK_SCHEMA


def test_readonly_sqlite_url_preserves_urls_that_already_request_read_only_or_uri():
    mode_ro_url = "sqlite:///file:/tmp/mingcang.db?mode=ro&immutable=1&uri=true"
    uri_true_url = "sqlite:///file:/tmp/mingcang.db?uri=true"

    assert lookahead._readonly_sqlite_url(mode_ro_url) == mode_ro_url
    assert lookahead._readonly_sqlite_url(uri_true_url) == uri_true_url


def test_readonly_sqlite_url_converts_plain_sqlite_file_url_to_read_only_uri():
    url = lookahead._readonly_sqlite_url("sqlite:///some/path.db")

    assert "file:" in url
    assert "mode=ro" in url
    assert "immutable=1" in url
    assert "uri=true" in url


def test_readonly_sqlite_url_preserves_non_sqlite_urls():
    assert lookahead._readonly_sqlite_url("postgresql://x") == "postgresql://x"


def test_run_lookahead_check_maps_blocked_status(monkeypatch):
    monkeypatch.setattr(
        lookahead,
        "build_audit",
        lambda db, *, as_of=None: {"status": "blocked", "schema_version": "audit.vX"},
    )

    result = lookahead.run_lookahead_check(db=object())

    assert result["ok"] is False
    assert any("Freeze" in action for action in result["recommended_next_actions"])
    assert result["promotion_impact"] == "none"
    assert result["read_contract"]["writes_db"] is False
    assert result["schema_version"] == LOOKAHEAD_CHECK_SCHEMA
    assert result["standing_check"] is True
    assert result["source_audit_schema_version"] == "audit.vX"


def test_run_lookahead_check_maps_warning_status(monkeypatch):
    monkeypatch.setattr(
        lookahead,
        "build_audit",
        lambda db, *, as_of=None: {"status": "warning", "schema_version": "audit.vX"},
    )

    result = lookahead.run_lookahead_check(db=object())

    assert result["ok"] is True
    assert any("Disclose" in action for action in result["recommended_next_actions"])
    assert result["read_contract"]["writes_db"] is False
    assert result["schema_version"] == LOOKAHEAD_CHECK_SCHEMA
    assert result["standing_check"] is True
    assert result["source_audit_schema_version"] == "audit.vX"


def test_run_lookahead_check_maps_ok_status(monkeypatch):
    monkeypatch.setattr(
        lookahead,
        "build_audit",
        lambda db, *, as_of=None: {"status": "ok", "schema_version": "audit.vX"},
    )

    result = lookahead.run_lookahead_check(db=object())

    assert result["ok"] is True
    assert any(
        "No lookahead blockers" in action
        for action in result["recommended_next_actions"]
    )
    assert result["read_contract"]["writes_db"] is False
    assert result["schema_version"] == LOOKAHEAD_CHECK_SCHEMA
    assert result["standing_check"] is True
    assert result["source_audit_schema_version"] == "audit.vX"


def test_run_lookahead_check_for_database_url_opens_sqlite_read_only(monkeypatch, tmp_path):
    db_path = tmp_path / "lookahead.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE sentinel (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO sentinel (id) VALUES (1)")

    monkeypatch.setattr(
        lookahead,
        "build_audit",
        lambda db, *, as_of=None: {"status": "ok", "schema_version": "audit.v1"},
    )

    result = lookahead.run_lookahead_check_for_database_url(
        database_url=f"sqlite:///{db_path}"
    )

    assert result["ok"] is True
    assert result["run_mode"] == "standing_read_only_check"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT id FROM sentinel").fetchone() == (1,)
