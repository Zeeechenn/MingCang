"""Pre-commit guard for runtime data and secrets."""

from __future__ import annotations

import sys
from pathlib import Path

BLOCKED_NAMES = {".env", ".env.local", ".env.production"}
BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pkl", ".pickle", ".parquet"}


def is_blocked(path: str) -> bool:
    p = Path(path)
    if p.name in BLOCKED_NAMES:
        return True
    return any(p.name.endswith(suffix) for suffix in BLOCKED_SUFFIXES)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    blocked = [path for path in argv if is_blocked(path)]
    if blocked:
        print("Blocked runtime data / secret-like files:", file=sys.stderr)
        for path in blocked:
            print(f"  - {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
