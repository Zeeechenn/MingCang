"""Record an operator's explicit clearance of an adjustment-basis drift event.

Why this exists
---------------
``summarize_basis_drift_events`` gates a day on same-source (and unknown-source)
adjustment-basis drift, and ``one_loop_continuity`` fails the *whole* window on
any incomplete day.  Until now nothing could ever clear such an event:
``rebase_price_history`` refuses to write production by design (P0-B1), so one
re-basing event -- 603993 on 2026-09-09 was the first to bite -- blocked the
20-day gate permanently no matter how many clean days followed.

What this does and does not do
------------------------------
It writes a *separate* clearance row.  It never edits or deletes the
``degradation_events`` row: the drift really happened, and that evidence has to
survive.  A clearance is a named operator asserting "I looked at this and dealt
with it", with a reason, and that assertion is itself auditable evidence.

Because a clearance suppresses a real gate, two guards apply:

* the drift event must actually exist and actually be gating on that date --
  you cannot pre-clear a future day or clear a cross-source event that was
  never gating in the first place;
* ``--operator`` and ``--reason`` are mandatory and must be non-empty.

Dry-run is the default; ``--apply`` writes.

Usage::

    python3 -m backend.tools.acknowledge_basis_drift \\
        --symbol 603993 --date 2026-09-09 \\
        --operator owner --reason "provider cash-dividend re-base, reviewed" [--apply]

After an approved clearance, create a new consistent SQLite snapshot with
``scripts/sqlite_consistent_snapshot.py`` and audit that snapshot with
``scripts/audit_one_loop_continuity.py``. The audit reads clearance rows alongside
the saved panel. Preserve completed signal batches and panels; do not regenerate
them just to acknowledge drift. A clearance does not repair historical prices.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date

from sqlalchemy import func

from backend.data.database import SessionLocal
from backend.data.models.degradation import (
    AdjustmentBasisClearance,
    DegradationEvent,
)
from backend.data.price_quality import summarize_basis_drift_events

DRIFT_CATEGORY = "adjustment_basis_drift"


def _parse_day(value: str) -> str:
    try:
        return _date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise SystemExit(f"--date must be YYYY-MM-DD, got {value!r}") from exc


def _gating_symbols(db, day: str) -> tuple[set[str], dict]:
    """Return the symbols whose drift gates *day*, ignoring existing clearances."""
    payloads = []
    rows = (
        db.query(DegradationEvent.context_json)
        .filter(
            DegradationEvent.category == DRIFT_CATEGORY,
            func.date(DegradationEvent.ts) == day,
        )
        .all()
    )
    for (context_json,) in rows:
        if not context_json:
            continue
        try:
            parsed = json.loads(context_json)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    summary = summarize_basis_drift_events(payloads)
    return set(summary["uncleared_symbols"]), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True, help="The drift day being cleared (YYYY-MM-DD)")
    parser.add_argument("--operator", required=True, help="Who is making this assertion")
    parser.add_argument("--reason", required=True, help="Why this drift is considered dealt with")
    parser.add_argument("--apply", action="store_true", help="Write; default is dry-run")
    args = parser.parse_args(argv)

    symbol = args.symbol.strip()
    operator = args.operator.strip()
    reason = args.reason.strip()
    if not symbol:
        print("⛔ --symbol must not be empty")
        return 2
    if not operator:
        print("⛔ --operator must not be empty: a clearance has to be attributable")
        return 2
    if not reason:
        print("⛔ --reason must not be empty: a clearance without a stated reason is not evidence")
        return 2
    day = _parse_day(args.date)

    db = SessionLocal()
    try:
        gating, summary = _gating_symbols(db, day)
        print(f"{day} 漂移事件 {summary['events']} 条 · 同源 {summary['same_source']} · "
              f"跨源 {summary['cross_source']} · 未知源 {summary['unknown_source']}")
        print(f"{day} 当前 gating（未清理）: {sorted(gating) or '无'}")

        if symbol not in gating:
            print(
                f"⛔ {symbol} 在 {day} 没有正在 gating 的同源/未知源漂移事件——"
                "不能预先清理未发生的事件，也不需要清理本来就不 gating 的跨源事件。"
            )
            return 4

        existing = (
            db.query(AdjustmentBasisClearance)
            .filter(
                AdjustmentBasisClearance.symbol == symbol,
                AdjustmentBasisClearance.event_date == day,
            )
            .one_or_none()
        )
        if existing is not None:
            print(
                f"✅ {symbol}@{day} 已有清理记录（{existing.operator} · {existing.ts}）："
                f"{existing.reason}"
            )
            return 0

        if not args.apply:
            print(
                f"[dry-run] 将写入清理记录：{symbol}@{day} · operator={operator} · reason={reason}\n"
                "          仅在获得明确确认后加 --apply；写入后创建新的一致 SQLite 快照并重新审计。\n"
                "          保留已成功的信号与面板，不为确认漂移重跑；确认记录不修复历史价格。"
            )
            return 0

        db.add(
            AdjustmentBasisClearance(
                symbol=symbol,
                event_date=day,
                operator=operator,
                reason=reason,
            )
        )
        db.commit()
        print(
            f"✅ 已写入清理记录：{symbol}@{day} · operator={operator}\n"
            f"   理由：{reason}\n"
            f"   ⚠ degradation_events 原始事件行未改动（证据保留）。\n"
            "   下一步：使用 scripts/sqlite_consistent_snapshot.py 创建新快照，\n"
            "   再用 scripts/audit_one_loop_continuity.py --db <新快照> 重新审计。\n"
            "   保留已成功的信号与面板，不为确认漂移重跑；确认记录不修复历史价格。"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
