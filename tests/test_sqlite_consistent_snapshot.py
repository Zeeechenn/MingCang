from __future__ import annotations

import sqlite3

from scripts.sqlite_consistent_snapshot import snapshot_sqlite


def test_snapshot_includes_latest_committed_wal_row_without_checkpoint(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "snapshot.db"
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        writer.execute("INSERT INTO events(value) VALUES ('first')")
        writer.commit()
        writer.execute("INSERT INTO events(value) VALUES ('latest committed')")
        writer.commit()
        assert (source.parent / "source.db-wal").exists()

        snapshot_sqlite(source, destination)

        with sqlite3.connect(destination) as snapshot:
            values = snapshot.execute("SELECT value FROM events ORDER BY id").fetchall()
        assert values == [("first",), ("latest committed",)]
        assert (source.parent / "source.db-wal").exists()
    finally:
        writer.close()
