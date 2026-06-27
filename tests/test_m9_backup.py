"""M9.横向 每日备份：dump_ai_memory + cleanup_old_backups + run_daily_backup."""
from __future__ import annotations

import json
from datetime import datetime, timedelta


def test_dump_ai_memory_writes_all_rows(test_db, tmp_path):
    from backend.memory.ai_memory import remember
    from backend.memory.backup import dump_ai_memory

    remember(test_db, "rule:test1", "测试1 规则", category="rule", scope="test1")
    remember(test_db, "position:300308", "已买入 5%", category="position", scope="test1")

    out = tmp_path / "ai_memory_2026-05-19.json"
    written = dump_ai_memory(test_db, out)

    assert written == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    keys = {r["key"] for r in payload["rows"]}
    assert keys == {"rule:test1", "position:300308"}


def test_dump_ai_memory_includes_expired_rows(test_db, tmp_path):
    """Backups intentionally include expired rows so deletes are recoverable."""
    from sqlalchemy import text

    from backend.memory.ai_memory import remember
    from backend.memory.backup import dump_ai_memory

    remember(test_db, "risk:old", "过期风险", category="risk", ttl_days=1)
    old = (datetime.utcnow() - timedelta(days=10)).isoformat(timespec="seconds")
    test_db.execute(text("UPDATE ai_memory SET updated_at = :old WHERE key='risk:old'"),
                    {"old": old})
    test_db.commit()

    out = tmp_path / "ai_memory_2026-05-19.json"
    dump_ai_memory(test_db, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert any(r["key"] == "risk:old" for r in payload["rows"])


def test_cleanup_old_backups_removes_files_past_keep_days(tmp_path):
    """Old files (by filename date) are removed; recent ones survive."""
    from backend.memory.backup import cleanup_old_backups

    fresh_date = datetime.utcnow().strftime("%Y-%m-%d")
    old_date = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%d")
    (tmp_path / f"ai_memory_{fresh_date}.json").write_text("{}")
    (tmp_path / f"ai_memory_{old_date}.json").write_text("{}")
    (tmp_path / "irrelevant.txt").write_text("ignore me")

    removed = cleanup_old_backups(tmp_path, keep_days=30)

    assert removed == 1
    surviving = sorted(p.name for p in tmp_path.iterdir())
    assert f"ai_memory_{fresh_date}.json" in surviving
    assert "irrelevant.txt" in surviving
    assert f"ai_memory_{old_date}.json" not in surviving


def test_cleanup_skips_malformed_filenames(tmp_path):
    """Files that match the prefix but not the date pattern are left alone."""
    from backend.memory.backup import cleanup_old_backups

    (tmp_path / "ai_memory_not-a-date.json").write_text("{}")
    (tmp_path / "ai_memory_2020-13-99.json").write_text("{}")

    removed = cleanup_old_backups(tmp_path, keep_days=30)

    assert removed == 0
    assert len(list(tmp_path.iterdir())) == 2


def test_run_daily_backup_writes_file_and_audits(test_db, tmp_path):
    from sqlalchemy import text

    from backend.memory.ai_memory import remember
    from backend.memory.backup import run_daily_backup

    remember(test_db, "rule:test1", "测试1 规则", category="rule", scope="test1")

    path = run_daily_backup(test_db, backup_dir=tmp_path, keep_days=365, today="2026-05-19")

    assert path.exists()
    assert path.name == "ai_memory_2026-05-19.json"

    audit_count = test_db.execute(text(
        "SELECT count(*) FROM audit_log_fts WHERE event_type='memory.backup'"
    )).scalar()
    assert audit_count == 1


def test_run_daily_backup_is_idempotent_same_day(test_db, tmp_path):
    """Re-running on the same day overwrites the file (still single backup)."""
    from backend.memory.ai_memory import remember
    from backend.memory.backup import run_daily_backup

    remember(test_db, "rule:test1", "v1", category="rule", scope="test1")
    run_daily_backup(test_db, backup_dir=tmp_path, keep_days=365, today="2026-05-19")

    remember(test_db, "rule:test1", "v2", category="rule", scope="test1")
    run_daily_backup(test_db, backup_dir=tmp_path, keep_days=365, today="2026-05-19")

    files = list(tmp_path.glob("ai_memory_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    values = {r["key"]: r["value"] for r in payload["rows"]}
    assert values["rule:test1"] == "v2"
