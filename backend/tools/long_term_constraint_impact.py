"""Read-only impact report for long-term label linkage.

The report compares the latest stored daily signal with the active long-term
label under two modes:

* shadow-only: ``LONG_TERM_CONSTRAINTS_ENABLED=false``
* enforced: ``LONG_TERM_CONSTRAINTS_ENABLED=true``

It does not refresh market data, run long-term analysts, call LLM providers, or
write to the database. The CLI opens the production SQLite database in
``mode=ro`` and prints the report to stdout.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from backend.agents.long_term.base import LongTermLabel
from backend.agents.long_term.storage import bulk_get_labels
from backend.config import BASE_DIR, settings
from backend.data.database import LongTermLabel as LongTermLabelORM
from backend.data.database import Signal, Stock
from backend.decision.research_constraints import apply_research_constraints
from backend.portfolio import suggest_position_pct

DEFAULT_UNIVERSE_PATH = BASE_DIR / "paper_trading" / "test2_universe.json"


@dataclass(frozen=True)
class ImpactRow:
    symbol: str
    name: str | None
    signal_date: str | None
    base_recommendation: str | None
    base_composite_score: float | None
    estimated_base_position_pct: float | None
    label: str | None
    label_date: str | None
    label_quality: str | None
    constraint_eligible: bool | None
    label_finding: str
    shadow_recommendation: str | None
    shadow_composite_score: float | None
    shadow_position_pct: float | None
    shadow_notes: list[str]
    enforced_recommendation: str | None
    enforced_composite_score: float | None
    enforced_position_pct: float | None
    enforced_notes: list[str]
    enforced_conflicts: list[dict]
    changed: bool
    impact_type: str
    delta_position_pct: float | None


@dataclass(frozen=True)
class ImpactReport:
    generated_at: str
    scope: str
    symbol_count: int
    long_term_team_enabled: bool
    current_long_term_constraints_enabled: bool
    latest_signal_date: str | None
    latest_label_date: str | None
    summary: dict[str, int]
    rows: list[ImpactRow]


def _latest_signal(db: Session, symbol: str) -> Signal | None:
    return (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.date.desc(), Signal.id.desc())
        .first()
    )


def _stock_names(db: Session, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    rows = db.query(Stock.symbol, Stock.name).filter(Stock.symbol.in_(symbols)).all()
    return {str(symbol): str(name) for symbol, name in rows}


def _load_test2_symbols(path: Path = DEFAULT_UNIVERSE_PATH) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    symbols: list[str] = []
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else row
        if symbol:
            symbols.append(str(symbol))
    return symbols


def resolve_symbols(
    db: Session,
    *,
    scope: str = "test2",
    symbols: str | None = None,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
) -> list[str]:
    if symbols:
        return [s.strip() for s in symbols.split(",") if s.strip()]
    if scope == "test2":
        return _load_test2_symbols(universe_path)
    if scope == "all-active":
        rows = (
            db.query(Stock.symbol)
            .filter(Stock.active.is_(True))
            .order_by(Stock.symbol.asc())
            .all()
        )
        return [str(row[0]) for row in rows]
    raise ValueError(f"unsupported scope: {scope}")


def _simulate_constraint(
    *,
    recommendation: str,
    composite_score: float,
    position_pct: float,
    label: LongTermLabel | None,
    enforcement_enabled: bool,
):
    original = settings.long_term_constraints_enabled
    settings.long_term_constraints_enabled = enforcement_enabled
    try:
        return apply_research_constraints(
            recommendation=recommendation,
            composite_score=composite_score,
            position_pct=position_pct,
            long_term_label=label,
            memory_context=None,
        )
    finally:
        settings.long_term_constraints_enabled = original


def _impact_type(
    *,
    signal: Signal | None,
    label: LongTermLabel | None,
    base_position: float | None,
    enforced_recommendation: str | None,
    enforced_score: float | None,
    enforced_position: float | None,
) -> tuple[str, bool, float | None]:
    if signal is None:
        return "missing_signal", False, None
    if label is None:
        return "missing_label", False, 0.0
    if not label.constraint_eligible:
        return "ineligible_label", False, 0.0
    if base_position is None or enforced_position is None or enforced_score is None:
        return "unchanged", False, None

    rec_changed = enforced_recommendation != signal.recommendation
    score_changed = round(enforced_score, 4) != round(float(signal.composite_score), 4)
    pos_changed = round(enforced_position, 4) != round(base_position, 4)
    delta = round(enforced_position - base_position, 4)

    if not (rec_changed or score_changed or pos_changed):
        return "unchanged", False, delta
    if enforced_recommendation == "观望" and enforced_position == 0.0:
        return "blocked_entry", True, delta
    if enforced_position < base_position:
        return "position_reduced", True, delta
    if enforced_score < float(signal.composite_score):
        return "score_capped", True, delta
    return "changed", True, delta


def build_impact_report(db: Session, *, scope: str = "test2", symbols: str | None = None) -> ImpactReport:
    selected = resolve_symbols(db, scope=scope, symbols=symbols)
    names = _stock_names(db, selected)
    labels = bulk_get_labels(selected, db)
    rows: list[ImpactRow] = []

    for symbol in selected:
        signal = _latest_signal(db, symbol)
        label = labels.get(symbol)
        base_position: float | None = None
        shadow = None
        enforced = None
        label_finding = (label.key_findings[0] if label and label.key_findings else "")

        if signal is not None:
            base_position = round(
                suggest_position_pct(float(signal.composite_score), signal.confidence),
                4,
            )
            shadow = _simulate_constraint(
                recommendation=signal.recommendation,
                composite_score=float(signal.composite_score),
                position_pct=base_position,
                label=label,
                enforcement_enabled=False,
            )
            enforced = _simulate_constraint(
                recommendation=signal.recommendation,
                composite_score=float(signal.composite_score),
                position_pct=base_position,
                label=label,
                enforcement_enabled=True,
            )

        impact_type, changed, delta = _impact_type(
            signal=signal,
            label=label,
            base_position=base_position,
            enforced_recommendation=enforced.recommendation if enforced else None,
            enforced_score=enforced.composite_score if enforced else None,
            enforced_position=enforced.position_pct if enforced else None,
        )
        rows.append(
            ImpactRow(
                symbol=symbol,
                name=names.get(symbol),
                signal_date=signal.date if signal else None,
                base_recommendation=signal.recommendation if signal else None,
                base_composite_score=float(signal.composite_score) if signal else None,
                estimated_base_position_pct=base_position,
                label=label.label if label else None,
                label_date=label.date if label else None,
                label_quality=label.quality if label else None,
                constraint_eligible=label.constraint_eligible if label else None,
                label_finding=label_finding,
                shadow_recommendation=shadow.recommendation if shadow else None,
                shadow_composite_score=shadow.composite_score if shadow else None,
                shadow_position_pct=shadow.position_pct if shadow else None,
                shadow_notes=shadow.risk_notes if shadow else [],
                enforced_recommendation=enforced.recommendation if enforced else None,
                enforced_composite_score=enforced.composite_score if enforced else None,
                enforced_position_pct=enforced.position_pct if enforced else None,
                enforced_notes=enforced.risk_notes if enforced else [],
                enforced_conflicts=enforced.conflicts if enforced else [],
                changed=changed,
                impact_type=impact_type,
                delta_position_pct=delta,
            )
        )

    summary = {
        "total": len(rows),
        "missing_signal": sum(1 for row in rows if row.impact_type == "missing_signal"),
        "missing_label": sum(1 for row in rows if row.impact_type == "missing_label"),
        "trusted_eligible": sum(
            1
            for row in rows
            if row.label_quality == "trusted" and row.constraint_eligible is True
        ),
        "degraded_or_ineligible": sum(
            1
            for row in rows
            if row.label is not None
            and not (row.label_quality == "trusted" and row.constraint_eligible is True)
        ),
        "changed_if_enforced": sum(1 for row in rows if row.changed),
        "blocked_entries": sum(1 for row in rows if row.impact_type == "blocked_entry"),
        "reduced_positions": sum(1 for row in rows if row.impact_type == "position_reduced"),
        "capped_scores": sum(1 for row in rows if row.impact_type == "score_capped"),
        "unchanged": sum(1 for row in rows if row.impact_type == "unchanged"),
    }
    latest_signal_date = (
        db.query(func.max(Signal.date)).filter(Signal.symbol.in_(selected)).scalar()
        if selected
        else None
    )
    latest_label_date = (
        db.query(func.max(LongTermLabelORM.date)).filter(LongTermLabelORM.symbol.in_(selected)).scalar()
        if selected
        else None
    )
    return ImpactReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        scope=symbols or scope,
        symbol_count=len(selected),
        long_term_team_enabled=bool(settings.long_term_team_enabled),
        current_long_term_constraints_enabled=bool(settings.long_term_constraints_enabled),
        latest_signal_date=latest_signal_date,
        latest_label_date=latest_label_date,
        summary=summary,
        rows=rows,
    )


def report_to_json(report: ImpactReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str)


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def report_to_markdown(report: ImpactReport) -> str:
    lines = [
        "# 长期标签联动只读影响报告",
        "",
        "> 只读影响面分析：基于现有最新 signals 与 active long_term_labels，模拟开启",
        "> LONG_TERM_CONSTRAINTS_ENABLED=true 后的官方动作变化；不是收益回测，也不验证收益改善。",
        "",
        "## 摘要",
        "",
    ]
    for key, value in report.summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            f"- scope: {report.scope}",
            f"- generated_at: {report.generated_at}",
            f"- latest_signal_date: {report.latest_signal_date or '-'}",
            f"- latest_label_date: {report.latest_label_date or '-'}",
            f"- current_long_term_constraints_enabled: {report.current_long_term_constraints_enabled}",
            "",
            "## 明细",
            "",
            "| symbol | name | base | label | eligible | shadow | enforced | impact | Δposition |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report.rows:
        base = (
            "-"
            if row.base_recommendation is None
            else f"{row.base_recommendation} / {row.base_composite_score:.1f} / {_fmt_pct(row.estimated_base_position_pct)}"
        )
        label = (
            "-"
            if row.label is None
            else f"{row.label} ({row.label_quality}, {row.label_date})"
        )
        shadow = (
            "-"
            if row.shadow_recommendation is None
            else f"{row.shadow_recommendation} / {row.shadow_composite_score:.1f} / {_fmt_pct(row.shadow_position_pct)}"
        )
        enforced = (
            "-"
            if row.enforced_recommendation is None
            else f"{row.enforced_recommendation} / {row.enforced_composite_score:.1f} / {_fmt_pct(row.enforced_position_pct)}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    row.symbol,
                    row.name or "-",
                    base,
                    label,
                    "-" if row.constraint_eligible is None else str(row.constraint_eligible),
                    shadow,
                    enforced,
                    row.impact_type,
                    _fmt_pct(row.delta_position_pct),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _sqlite_readonly_url(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("long-term impact report currently supports sqlite file databases only")
    raw_path = database_url[len(prefix):]
    if raw_path == ":memory:":
        raise ValueError("read-only CLI requires a sqlite file database")
    path = Path(raw_path).expanduser().resolve()
    return f"sqlite:///file:{quote(str(path), safe='/:')}?mode=ro&uri=true"


@contextmanager
def readonly_session(database_url: str | None = None) -> Iterator[Session]:
    engine = create_engine(
        _sqlite_readonly_url(database_url or settings.database_url),
        connect_args={"check_same_thread": False, "uri": True},
    )
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--scope", choices=("test2", "all-active"), default="test2")
    parser.add_argument("--symbols", help="Comma-separated symbols; overrides --scope")
    parser.add_argument("--database-url", help="SQLite database URL; defaults to settings.database_url")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with readonly_session(args.database_url) as db:
        report = build_impact_report(db, scope=args.scope, symbols=args.symbols)
    if args.format == "json":
        print(report_to_json(report))
    else:
        print(report_to_markdown(report), end="")


if __name__ == "__main__":
    main()
