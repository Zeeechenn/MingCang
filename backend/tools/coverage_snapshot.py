"""Print the current StockSage data coverage snapshot as JSON."""

from __future__ import annotations

import json

from backend.data.database import SessionLocal
from backend.data.quality import build_data_coverage_snapshot


def main() -> None:
    db = SessionLocal()
    try:
        print(
            json.dumps(build_data_coverage_snapshot(db), ensure_ascii=False, indent=2, default=str)
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
