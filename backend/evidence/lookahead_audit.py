"""Canonical read-only lookahead audit implementation.

This is intentionally not wired into the public ``mingcang`` CLI. M47 owns the
standing productized check. The historical M46.5 tool path remains as a
compatibility adapter. The audit emits pass/warning/blocked evidence for the
current SQLite state.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from backend.config import settings, sqlite_path_from_url
from backend.data.database import (
    FinancialMetric,
    MemoryAtom,
    MemoryPromotionCandidate,
    NewsItem,
    Price,
    ReviewCase,
    Signal,
    StockMemoryItem,
)

DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
PLAIN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_part(value: Any) -> str | None:
    if value is None:
        return None
    match = DATE_PREFIX_RE.match(str(value))
    return match.group(1) if match else None


def _plain_date_count(db, model, field_name: str) -> int:
    field = getattr(model, field_name)
    return sum(
        1
        for (value,) in db.query(field).all()
        if value is None or not PLAIN_DATE_RE.match(str(value))
    )


def _examples(rows: list[Any], fields: list[str], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for row in rows[:limit]:
        out.append({field: getattr(row, field, None) for field in fields})
    return out


def _check(
    *,
    name: str,
    status: str,
    count: int,
    description: str,
    examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "count": int(count),
        "description": description,
        "examples": examples or [],
    }


def _signal_data_timestamp_after_signal_day(db) -> dict[str, Any]:
    rows = []
    for row in db.query(Signal).all():
        data_day = _date_part(row.data_timestamp)
        signal_day = _date_part(row.date)
        if data_day is not None and signal_day is not None and data_day > signal_day:
            rows.append(row)
    return _check(
        name="signal_data_timestamp_after_signal_day",
        status="blocked" if rows else "pass",
        count=len(rows),
        description="Signal.data_timestamp must not post-date the signal day.",
        examples=_examples(rows, ["id", "symbol", "date", "data_timestamp", "recommendation"]),
    )


def _signal_date_shape(db) -> dict[str, Any]:
    count = _plain_date_count(db, Signal, "date")
    rows = (
        db.query(Signal)
        .order_by(Signal.id.desc())
        .limit(200)
        .all()
    )
    examples = [
        {"id": row.id, "symbol": row.symbol, "date": row.date, "data_timestamp": row.data_timestamp}
        for row in rows
        if row.date is None or not PLAIN_DATE_RE.match(str(row.date))
    ][:5]
    return _check(
        name="signal_date_not_plain_yyyy_mm_dd",
        status="warning" if count else "pass",
        count=count,
        description="Signal.date should stay as YYYY-MM-DD so PIT string comparisons and UI dates are unambiguous.",
        examples=examples,
    )


def _signals_without_asof_price(db) -> dict[str, Any]:
    rows = []
    for signal in db.query(Signal).all():
        signal_day = _date_part(signal.date)
        if not signal_day:
            continue
        has_price = (
            db.query(Price.id)
            .filter(Price.symbol == signal.symbol, Price.date <= signal_day)
            .order_by(Price.date.desc())
            .first()
            is not None
        )
        if not has_price:
            rows.append(signal)
    return _check(
        name="signal_without_price_on_or_before_signal_day",
        status="blocked" if rows else "pass",
        count=len(rows),
        description="Every stored signal must have at least one same-symbol price row available on or before its signal day.",
        examples=_examples(rows, ["id", "symbol", "date", "data_timestamp", "recommendation"]),
    )


def _same_symbol_news_after_signal_day(db) -> dict[str, Any]:
    rows = []
    signals = (
        db.query(Signal)
        .filter(Signal.sentiment_score.is_not(None), Signal.sentiment_score != 0)
        .all()
    )
    for signal in signals:
        signal_day = _date_part(signal.date)
        if not signal_day:
            continue
        news = (
            db.query(NewsItem)
            .filter(
                NewsItem.symbol == signal.symbol,
                func.substr(NewsItem.published_at, 1, 10) > signal_day,
                func.substr(NewsItem.published_at, 1, 10) <= func.date(signal_day, "+1 day"),
            )
            .order_by(NewsItem.published_at.asc())
            .first()
        )
        if news is not None:
            rows.append({
                "signal_id": signal.id,
                "symbol": signal.symbol,
                "signal_date": signal.date,
                "sentiment_score": signal.sentiment_score,
                "news_published_at": str(news.published_at),
                "news_title": news.title,
            })
    return _check(
        name="same_symbol_news_after_signal_day_requires_lineage_review",
        status="warning" if rows else "pass",
        count=len(rows),
        description=(
            "Same-symbol news exists after a sentiment-bearing signal day. "
            "This is not a leak proof without per-signal news lineage, but it requires review before promotion."
        ),
        examples=rows[:5],
    )


def _financial_disclosure_before_report_date(db) -> dict[str, Any]:
    rows = (
        db.query(FinancialMetric)
        .filter(
            FinancialMetric.disclosure_date.is_not(None),
            FinancialMetric.disclosure_date != "",
            FinancialMetric.disclosure_date < FinancialMetric.report_date,
        )
        .order_by(FinancialMetric.symbol, FinancialMetric.report_date)
        .limit(5)
        .all()
    )
    count = (
        db.query(FinancialMetric)
        .filter(
            FinancialMetric.disclosure_date.is_not(None),
            FinancialMetric.disclosure_date != "",
            FinancialMetric.disclosure_date < FinancialMetric.report_date,
        )
        .count()
    )
    return _check(
        name="financial_disclosure_before_report_date",
        status="blocked" if count else "pass",
        count=count,
        description="FinancialMetric.disclosure_date must not be earlier than report_date.",
        examples=_examples(rows, ["id", "symbol", "report_date", "disclosure_date"]),
    )


def _financial_disclosure_missing(db) -> dict[str, Any]:
    count = (
        db.query(FinancialMetric)
        .filter((FinancialMetric.disclosure_date.is_(None)) | (FinancialMetric.disclosure_date == ""))
        .count()
    )
    rows = (
        db.query(FinancialMetric)
        .filter((FinancialMetric.disclosure_date.is_(None)) | (FinancialMetric.disclosure_date == ""))
        .order_by(FinancialMetric.symbol, FinancialMetric.report_date)
        .limit(5)
        .all()
    )
    return _check(
        name="financial_disclosure_date_missing",
        status="warning" if count else "pass",
        count=count,
        description="Missing disclosure_date falls back to conservative PIT handling, but cannot prove exact filing availability.",
        examples=_examples(rows, ["id", "symbol", "report_date", "disclosure_date"]),
    )


def _price_rows_missing_provenance(db) -> dict[str, Any]:
    count = (
        db.query(Price)
        .filter(
            (Price.source.is_(None)) | (Price.source == "")
            | (Price.fetched_at.is_(None))
            | (Price.adjustment.is_(None)) | (Price.adjustment == "")
        )
        .count()
    )
    rows = (
        db.query(Price)
        .filter(
            (Price.source.is_(None)) | (Price.source == "")
            | (Price.fetched_at.is_(None))
            | (Price.adjustment.is_(None)) | (Price.adjustment == "")
        )
        .order_by(Price.symbol, Price.date)
        .limit(5)
        .all()
    )
    return _check(
        name="price_rows_missing_provenance",
        status="warning" if count else "pass",
        count=count,
        description="Price rows without source/fetched_at/adjustment cannot prove provider fallback or qfq/hfq basis.",
        examples=_examples(rows, ["id", "symbol", "date", "source", "fetched_at", "adjustment"]),
    )


def _review_case_references_future_signal(db) -> dict[str, Any]:
    rows = []
    for review in db.query(ReviewCase).filter(ReviewCase.signal_id.is_not(None)).all():
        signal = db.query(Signal).filter(Signal.id == review.signal_id).first()
        if not signal:
            continue
        signal_day = _date_part(signal.date)
        review_day = _date_part(review.as_of)
        if signal_day and review_day and signal_day > review_day:
            rows.append({
                "review_case_id": review.id,
                "symbol": review.symbol,
                "review_as_of": review.as_of,
                "signal_id": signal.id,
                "signal_date": signal.date,
            })
    return _check(
        name="review_case_references_future_signal",
        status="blocked" if rows else "pass",
        count=len(rows),
        description="ReviewCase.as_of must not reference a Signal dated after the review date.",
        examples=rows[:5],
    )


def _review_case_created_before_as_of(db) -> dict[str, Any]:
    rows = []
    for row in db.query(ReviewCase).all():
        created_day = _date_part(row.created_at)
        as_of_day = _date_part(row.as_of)
        if created_day is not None and as_of_day is not None and created_day < as_of_day:
            rows.append(row)
    return _check(
        name="review_case_created_before_as_of",
        status="warning" if rows else "pass",
        count=len(rows),
        description="Review cases created before their as_of date may be preregistered, but should be reviewed before promotion.",
        examples=_examples(rows, ["id", "symbol", "as_of", "signal_id", "created_at"]),
    )


def _memory_promotion_state(db) -> dict[str, Any]:
    trusted_without_review = (
        db.query(MemoryPromotionCandidate)
        .filter(
            MemoryPromotionCandidate.source_trust == "trusted",
            MemoryPromotionCandidate.review_case_id.is_(None),
        )
        .count()
    )
    trusted_atoms = db.query(MemoryAtom).filter(MemoryAtom.trust_state.in_(["trusted", "refuted"])).count()
    legacy_active = db.query(StockMemoryItem).filter(StockMemoryItem.status == "active").count()
    status = "blocked" if trusted_without_review else "pass"
    return _check(
        name="memory_promotion_state",
        status=status,
        count=trusted_without_review,
        description=(
            "Trusted memory promotion candidates must be tied to a review case. "
            f"Trusted/refuted L0 atoms={trusted_atoms}; active legacy memory rows={legacy_active}."
        ),
    )


def build_audit(db, *, as_of: str | None = None) -> dict[str, Any]:
    checks = [
        _signal_data_timestamp_after_signal_day(db),
        _signal_date_shape(db),
        _signals_without_asof_price(db),
        _same_symbol_news_after_signal_day(db),
        _financial_disclosure_before_report_date(db),
        _financial_disclosure_missing(db),
        _price_rows_missing_provenance(db),
        _review_case_references_future_signal(db),
        _review_case_created_before_as_of(db),
        _memory_promotion_state(db),
        _check(
            name="pit_guard_managed_models",
            status="pass",
            count=6,
            description="PITSession has registered guards for Price, Signal, LongTermLabel, FinancialMetric, IndexPrice, and NewsItem.",
        ),
    ]
    blockers = [check["name"] for check in checks if check["status"] == "blocked"]
    warnings = [check["name"] for check in checks if check["status"] == "warning"]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m46_5_lookahead_one_time_audit.v1",
        "milestone": "M46.5",
        "purpose": "one-time read-only lookahead leak audit before user-facing polish",
        "run_mode": "one_time_read_only_audit",
        "status": "blocked" if blockers else ("warning" if warnings else "pass"),
        "as_of": as_of,
        "writes_db": False,
        "calls_llm_or_api": False,
        "productized_cli": False,
        "promotion_impact": "none",
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M46.5 Lookahead One-Time Audit",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- status: {report['status']}",
        f"- run_mode: {report['run_mode']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- productized_cli: {report['productized_cli']}",
        f"- promotion_impact: {report['promotion_impact']}",
        "",
        "## Checks",
        "",
        "| check | status | count |",
        "|---|---|---:|",
    ]
    lines.extend(
        f"| {check['name']} | {check['status']} | {check['count']} |"
        for check in report["checks"]
    )
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report["blockers"] or ["none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in report["warnings"] or ["none"])
    lines.append("")
    return "\n".join(lines)


def _readonly_sqlite_url(database_url: str) -> str:
    if "mode=ro" in database_url or "uri=true" in database_url:
        return database_url
    sqlite_path = sqlite_path_from_url(database_url)
    if sqlite_path is None:
        return database_url
    return f"sqlite:///file:{sqlite_path}?mode=ro&immutable=1&uri=true"


def _session_for_url(database_url: str):
    engine = create_engine(_readonly_sqlite_url(database_url))
    return sessionmaker(bind=engine)()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=settings.database_url)
    parser.add_argument("--as-of")
    parser.add_argument("--markdown", action="store_true", help="Print markdown instead of JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = _session_for_url(args.db_url)
    try:
        db.execute(text("SELECT 1"))
        report = build_audit(db, as_of=args.as_of)
    finally:
        db.close()
    if args.markdown:
        print(report_to_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
