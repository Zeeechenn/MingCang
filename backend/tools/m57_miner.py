"""CLI for the M57 rule-based memory evolution miner."""
from __future__ import annotations

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M57 memory evolution miner")
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--cooldown-days", type=int, default=7)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    from backend.data.database import SessionLocal, init_db
    from backend.memory.evolution_miner import run_miner

    init_db()
    db = SessionLocal()
    try:
        result = run_miner(
            db,
            min_support=args.min_support,
            cooldown_days=args.cooldown_days,
            lookback_days=args.lookback_days,
        )
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, default=str))


if __name__ == "__main__":
    main()
