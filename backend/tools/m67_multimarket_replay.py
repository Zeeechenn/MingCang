"""CLI adapter for the M67 gray replay."""

from __future__ import annotations

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M67 close-confirmed multi-market replay")
    parser.add_argument("asset_keys", nargs="+", help="Market-scoped keys such as HK:00700 US:AAPL")
    parser.add_argument("--as-of", default=None, help="Inclusive YYYY-MM-DD cutoff")
    args = parser.parse_args()

    from backend.backtest.multimarket_replay import run_market_replay
    from backend.data.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        print(json.dumps(
            run_market_replay(db, args.asset_keys, as_of=args.as_of),
            ensure_ascii=False,
            indent=2,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    main()
