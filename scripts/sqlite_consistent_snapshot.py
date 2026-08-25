#!/usr/bin/env python3
"""Create an atomic, consistent SQLite snapshot without mutating the source.

The source is opened read-only and copied with SQLite's backup API. In
particular, this does not issue a checkpoint: committed rows still held in a
source WAL are part of the read-only connection's snapshot. The destination is
built beside the requested path, checked, and atomically replaced only after
the copy passes ``quick_check``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote


def _source_uri(path: Path) -> str:
    return f"file:{quote(str(path), safe='/')}?mode=ro"


def snapshot_sqlite(source: Path | str, destination: Path | str) -> Path:
    """Snapshot *source* to *destination* and return the destination path."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("source and destination must differ")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    with sqlite3.connect(_source_uri(source_path), uri=True) as source_db:
        with tempfile.NamedTemporaryFile(
            dir=destination_path.parent,
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
        try:
            with sqlite3.connect(temp_path) as destination_db:
                source_db.backup(destination_db)
                check = destination_db.execute("PRAGMA quick_check").fetchone()
                if check != ("ok",):
                    raise sqlite3.DatabaseError(f"destination quick_check failed: {check!r}")
                destination_db.commit()
            with temp_path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temp_path, destination_path)
            temp_path = None
            try:
                dir_fd = os.open(destination_path.parent, os.O_RDONLY)
            except OSError:
                dir_fd = None
            if dir_fd is not None:
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return destination_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, type=Path, help="SQLite database to open read-only"
    )
    parser.add_argument(
        "--destination",
        required=True,
        type=Path,
        help="snapshot path to atomically replace",
    )
    args = parser.parse_args(argv)
    snapshot_sqlite(args.source, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
