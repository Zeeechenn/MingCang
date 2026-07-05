import os
import subprocess
import sys
from pathlib import Path


def test_settings_config_does_not_emit_pydantic_v1_config_warning():
    repo = Path(__file__).resolve().parents[1]
    script = """
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    import backend.config  # noqa: F401

messages = [str(w.message) for w in caught]
if any("class-based `config`" in message for message in messages):
    raise SystemExit("\\n".join(messages))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)

    subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_sqlite_path_from_url_resolves_local_database_paths(tmp_path):
    from backend.config import sqlite_path_from_url

    db_path = tmp_path / "mingcang.db"

    assert sqlite_path_from_url(f"sqlite:///{db_path}") == db_path
    assert sqlite_path_from_url("sqlite:///:memory:") is None
    assert sqlite_path_from_url("postgresql://localhost/mingcang") is None


def test_default_database_url_uses_mingcang_db_even_when_legacy_exists(monkeypatch, tmp_path):
    import backend.config as config

    mingcang_path = tmp_path / "mingcang.db"
    legacy_path = tmp_path / ("stock" + "-sage.db")
    legacy_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "_MINGCANG_DB_PATH", mingcang_path)

    assert config._default_database_url() == f"sqlite:///{mingcang_path}"


def test_local_agent_mode_rejects_non_local_cors_origin():
    import pytest

    from backend.config import Settings

    with pytest.raises(ValueError, match="mingcang_agent_mode=local"):
        Settings(
            mingcang_agent_mode="local",
            cors_origins="http://localhost:5173,https://example.com",
        )


def test_remote_agent_mode_allows_non_local_cors_origin():
    from backend.config import Settings

    settings = Settings(
        mingcang_agent_mode="remote",
        cors_origins="https://example.com",
    )

    assert settings.cors_origins_list == ["https://example.com"]
