"""M54 news layer v2 daily forward accrual.

Purpose (M54_OOS_PREREGISTER.md §12-13): the only path left to a real
v2-vs-legacy verdict is accumulating more non-overlapping IC days (14/9 vs the
20-day gate as of §13) by scoring *forward* -- one trading day at a time, from
now on -- rather than re-litigating the same closed historical window. This
tool is the daily operator entrypoint for that: idempotent same-day content
fetch, pyramid scoring (M54 §12-13 owner-authorized default), a v2 score-cache
write, and a progress readout against the 20-IC-day gate.

Read/write boundary, same posture as backend/tools/m54_news_v2_oos.py:
- writes only deduplicated `news` rows (via save_news_to_db, same as
  m54_content_backfill.py) and rows in the shared `m54_oos_score_cache` table,
  keyed by (namespace, symbol, sig_date, lookback_days, tier) so re-running the
  same date is a no-op for scoring/spend (cache hit, no new LLM call).
- never imports backend/analysis/sentiment.py, the official signal path, the
  scheduler, or any test1/test2 weight. Pyramid scoring flows exclusively
  through backend.data.news_layer_v2.news_v2_score_from_db, the same v2
  observe-only entrypoint m54_news_v2_oos.py uses.
- forces the pyramid path on for its own scoring calls (via
  m54_news_v2_oos._pyramid_override(True)) regardless of the ambient
  settings.news_v2_pyramid_enabled value, so this command's semantics stay
  fixed even if the global default is ever flipped back for unrelated reasons.

Recommended daily usage::

    python3 -m backend.tools.m54_daily_accrual

Read-only progress check (no fetch/scoring, safe to run anytime)::

    python3 -m backend.tools.m54_daily_accrual --report-only
"""
from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.data.database import SessionLocal
from backend.data.news import (
    fetch_news_ifind,
    fetch_stock_news_anspire,
    fetch_stock_news_cn,
    save_news_to_db,
)
from backend.data.news_layer_v2 import PYRAMID_NOT_TRIGGERED, news_v2_score_from_db
from backend.data.news_models import RawNews
from backend.ops.llm_budget import get_today_spend
from backend.tools import m54_news_v2_oos as oos_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE = REPO_ROOT / "paper_trading" / "test3_universe.json"
DEFAULT_NS = "m54_pyramid_forward"
DEFAULT_LOOKBACK_DAYS = oos_tool.DEFAULT_LOOKBACK_DAYS
DEFAULT_TIER = "capable"

SessionFactory = Callable[[], Session]

logger = logging.getLogger(__name__)


def run_daily_accrual(
    *,
    date: str,
    universe_path: Path = DEFAULT_UNIVERSE,
    ns: str = DEFAULT_NS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tier: str = DEFAULT_TIER,
    cn_limit: int = 20,
    stock_limit: int | None = None,
    mock: bool = False,
    fetch_content: bool = True,
    db: Session | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> dict[str, Any]:
    """Run one day's forward accrual: content fetch + pyramid scoring + cache write.

    Idempotent: re-running the same ``date`` re-fetches content (itself
    deduplicated by URL/title in ``save_news_to_db``) but skips re-scoring any
    (symbol, date) pair already present in the score cache -- no duplicate LLM
    spend, no duplicate rows, same trigger/token accounting either way.
    """
    target_dt = datetime.strptime(date, "%Y-%m-%d")
    owns_db = db is None
    active_db = db or session_factory()
    try:
        oos_tool._ensure_score_cache_schema(active_db)

        if target_dt.weekday() >= 5:
            progress = compute_progress(
                ns=ns,
                lookback_days=lookback_days,
                tier=tier,
                db=active_db,
                session_factory=session_factory,
            )
            return {
                "ok": True,
                "date": date,
                "market_open": False,
                "note": "weekend date, skipped fetch/score (idempotent no-op)",
                "progress": progress,
            }

        if mock:
            oos_tool._install_mock_provider()

        targets = oos_tool._load_universe(universe_path, limit=stock_limit)

        inserted_total = 0
        fetch_failed = 0
        if fetch_content:
            for target in targets:
                symbol, name = target["symbol"], target["name"]
                try:
                    items: list[RawNews] = []
                    items.extend(fetch_stock_news_cn(symbol, limit=cn_limit))
                    items.extend(fetch_stock_news_anspire(symbol, name))
                    items.extend(fetch_news_ifind(symbol, name))
                    inserted_total += save_news_to_db(items, active_db)
                except Exception as exc:  # pragma: no cover - operator resilience, mirrors m54_content_backfill.
                    fetch_failed += 1
                    logger.warning("M54 daily accrual content fetch skipped %s: %s", symbol, exc)
                    active_db.rollback()

        as_of = datetime.combine(target_dt.date(), time(23, 59, 59))
        n_scored_new = 0
        n_cache_hit = 0
        n_score_failed = 0
        n_triggered = 0
        n_not_triggered = 0

        with oos_tool._pyramid_override(True):
            for target in targets:
                symbol = target["symbol"]
                cached = oos_tool._score_cache_get(
                    active_db,
                    namespace=ns,
                    symbol=symbol,
                    sig_date=date,
                    lookback_days=lookback_days,
                    tier=tier,
                )
                if cached is not None:
                    n_cache_hit += 1
                    score = cached
                else:
                    try:
                        signal = news_v2_score_from_db(
                            symbol, as_of, lookback_days, active_db, tier=tier
                        )
                    except Exception as exc:  # pragma: no cover - operator resilience.
                        n_score_failed += 1
                        logger.warning("M54 daily accrual scoring failed %s: %s", symbol, exc)
                        continue
                    score = oos_tool._score_from_signal(signal)
                    n_scored_new += 1
                    if oos_tool._score_is_cacheable(score):
                        oos_tool._score_cache_set(
                            active_db,
                            namespace=ns,
                            symbol=symbol,
                            sig_date=date,
                            lookback_days=lookback_days,
                            tier=tier,
                            score=score,
                        )

                if PYRAMID_NOT_TRIGGERED in score.get("degradation_flags", []):
                    n_not_triggered += 1
                else:
                    n_triggered += 1

        n_processed = n_triggered + n_not_triggered
        trigger_rate = round(n_triggered / n_processed, 4) if n_processed else None
        tokens_spent_today, tokens_unknown = get_today_spend("sentiment")

        progress = compute_progress(
            ns=ns,
            lookback_days=lookback_days,
            tier=tier,
            db=active_db,
            session_factory=session_factory,
        )

        return {
            "ok": True,
            "date": date,
            "market_open": True,
            "namespace": ns,
            "universe": str(universe_path),
            "n_symbols_total": len(targets),
            "content_inserted": inserted_total,
            "content_fetch_failed": fetch_failed,
            "n_scored_new": n_scored_new,
            "n_cache_hit_skipped": n_cache_hit,
            "n_score_failed": n_score_failed,
            "n_triggered": n_triggered,
            "n_not_triggered": n_not_triggered,
            "trigger_rate": trigger_rate,
            "tokens_spent_today_sentiment_bucket": tokens_spent_today,
            "tokens_spent_unknown": tokens_unknown,
            "progress": progress,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    finally:
        if owns_db:
            active_db.close()


def compute_progress(
    *,
    ns: str = DEFAULT_NS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    tier: str = DEFAULT_TIER,
    db: Session | None = None,
    session_factory: SessionFactory = SessionLocal,
) -> dict[str, Any]:
    """Read-only cumulative IC-day progress for ``ns``, no fetch/scoring/LLM spend.

    Reuses the exact IC methodology of backend.tools.m54_news_v2_oos
    (_load_prices / _build_trading_calendar / _forward_return /
    _metrics_for_records) over whatever is already cached, so the numbers here
    are directly comparable to the harness's own IC-day gate.
    """
    owns_db = db is None
    active_db = db or session_factory()
    try:
        oos_tool._ensure_score_cache_schema(active_db)
        rows = active_db.execute(
            text(
                """
                SELECT symbol, sig_date, composite, degradation_flags
                FROM m54_oos_score_cache
                WHERE namespace = :namespace
                  AND lookback_days = :lookback_days
                  AND tier = :tier
                ORDER BY sig_date ASC
                """
            ),
            {"namespace": ns, "lookback_days": lookback_days, "tier": tier},
        ).fetchall()
    finally:
        if owns_db:
            active_db.close()

    if not rows:
        empty_metrics = oos_tool._metrics_for_records([])
        return {
            "namespace": ns,
            "window": None,
            "n_cached_rows": 0,
            "n_ic_eligible_rows": 0,
            "n_symbols": 0,
            "metrics": empty_metrics,
            "gate": _gate_progress(empty_metrics),
        }

    parsed_rows = [
        {
            "symbol": str(row._mapping["symbol"]),
            "sig_date": str(row._mapping["sig_date"]),
            "composite": float(row._mapping["composite"]),
            "flags": json.loads(str(row._mapping["degradation_flags"] or "[]")),
        }
        for row in rows
    ]
    symbols = sorted({r["symbol"] for r in parsed_rows})
    dates = [r["sig_date"] for r in parsed_rows]
    window_start, window_end = min(dates), max(dates)

    prices_by_symbol = oos_tool._load_prices(
        symbols, window_start, window_end, session_factory=session_factory
    )
    calendar = oos_tool._build_trading_calendar(prices_by_symbol)

    records: list[dict[str, Any]] = []
    for row in parsed_rows:
        if any(flag in oos_tool.EXCLUDE_FROM_IC for flag in row["flags"]):
            continue
        prices = prices_by_symbol.get(row["symbol"], {})
        record: dict[str, Any] = {
            "symbol": row["symbol"],
            "date": row["sig_date"],
            "score": row["composite"],
        }
        for horizon in oos_tool.HORIZONS:
            record[f"fwd_{horizon}d"] = oos_tool._forward_return(
                prices, row["sig_date"], horizon, calendar
            )
        records.append(record)

    metrics = oos_tool._metrics_for_records(records)
    return {
        "namespace": ns,
        "window": {"start": window_start, "end": window_end},
        "n_cached_rows": len(parsed_rows),
        "n_ic_eligible_rows": len(records),
        "n_symbols": len(symbols),
        "metrics": metrics,
        "gate": _gate_progress(metrics),
    }


def _gate_progress(metrics: dict[str, Any]) -> dict[str, Any]:
    per_horizon: dict[str, Any] = {}
    for hkey, horizon in (("h3d", 3), ("h5d", 5)):
        ic_days = int(metrics.get(hkey, {}).get("ic_days") or 0)
        remaining = max(0, oos_tool.MIN_NON_OVERLAP_IC_DAYS - ic_days)
        per_horizon[hkey] = {
            "ic_days": ic_days,
            "min_required": oos_tool.MIN_NON_OVERLAP_IC_DAYS,
            "remaining_ic_days": remaining,
            # Heuristic only: ic_days is drawn via non-overlapping horizon-day
            # strides over the trading calendar (M54_OOS_PREREGISTER §10-13),
            # so one more IC day needs roughly `horizon` more trading days.
            "approx_trading_days_remaining": remaining * horizon,
        }
    passed = all(v["remaining_ic_days"] == 0 for v in per_horizon.values())
    return {**per_horizon, "passed": passed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M54 news layer v2 daily forward accrual: idempotent same-day "
            "content fetch + pyramid scoring + v2 score-cache write, plus "
            "cumulative IC-day gate progress (M54_OOS_PREREGISTER §12-13)."
        )
    )
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD, default today")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--ns", default=DEFAULT_NS)
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--tier", default=DEFAULT_TIER)
    parser.add_argument("--cn-limit", type=int, default=20)
    parser.add_argument("--limit", type=int, default=None, help="Limit universe size (debugging)")
    parser.add_argument(
        "--mock", action="store_true", help="Install the deterministic mock LLM provider (no live LLM calls)"
    )
    parser.add_argument(
        "--no-fetch", action="store_true", help="Skip content fetch, score from whatever news is already in the DB"
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Read-only: print cumulative IC-day gate progress, no fetch/scoring/spend",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.report_only:
        progress = compute_progress(ns=args.ns, lookback_days=args.lookback, tier=args.tier)
        payload: dict[str, Any] = {
            "ok": True,
            "schema_version": "m54_daily_accrual.report.v1",
            **progress,
        }
    else:
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        result = run_daily_accrual(
            date=date,
            universe_path=args.universe,
            ns=args.ns,
            lookback_days=args.lookback,
            tier=args.tier,
            cn_limit=args.cn_limit,
            stock_limit=args.limit,
            mock=args.mock,
            fetch_content=not args.no_fetch,
        )
        payload = {"schema_version": "m54_daily_accrual.v1", **result}

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
