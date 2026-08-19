"""Audit or maintain MingCang's outcome-backed memory loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import default_sqlite_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_sqlite_path())
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Backfill outcomes, archive resolved/unresolvable raw judgments, "
            "and synchronize recall index"
        ),
    )
    parser.add_argument("--retention-days", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    from backend.memory.maintenance import memory_health_snapshot, run_memory_maintenance

    args = build_parser().parse_args(argv)
    db_path = args.db.expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    url = (
        f"sqlite+pysqlite:///{db_path}"
        if args.apply
        else f"sqlite+pysqlite:///file:{db_path}?mode=ro&immutable=1&uri=true"
    )
    engine = create_engine(url, future=True)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    try:
        payload = (
            run_memory_maintenance(db, retention_days=max(0, args.retention_days))
            if args.apply
            else memory_health_snapshot(db)
        )
    finally:
        db.close()
        engine.dispose()
    payload = {
        "database": str(db_path),
        "mode": "apply" if args.apply else "read_only_immutable",
        **payload,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
