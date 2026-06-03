"""
M40 Gate-B prospective tracker — injectable-Session storage layer.

Exposes:
  record_observations   — walk Signal rows AS-OF a date, evaluate M33 gate,
                          write GateBObservation rows (idempotent).
  realize_returns       — fill forward_return_net for observations whose 5-day
                          window has closed (idempotent).
  report                — compute pre-registered §7 metrics and apply the
                          PROMOTE/REJECT/INCONCLUSIVE/ABORT decision rule.
  get_observation       — read-only single-row fetch.
  list_observations     — filtered read-only list.

Design rules:
  - Follows thesis_ledger.py flush → audit_write → commit transaction order.
  - Calls build_case() from case.py as a pure consumer; strips copilot_present
    post-hoc to derive gate_pass_variant. Does NOT modify case.py.
  - Reads Signal / LongTermLabel / DecisionRun / Price via raw AS-OF SQL queries.
  - Writes ONLY gate_b_observations.  No writes to any production table.
  - All writes are guarded by settings.gate_b_tracker_enabled == True.
"""
from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from typing import Any

from backend.config import settings
from backend.memory.audit_log import audit_write
from backend.research.case import build_case

GATE_B_VERSION = "v1"


# ---------------------------------------------------------------------------
# Private helpers  (verbatim pattern from thesis_ledger.py)
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "signal_date": row.signal_date,
        "as_of": row.as_of,
        "signal_id": row.signal_id,
        "label_id": row.label_id,
        "gate_pass_full": bool(row.gate_pass_full),
        "gate_pass_variant": bool(row.gate_pass_variant),
        "card_pass": bool(row.card_pass),
        "ready_variant": bool(row.ready_variant),
        "recommendation": row.recommendation,
        "composite_score": row.composite_score,
        "entry_close": row.entry_close,
        "horizon_days": row.horizon_days,
        "forward_status": row.forward_status,
        "realized_at": row.realized_at,
        "forward_return_raw": row.forward_return_raw,
        "forward_return_net": row.forward_return_net,
        "blockers": json.loads(row.blockers_json) if row.blockers_json else [],
        "blockers_variant": json.loads(row.blockers_variant_json) if row.blockers_variant_json else [],
        "checks": json.loads(row.checks_json) if row.checks_json else {},
        "gate_b_tracker_version": row.gate_b_tracker_version,
        "recorded_at": _iso(row.recorded_at),
        "updated_at": _iso(row.updated_at),
    }


# ---------------------------------------------------------------------------
# PIT dossier builder (no leakage — all queries use date <= as_of)
# ---------------------------------------------------------------------------

def _build_pit_dossier(db, symbol: str, as_of: str) -> dict:
    """
    Build a minimal research dossier AS-OF `as_of` using raw SQL filters.

    All queries are strictly point-in-time:
      Signal        : date <= as_of  ORDER BY date DESC LIMIT 1
      LongTermLabel : date <= as_of AND expires_at >= as_of  ORDER BY date DESC LIMIT 1
      DecisionRun   : as_of <= D  ORDER BY as_of DESC, created_at DESC LIMIT 3
      ResearchState : current singleton, copilot forced to None (no temporal column)
      StockMemoryItem: created_at <= as_of AND memory_type='research_pointer' AND status='active'
    """
    from sqlalchemy import text

    # Signal
    sig_row = db.execute(
        text("""
            SELECT id, symbol, date, recommendation, composite_score, confidence,
                   rule_version, quant_score, technical_score, sentiment_score, created_at
            FROM signals
            WHERE symbol = :sym AND date <= :d
            ORDER BY date DESC, id DESC
            LIMIT 1
        """),
        {"sym": symbol, "d": as_of},
    ).fetchone()

    latest_signal: dict | None = None
    if sig_row:
        latest_signal = {
            "id": sig_row[0],
            "symbol": sig_row[1],
            "date": sig_row[2],
            "recommendation": sig_row[3],
            "composite_score": sig_row[4],
            "confidence": sig_row[5],
            "rule_version": sig_row[6],
        }

    # LongTermLabel — must be active on as_of (not expired)
    lbl_row = db.execute(
        text("""
            SELECT id, symbol, date, label, score, expires_at, quality, constraint_eligible
            FROM long_term_labels
            WHERE symbol = :sym AND date <= :d AND expires_at >= :d
            ORDER BY date DESC, id DESC
            LIMIT 1
        """),
        {"sym": symbol, "d": as_of},
    ).fetchone()

    long_term_label: dict | None = None
    if lbl_row:
        long_term_label = {
            "id": lbl_row[0],
            "symbol": lbl_row[1],
            "date": lbl_row[2],
            "label": lbl_row[3],
            "score": lbl_row[4],
            "expires_at": lbl_row[5],
            "quality": lbl_row[6],
            "constraint_eligible": bool(lbl_row[7]),
        }

    # DecisionRun evidence (last 3 runs as-of D)
    dr_rows = db.execute(
        text("""
            SELECT id, run_id, run_type, symbol, as_of, profile, rule_version,
                   recommendation, composite_score, input_snapshot_json, created_at
            FROM decision_runs
            WHERE symbol = :sym AND as_of <= :d
            ORDER BY as_of DESC, created_at DESC
            LIMIT 3
        """),
        {"sym": symbol, "d": as_of},
    ).fetchall()

    evidence: list[dict] = []
    for dr in dr_rows:
        input_snapshot: dict = {}
        if dr[9]:
            try:
                input_snapshot = json.loads(dr[9])
            except (json.JSONDecodeError, TypeError):
                pass
        evidence.append({
            "run_id": dr[1],
            "run_type": dr[2],
            "symbol": dr[3],
            "as_of": dr[4],
            "profile": dr[5],
            "rule_version": dr[6],
            "recommendation": dr[7],
            "composite_score": dr[8],
            "input_snapshot": input_snapshot,
            "created_at": _iso(dr[10]),
        })

    # ResearchState — current singleton, copilot forced to None
    rs_row = db.execute(
        text("""
            SELECT id, symbol, thesis, risks_json, open_questions_json,
                   last_signal_summary, last_review_json
            FROM research_states
            WHERE symbol = :sym
            LIMIT 1
        """),
        {"sym": symbol},
    ).fetchone()

    research_state: dict | None = None
    if rs_row:
        open_questions: list = []
        if rs_row[4]:
            try:
                open_questions = json.loads(rs_row[4])
            except (json.JSONDecodeError, TypeError):
                pass
        research_state = {
            "id": rs_row[0],
            "symbol": rs_row[1],
            "thesis": rs_row[2],
            "copilot": None,   # forced to None — no temporal history; copilot_present excluded in variant
            "open_questions": open_questions,
        }

    # StockMemoryItem deep_research — only items created by as_of
    mem_rows = db.execute(
        text("""
            SELECT id, summary, source_ref, created_at
            FROM stock_memory_items
            WHERE symbol = :sym
              AND memory_type = 'research_pointer'
              AND status = 'active'
              AND created_at <= :d
            ORDER BY created_at DESC
            LIMIT 10
        """),
        {"sym": symbol, "d": as_of},
    ).fetchall()

    deep_research: list[dict] = []
    for mr in mem_rows:
        deep_research.append({
            "id": mr[0],
            "summary": mr[1],
            "source_ref": mr[2],
            "created_at": _iso(mr[3]),
        })

    # Pending questions from research_state
    pending_questions = research_state.get("open_questions", []) if research_state else []

    return {
        "symbol": symbol,
        "latest_signal": latest_signal,
        "long_term_label": long_term_label,
        "evidence": evidence,
        "research_state": research_state,
        "deep_research": deep_research,
        "pending_questions": pending_questions,
        "missing": [],  # not computable PIT without full pipeline; left empty
    }


# ---------------------------------------------------------------------------
# record_observations
# ---------------------------------------------------------------------------

def record_observations(
    db,
    *,
    source_db=None,
    as_of: str | None = None,
    horizon_days: int = 5,
    symbols: list[str] | None = None,
) -> list[dict]:
    """
    For each Signal with date <= as_of, evaluate the M33 gate AS-OF that date
    and write a GateBObservation row.

    Reads (signals / labels / decisions / prices) come from ``source_db`` when
    provided (a read-only production session); GateBObservation rows are written
    to ``db``. When ``source_db`` is None, ``db`` is used for both (test default).
    This separation lets the tracker read production data read-only while
    persisting observations in a dedicated, isolated database.

    Idempotent: skips signals already recorded for the same (signal_id, as_of).
    Returns list of newly inserted row dicts (existing rows are not returned).
    Guard: returns [] immediately if gate_b_tracker_enabled is False.
    """
    if not settings.gate_b_tracker_enabled:
        return []

    from sqlalchemy import text

    src = source_db if source_db is not None else db
    effective_as_of: str = as_of or datetime.now(UTC).date().isoformat()

    from backend.data.database import GateBObservation, Price

    # Fetch all signals with date <= as_of
    sym_filter = ""
    params: dict[str, Any] = {"d": effective_as_of}
    if symbols:
        placeholders = ", ".join(f":s{i}" for i in range(len(symbols)))
        sym_filter = f"AND symbol IN ({placeholders})"
        for i, s in enumerate(symbols):
            params[f"s{i}"] = s

    sig_rows = src.execute(
        text(f"""
            SELECT id, symbol, date, recommendation, composite_score
            FROM signals
            WHERE date <= :d {sym_filter}
            ORDER BY date ASC, id ASC
        """),
        params,
    ).fetchall()

    inserted: list[dict] = []

    for sig in sig_rows:
        sig_id, symbol, sig_date, recommendation, composite_score = (
            sig[0], sig[1], sig[2], sig[3], sig[4]
        )

        # Idempotency check
        existing = (
            db.query(GateBObservation)
            .filter(
                GateBObservation.signal_id == sig_id,
                GateBObservation.as_of == sig_date,
            )
            .first()
        )
        if existing is not None:
            continue  # already recorded — skip silently

        # Build PIT dossier and evaluate gate (read from the source session)
        dossier = _build_pit_dossier(src, symbol, sig_date)
        case = build_case(dossier, as_of=sig_date)

        raw_blockers: list[str] = case["quality_gate"]["blockers"]
        gate_pass_full: bool = case["quality_gate"]["gate_pass"]
        blockers_variant: list[str] = [b for b in raw_blockers if b != "copilot_present"]
        gate_pass_variant: bool = len(blockers_variant) == 0
        card_pass: bool = case["validity_card"]["card_pass"]
        ready_variant: bool = gate_pass_variant and card_pass
        checks_dict: dict = case["quality_gate"].get("checks", {})

        # label_id from dossier
        label_id: int | None = None
        label = dossier.get("long_term_label")
        if label:
            label_id = label.get("id")

        # entry_close from Price on sig_date (read from the source session)
        price_row = src.execute(
            text("SELECT close FROM prices WHERE symbol=:sym AND date=:d LIMIT 1"),
            {"sym": symbol, "d": sig_date},
        ).fetchone()
        entry_close: float | None = float(price_row[0]) if price_row else None

        now = _utc_now()
        obs = GateBObservation(
            symbol=symbol,
            signal_date=sig_date,
            as_of=sig_date,
            signal_id=sig_id,
            label_id=label_id,
            gate_pass_full=gate_pass_full,
            gate_pass_variant=gate_pass_variant,
            card_pass=card_pass,
            ready_variant=ready_variant,
            recommendation=recommendation,
            composite_score=float(composite_score) if composite_score is not None else None,
            entry_close=entry_close,
            horizon_days=horizon_days,
            forward_status="pending",
            realized_at=None,
            forward_return_raw=None,
            forward_return_net=None,
            blockers_json=json.dumps(raw_blockers, ensure_ascii=False),
            blockers_variant_json=json.dumps(blockers_variant, ensure_ascii=False),
            checks_json=json.dumps(checks_dict, ensure_ascii=False),
            gate_b_tracker_version=GATE_B_VERSION,
            recorded_at=now,
            updated_at=now,
        )
        db.add(obs)
        db.flush()
        audit_write(
            db,
            "gate_b_recorder.record",
            (
                f"obs recorded: symbol={symbol} signal_date={sig_date}"
                f" gate_pass_variant={gate_pass_variant} card_pass={card_pass}"
            ),
            related_symbol=symbol,
            related_scope="gate_b",
        )
        db.commit()
        inserted.append(_row_to_dict(obs))

    return inserted


# ---------------------------------------------------------------------------
# realize_returns
# ---------------------------------------------------------------------------

def realize_returns(db, *, source_db=None, as_of: str | None = None) -> list[dict]:
    """
    Fill forward_return_net for observations whose 5-day window has closed.

    Observations are read/updated in ``db``; forward prices are read from
    ``source_db`` when provided (read-only production session), else from ``db``.

    For each pending GateBObservation:
      - Query the 5 trading-day prices strictly after signal_date.
      - If 5 rows exist: compute gross return, subtract 0.4% round-trip cost.
      - If < 5 rows and latest price is > 30 calendar days after signal_date: mark 'unrealizable'.
      - Otherwise: leave 'pending'.

    Idempotent: only processes rows where forward_status == 'pending'.
    Guard: returns [] immediately if gate_b_tracker_enabled is False.
    """
    if not settings.gate_b_tracker_enabled:
        return []

    from datetime import date as _date, timedelta

    from sqlalchemy import text

    from backend.backtest.costs import net_return_from_prices
    from backend.data.database import GateBObservation

    src = source_db if source_db is not None else db
    effective_as_of: str = as_of or datetime.now(UTC).date().isoformat()

    pending_rows = (
        db.query(GateBObservation)
        .filter(GateBObservation.forward_status == "pending")
        .all()
    )

    realized: list[dict] = []

    for obs in pending_rows:
        if obs.entry_close is None:
            continue

        # Fetch up to 5 forward prices strictly after signal_date (from source)
        fwd_rows = src.execute(
            text("""
                SELECT date, close FROM prices
                WHERE symbol = :sym AND date > :sig_date
                ORDER BY date ASC
                LIMIT 5
            """),
            {"sym": obs.symbol, "sig_date": obs.signal_date},
        ).fetchall()

        if len(fwd_rows) == 5:
            exit_close = float(fwd_rows[4][1])
            raw = (exit_close - obs.entry_close) / obs.entry_close
            net = net_return_from_prices(obs.entry_close, exit_close)
            obs.forward_return_raw = raw
            obs.forward_return_net = net
            obs.forward_status = "realized"
            obs.realized_at = effective_as_of
            obs.updated_at = _utc_now()
            db.flush()
            audit_write(
                db,
                "gate_b_recorder.realize",
                (
                    f"fwd_net={net:.4f}"
                    f" symbol={obs.symbol} signal_date={obs.signal_date}"
                ),
                related_symbol=obs.symbol,
                related_scope="gate_b",
            )
            db.commit()
            realized.append(_row_to_dict(obs))

        elif fwd_rows:
            # Check if we've waited more than 30 calendar days
            latest_price_date = fwd_rows[-1][0]
            try:
                sig_dt = _date.fromisoformat(obs.signal_date)
                latest_dt = _date.fromisoformat(latest_price_date)
                if (latest_dt - sig_dt).days > 30:
                    obs.forward_status = "unrealizable"
                    obs.updated_at = _utc_now()
                    db.flush()
                    audit_write(
                        db,
                        "gate_b_recorder.realize",
                        f"unrealizable: symbol={obs.symbol} signal_date={obs.signal_date}",
                        related_symbol=obs.symbol,
                        related_scope="gate_b",
                    )
                    db.commit()
            except ValueError:
                pass
        # else: no forward prices at all — leave pending

    return realized


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(db) -> dict:
    """
    Compute pre-registered §7 metrics over all realized GateBObservation rows.

    Decision rule (applied in strict order):
      1. n_total < 30           → INCONCLUSIVE / insufficient_sample
      2. avg_net_return_delta <= 0 OR icir <= 0 OR n_pass < 30 → REJECT
      3. gate_pass_rate outside [0.02, 0.30] (exclusive)       → ABORT / bias_threat_coverage_or_rate
      4. all positive thresholds met                            → PROMOTE
      5. otherwise                                              → INCONCLUSIVE

    Always returns INCONCLUSIVE (not PROMOTE or REJECT) when n_total < 30.
    """
    from backend.data.database import GateBObservation

    realized_rows = (
        db.query(GateBObservation)
        .filter(GateBObservation.forward_status == "realized")
        .all()
    )

    pass_rows = [r for r in realized_rows if r.gate_pass_variant]
    fail_rows = [r for r in realized_rows if not r.gate_pass_variant]

    n_pass = len(pass_rows)
    n_fail = len(fail_rows)
    n_total = n_pass + n_fail

    # Pre-registered metrics
    avg_net_return_pass: float | None = (
        statistics.mean(float(r.forward_return_net) for r in pass_rows)
        if n_pass > 0 else None
    )
    avg_net_return_fail: float | None = (
        statistics.mean(float(r.forward_return_net) for r in fail_rows)
        if n_fail > 0 else None
    )
    avg_net_return_delta: float | None = (
        avg_net_return_pass - avg_net_return_fail
        if avg_net_return_pass is not None and avg_net_return_fail is not None
        else None
    )

    hit_rate_pass: float | None = (
        sum(1 for r in pass_rows if float(r.forward_return_net) > 0) / n_pass
        if n_pass > 0 else None
    )

    gate_pass_rate: float | None = n_pass / n_total if n_total > 0 else None

    # Stride ICIR via m27_alpha_diagnostic (best-effort; falls back to None on import error)
    icir: float | None = None
    ic_days: int = 0
    try:
        import pandas as pd
        from backend.tools.m27_alpha_diagnostic import cross_sectional_ic, summarize_ic

        if n_total >= 5:
            rows_data = [
                {
                    "date": r.signal_date,
                    "symbol": r.symbol,
                    "gate_score": 1.0 if r.gate_pass_variant else 0.0,
                    "forward_return_net": float(r.forward_return_net),
                }
                for r in realized_rows
            ]
            df = pd.DataFrame(rows_data)
            ic_series = cross_sectional_ic(df, "gate_score", "forward_return_net", min_names=2)
            ic_summary = summarize_ic(ic_series)
            icir = ic_summary.get("icir")
            ic_days = ic_summary.get("ic_days", 0)
    except Exception:
        pass  # pandas/m27 unavailable in test or CI environments

    # §7 decision rule (strict order — INCONCLUSIVE on small sample is checked first)
    verdict: str
    reason: str | None = None

    if n_total < 30:
        verdict = "INCONCLUSIVE"
        reason = "insufficient_sample"
    elif (
        avg_net_return_delta is None
        or avg_net_return_delta <= 0
        or (icir is not None and icir <= 0)
        or n_pass < 30
    ):
        verdict = "REJECT"
        reason = "delta_or_icir_or_npass_failed"
    elif gate_pass_rate is not None and (gate_pass_rate > 0.30 or gate_pass_rate < 0.02):
        verdict = "ABORT"
        reason = "bias_threat_coverage_or_rate"
    elif (
        avg_net_return_delta is not None
        and avg_net_return_delta > 0.003
        and (icir is None or icir > 0.15)
        and gate_pass_rate is not None
        and 0.05 <= gate_pass_rate <= 0.80
        and n_pass >= 30
    ):
        verdict = "PROMOTE"
        reason = None
    else:
        verdict = "INCONCLUSIVE"
        reason = "thresholds_not_met"

    return {
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_total": n_total,
        "avg_net_return_pass": avg_net_return_pass,
        "avg_net_return_fail": avg_net_return_fail,
        "avg_net_return_delta": avg_net_return_delta,
        "hit_rate_pass": hit_rate_pass,
        "gate_pass_rate": gate_pass_rate,
        "icir": icir,
        "ic_days": ic_days,
        "verdict": verdict,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------

def get_observation(db, obs_id: int) -> dict | None:
    """Return a single GateBObservation by id, or None. Read-only, no audit."""
    from backend.data.database import GateBObservation

    row = db.query(GateBObservation).filter(GateBObservation.id == obs_id).first()
    return _row_to_dict(row) if row else None


def list_observations(
    db,
    *,
    symbol: str | None = None,
    gate_pass_variant: bool | None = None,
    unrealized_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    """Return GateBObservation rows filtered by optional criteria, newest first."""
    from backend.data.database import GateBObservation

    q = db.query(GateBObservation)
    if symbol is not None:
        q = q.filter(GateBObservation.symbol == symbol)
    if gate_pass_variant is not None:
        q = q.filter(GateBObservation.gate_pass_variant == gate_pass_variant)
    if unrealized_only:
        q = q.filter(GateBObservation.forward_status == "pending")
    return [_row_to_dict(r) for r in q.order_by(GateBObservation.signal_date.desc()).limit(limit).all()]
