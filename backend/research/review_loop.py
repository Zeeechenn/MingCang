"""
M37 Review / Calibration / Memory Loop — pure storage layer.

Exposes ten injectable-Session functions:
  create_review_case, get_review_case, list_review_cases,
  create_memory_candidate, get_memory_candidate, list_memory_candidates,
  promote_memory, reject_memory_candidate,
  attach_independent_review, run_independent_review (pure, no Session)

No LLM calls. No writes to Signal / DecisionRun / M29 / ai_memory tables.
Memory candidates are ALWAYS created in 'pending' state.
Promotion to 'trusted' is only possible via the explicit gated promote_memory
function, which is never called from any LLM agent code path.
Routes deferred to M40.

M55 Phase 2 addition (graft, not rebuild): `run_independent_review` /
`IndependentReviewVerdict` / `attach_independent_review` port the checklist
dimensions from zad's "independent reviewer sub-agent" step (see
docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md mapping table #1/#8) onto this
module's existing ReviewCase storage primitive instead of building a second
review system. Still no LLM calls here: the actual independent
re-verification (fresh-context sub-agent, adversarial stance) happens
OUTSIDE this module; `run_independent_review` is the deterministic
structural gate that checks the reviewer's own output is complete
(mirrors how research_report_gate checks a DeepResearchReport), and
`attach_independent_review` records that verdict onto the ReviewCase it
belongs to. Verdicts are pass/revise only — no score/vote field, matching
the same non-promoting invariant as the rest of this module.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.memory.audit_log import audit_write
from backend.memory.stock_memory import MEMORY_TYPES
from backend.observability import get_correlation_id

CANDIDATE_TRUST_VALUES = {"pending", "trusted", "rejected"}


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _rc_to_dict(row) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "as_of": row.as_of,
        "signal_id": row.signal_id,
        "thesis_id": row.thesis_id,
        "research_case_symbol": row.research_case_symbol,
        "research_case_as_of": row.research_case_as_of,
        "position_case_ref_json": row.position_case_ref_json,
        "outcome_correct": row.outcome_correct,
        "next_day_return": row.next_day_return,
        "composite_score": row.composite_score,
        "recommendation": row.recommendation,
        "attribution": json.loads(row.attribution_json) if row.attribution_json else None,
        "review_payload": json.loads(row.review_payload_json) if row.review_payload_json else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _cand_to_dict(row) -> dict:
    return {
        "id": row.id,
        "review_case_id": row.review_case_id,
        "memory_atom_id": row.memory_atom_id,
        "stock_memory_item_id": row.stock_memory_item_id,
        "symbol": row.symbol,
        "summary": row.summary,
        "memory_type": row.memory_type,
        "source_trust": row.source_trust,
        "source_ref": row.source_ref,
        "importance": row.importance,
        "confidence": row.confidence,
        "promoted_at": _iso(row.promoted_at),
        "rejected_at": _iso(row.rejected_at),
        "note": row.note,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# ── ReviewCase CRUD ──────────────────────────────────────────────────────────

def create_review_case(
    db,
    *,
    symbol: str,
    as_of: str,
    signal_id: int | None = None,
    thesis_id: int | None = None,
    research_case_as_of: str | None = None,
    review_payload: dict | None = None,
) -> dict:
    """Insert a ReviewCase row and return its dict representation.

    Idempotent: if a row with the same (symbol, as_of) already exists
    (UniqueConstraint) the existing row is returned without modification.
    Outcome data (outcome_correct, next_day_return, composite_score,
    recommendation, attribution_json, review_payload_json) is extracted
    from review_payload when provided.
    Always calls audit_write after a successful insert.
    """
    from backend.data.database import ReviewCase

    existing = (
        db.query(ReviewCase)
        .filter(ReviewCase.symbol == symbol, ReviewCase.as_of == as_of)
        .first()
    )
    if existing is not None:
        return _rc_to_dict(existing)

    # Extract outcome fields from review_payload if present
    outcome_correct = None
    next_day_return = None
    composite_score = None
    recommendation = None
    attribution_json = None
    review_payload_json = None

    if review_payload is not None:
        outcome_correct = review_payload.get("correct")
        next_day_return = review_payload.get("next_day_return")
        composite_score = review_payload.get("composite_score")
        recommendation = review_payload.get("recommendation")
        attribution = review_payload.get("attribution")
        if attribution is not None:
            attribution_json = json.dumps(attribution, ensure_ascii=False)
        review_payload_json = json.dumps(review_payload, ensure_ascii=False, default=str)

    now = _utc_now()
    row = ReviewCase(
        symbol=symbol,
        as_of=as_of,
        signal_id=signal_id,
        thesis_id=thesis_id,
        research_case_symbol=symbol,
        research_case_as_of=research_case_as_of,
        outcome_correct=outcome_correct,
        next_day_return=next_day_return,
        composite_score=composite_score,
        recommendation=recommendation,
        attribution_json=attribution_json,
        review_payload_json=review_payload_json,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    audit_write(
        db,
        "review_loop.create_review_case",
        f"review_case created symbol={symbol} as_of={as_of}",
        related_symbol=symbol,
    )
    db.commit()
    return _rc_to_dict(row)


def get_review_case(db, review_case_id: int) -> dict | None:
    """Return the ReviewCase with the given id, or None. (read-only, no audit)"""
    from backend.data.database import ReviewCase

    row = db.query(ReviewCase).filter(ReviewCase.id == review_case_id).first()
    return _rc_to_dict(row) if row is not None else None


def list_review_cases(
    db,
    *,
    symbol: str | None = None,
    thesis_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return review cases filtered by symbol and/or thesis_id, sorted by as_of DESC."""
    from backend.data.database import ReviewCase

    q = db.query(ReviewCase)
    if symbol is not None:
        q = q.filter(ReviewCase.symbol == symbol)
    if thesis_id is not None:
        q = q.filter(ReviewCase.thesis_id == thesis_id)
    rows = q.order_by(ReviewCase.as_of.desc()).limit(limit).all()
    return [_rc_to_dict(r) for r in rows]


# ── MemoryPromotionCandidate CRUD ─────────────────────────────────────────────

def create_memory_candidate(
    db,
    *,
    review_case_id: int | None = None,
    symbol: str,
    summary: str,
    memory_type: str,
    importance: int = 3,
    confidence: float = 0.5,
    source_ref: str | None = None,
    note: str | None = None,
) -> dict:
    """Insert a MemoryPromotionCandidate with source_trust='pending' (hardcoded).

    source_trust is NOT accepted as a parameter — callers cannot override it.
    The only path to 'trusted' is the gated promote_memory function.

    Idempotent only when review_case_id or source_ref provides an explicit key.
    When a key is present, both review_case_id and source_ref participate in the
    match, with NULL matched explicitly. This prevents a broad source_ref rerun
    from swallowing a later case-specific lesson. Calls without either key
    always create a new candidate so unrelated lessons are not merged broadly.
    Raises ValueError on invalid memory_type.
    Always calls audit_write after a successful insert.
    """
    if memory_type not in MEMORY_TYPES:
        raise ValueError(
            f"invalid memory_type: {memory_type!r}; must be one of {MEMORY_TYPES}"
        )

    from backend.data.database import MemoryPromotionCandidate

    if review_case_id is not None or source_ref is not None:
        q = (
            db.query(MemoryPromotionCandidate)
            .filter(
                MemoryPromotionCandidate.symbol == symbol,
                MemoryPromotionCandidate.memory_type == memory_type,
                MemoryPromotionCandidate.source_trust == "pending",
            )
        )
        if review_case_id is not None:
            q = q.filter(MemoryPromotionCandidate.review_case_id == review_case_id)
        else:
            q = q.filter(MemoryPromotionCandidate.review_case_id.is_(None))
        if source_ref is not None:
            q = q.filter(MemoryPromotionCandidate.source_ref == source_ref)
        else:
            q = q.filter(MemoryPromotionCandidate.source_ref.is_(None))
        existing = q.first()
        if existing is not None:
            return _cand_to_dict(existing)

    now = _utc_now()
    row = MemoryPromotionCandidate(
        review_case_id=review_case_id,
        symbol=symbol,
        summary=summary,
        memory_type=memory_type,
        source_trust="pending",  # hardcoded — no caller override possible
        source_ref=source_ref,
        importance=max(1, min(5, int(importance))),
        confidence=max(0.0, min(1.0, float(confidence))),
        note=note,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    correlation_id = get_correlation_id()
    trace_suffix = f" correlation_id={correlation_id}" if correlation_id else ""
    audit_write(
        db,
        "review_loop.create_memory_candidate",
        f"candidate created symbol={symbol} type={memory_type} trust=pending{trace_suffix}",
        related_symbol=symbol,
    )
    db.commit()
    return _cand_to_dict(row)


def get_memory_candidate(db, candidate_id: int) -> dict | None:
    """Return the MemoryPromotionCandidate with the given id, or None. (read-only)"""
    from backend.data.database import MemoryPromotionCandidate

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    return _cand_to_dict(row) if row is not None else None


def list_memory_candidates(
    db,
    *,
    symbol: str | None = None,
    source_trust: str | None = None,
    review_case_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return candidates filtered by symbol, source_trust, and/or review_case_id,
    sorted by created_at DESC."""
    from backend.data.database import MemoryPromotionCandidate

    q = db.query(MemoryPromotionCandidate)
    if symbol is not None:
        q = q.filter(MemoryPromotionCandidate.symbol == symbol)
    if source_trust is not None:
        q = q.filter(MemoryPromotionCandidate.source_trust == source_trust)
    if review_case_id is not None:
        q = q.filter(MemoryPromotionCandidate.review_case_id == review_case_id)
    rows = q.order_by(MemoryPromotionCandidate.created_at.desc()).limit(limit).all()
    return [_cand_to_dict(r) for r in rows]


# ── Gated promotion / rejection ───────────────────────────────────────────────
# These functions are the ONLY path to 'trusted' / 'rejected'.
# They are NOT imported or called from any LLM agent code path
# (backend/agents/, backend/decision/harness.py, backend/skills/).
# Routes that call them are deferred to M40.

def promote_memory(db, candidate_id: int, *, confirmed_by: str) -> dict:
    """GATED: Promote a pending candidate to 'trusted' and materialise a StockMemoryItem.

    This is the ONLY function that writes source_trust='trusted'.
    It also creates/updates a StockMemoryItem with status='active' and stores
    the returned row id in stock_memory_item_id.
    Raises ValueError if the candidate is not in 'pending' state.
    Always calls audit_write on success.

    confirmed_by: str identifying the human actor confirming this promotion.
    """
    from backend.data.database import MemoryPromotionCandidate
    from backend.memory.stock_memory import create_stock_memory

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    if row is None:
        raise ValueError(f"memory candidate {candidate_id} not found")
    if row.source_trust != "pending":
        raise ValueError(
            f"candidate {candidate_id} is already in state {row.source_trust!r}; "
            "only 'pending' candidates can be promoted"
        )

    atom_source_ref = (
        row.source_ref
        or f"m37_candidate_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    from backend.memory.l0_memory import create_memory_atom, promote_atom

    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
    )

    # Materialise the candidate as a legacy StockMemoryItem for compatibility.
    source_ref = (
        row.source_ref
        or f"m37_promotion_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    mem = create_stock_memory(
        db,
        symbol=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion",
        source_ref=source_ref,
        importance=row.importance,
        confidence=row.confidence,
        status="active",
        evidence={"memory_atom_id": atom["id"], "review_case_id": row.review_case_id},
    )
    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_promotion_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
            "stock_memory_item_id": mem["id"],
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
        stock_memory_item_id=mem["id"],
    )
    atom = promote_atom(db, atom["id"], confirmed_by=confirmed_by)

    now = _utc_now()
    row.source_trust = "trusted"
    row.memory_atom_id = atom["id"]
    row.stock_memory_item_id = mem["id"]
    row.promoted_at = now
    row.updated_at = now
    db.flush()

    audit_write(
        db,
        "memory_promotion.confirm",
        (
            f"candidate {candidate_id} promoted by {confirmed_by!r}; "
            f"memory_atom_id={atom['id']} stock_memory_item_id={mem['id']} "
            f"symbol={row.symbol}"
        ),
        related_symbol=row.symbol,
    )
    db.commit()
    return _cand_to_dict(row)


def reject_memory_candidate(
    db,
    candidate_id: int,
    *,
    confirmed_by: str,
    note: str | None = None,
) -> dict:
    """GATED: Reject a pending candidate (terminal state — no further transitions).

    This is the ONLY function that writes source_trust='rejected'.
    Raises ValueError if the candidate is not in 'pending' state.
    Always calls audit_write on success.

    confirmed_by: str identifying the human actor confirming this rejection.
    """
    from backend.data.database import MemoryPromotionCandidate

    row = (
        db.query(MemoryPromotionCandidate)
        .filter(MemoryPromotionCandidate.id == candidate_id)
        .first()
    )
    if row is None:
        raise ValueError(f"memory candidate {candidate_id} not found")
    if row.source_trust != "pending":
        raise ValueError(
            f"candidate {candidate_id} is already in state {row.source_trust!r}; "
            "only 'pending' candidates can be rejected"
        )

    atom_source_ref = (
        row.source_ref
        or f"m37_rejected_{candidate_id}_{row.symbol}_{row.memory_type}"
    )
    from backend.memory.l0_memory import create_memory_atom, refute_atom

    atom = create_memory_atom(
        db,
        scope_type="stock",
        scope_key=row.symbol,
        memory_type=row.memory_type,
        summary=row.summary,
        source_type="m37_rejected_candidate",
        source_ref=f"l0:{atom_source_ref}",
        trust_state="pending",
        evidence={
            "candidate_id": candidate_id,
            "review_case_id": row.review_case_id,
            "candidate_source_ref": row.source_ref,
            "confirmed_by": confirmed_by,
        },
        importance=row.importance,
        confidence=row.confidence,
        review_case_id=row.review_case_id,
    )
    atom = refute_atom(db, atom["id"], confirmed_by=confirmed_by, reason=note)

    now = _utc_now()
    row.source_trust = "rejected"
    row.memory_atom_id = atom["id"]
    row.rejected_at = now
    row.updated_at = now
    if note:
        row.note = note
    db.flush()

    audit_write(
        db,
        "memory_promotion.reject",
        (
            f"candidate {candidate_id} rejected by {confirmed_by!r}; "
            f"symbol={row.symbol}"
            + (f"; note={note!r}" if note else "")
        ),
        related_symbol=row.symbol,
    )
    db.commit()
    return _cand_to_dict(row)


# ── Independent review checklist (M55 Phase 2 graft) ─────────────────────────
# Ports zad's "independent reviewer sub-agent" checklist dimensions onto this
# module's existing ReviewCase storage primitive. See module docstring.

DEGRADED_REVIEW_TAG = "[未独立复核]"

# zad SKILL.md: "独立联网重核 ≥3 个关键数字" — floor for how many measurable
# claims a reviewer must have independently re-verified before a report can
# pass on the fabrication/sourcing dimension.
MIN_INDEPENDENT_REVERIFY = 3

# Internal codename / methodology-label leakage this reviewer step must catch
# in the reviewer's own findings text and in any rendered_text it is given —
# narrow, review-scoped list (the full dossier-level Chinese-wording gate
# lives in dossier.py; not duplicated here).
_INTERNAL_JARGON_PATTERNS: tuple[str, ...] = (
    "信念档", "五连判", "用户头", "硬否", "不具身", "量价双控",
    "OSINT 推断", "已证实供货关系", "纯推测",
)

_BOLD_MARKER_PATTERN = re.compile(r"\*\*[^*]+\*\*")
_MAX_BOLD_MARKERS = 25

_STRONG_EVIDENCE_TIERS = frozenset({"primary", "official", "filing"})


@dataclass(frozen=True)
class IndependentReviewVerdict:
    """Result of run_independent_review.

    status: 'pass' | 'revise' (no score/vote field — matches this module's
      non-promoting invariant; see test_no_direct_trusted_write_path-style
      guards elsewhere in this file).
    findings: human-readable list of concrete problems found, most-severe
      dimension first (fabrication/sourcing, then omission, then logic/bias,
      then catering, then readability).
    degraded: True when sub_agent_available=False — this verdict is a
      self-check stopgap, not a true independent review (zad "无 sub-agent
      环境降级路径"). Callers must never treat degraded=True the same as a
      real independent pass.
    """

    status: str
    findings: list[str] = field(default_factory=list)
    degraded: bool = False


def run_independent_review(
    *,
    claims: list[dict] | None = None,
    bear_before_bull: bool = True,
    falsification_questions: list[str] | None = None,
    user_directional_hint: bool = False,
    counter_pressure_applied: bool = False,
    omission_checklist: dict[str, bool] | None = None,
    catering_check_passed: bool = True,
    rendered_text: str = "",
    sub_agent_available: bool = True,
) -> IndependentReviewVerdict:
    """Independent-reviewer checklist (M55 graft of zad's reviewer sub-agent).

    Pure, deterministic, no Session, no LLM calls, no network I/O. This
    function does NOT itself re-verify facts — the actual independent
    re-verification (fresh-context sub-agent, adversarial "挑刺, not
    背书" stance, opus-class model) must happen OUTSIDE this function, by an
    agent that did not write the report under review (self-review is
    invalid — zad: "reviewer 不把分析者的推理当权威"). This function is the
    deterministic gate that checks the *reviewer's own output* is complete
    and internally consistent, the same relationship
    research_report_gate.run_research_report_gate has to a DeepResearchReport.

    Five checked dimensions, ported from zad's "最后一步:独立复核" (highest
    severity first):

    1. 编造/取数 (fabrication / sourcing — zad's highest-frequency failure
       mode). Checked via ``claims``: list of dicts, one per measurable
       claim the reviewer looked at —
         - description: str
         - value_type: 'measurable' | 'qualitative' (default 'measurable')
         - label: '已证实' | '管理层声称' | '我的推断' | '纯推测'
         - source_ref: str | None
         - evidence_tier: SourceTier value (primary/official/filing/ir/
           industry/social_lead) | None
         - fast_changing: bool — backlog/orders/guidance/customer-list style
           fields that need a dedicated as-of-minus-60-days re-search
         - independently_reverified: bool — reviewer re-checked this claim
           against an independent/fresh source, not just re-read the
           original text
       Flags both directions: an unverified/inferred claim mislabeled
       '已证实', AND a well-sourced claim mislabeled as inference/guess (the
       10-K-already-named-it-but-we-called-it-unverified failure mode).
       Also flags fast-changing fields never independently reverified, and
       an overall reverified-claim count below MIN_INDEPENDENT_REVERIFY.
    2. 重大遗漏 (material omission): ``omission_checklist`` is a dict of
       checklist-item -> whether the reviewer actually confirmed it (e.g.
       regulatory investigation, major-customer concentration, stale
       customer list). Any unconfirmed item is flagged.
    3. 逻辑 + 反偏误: ``bear_before_bull`` must be True (risk section written
       before bull section); ``falsification_questions`` must be non-empty;
       when ``user_directional_hint`` is True (the user's own wording leaned
       toward wanting a buy/positive answer), ``counter_pressure_applied``
       must also be True, or it is flagged.
    4. 迎合 (catering to user / narrative momentum): ``catering_check_passed``
       is the reviewer's own attestation that the conclusion was checked
       against "is this just telling the user what they want to hear".
    5. 可读性 (Chinese-output jargon leak + bold overuse): when
       ``rendered_text`` is supplied, scans for internal-codename leakage
       and counts markdown bold markers against _MAX_BOLD_MARKERS.

    ``sub_agent_available=False`` activates zad's degradation path ("无
    sub-agent 环境降级路径"): the verdict is marked ``degraded=True`` and
    every finding is prefixed with DEGRADED_REVIEW_TAG so callers can never
    mistake a self-check stopgap for a true independent review — the
    conclusion should be reported to the user as degraded and/or have its
    confidence band lowered by one notch.
    """
    findings: list[str] = []
    claims = claims or []

    # 1. 编造/取数 (fabrication & sourcing)
    measurable = [c for c in claims if c.get("value_type", "measurable") == "measurable"]
    for c in measurable:
        desc = c.get("description", "<unlabeled>")
        label = c.get("label")
        tier = c.get("evidence_tier")
        source_ref = c.get("source_ref")

        if label == "已证实" and not source_ref:
            findings.append(
                f"编造/取数：'{desc}' 标注已证实但无 source_ref（可能虚构或漏取一手源）"
            )
        if label == "已证实" and tier not in _STRONG_EVIDENCE_TIERS:
            findings.append(
                f"编造/取数：'{desc}' 标注已证实但 evidence_tier={tier!r} 未达 "
                f"primary/official/filing，应降级为推断标注或补一手源"
            )
        # Reverse direction: a claim WITH a strong source mislabeled as an
        # inference/guess (真关系被误标"未点名/不可证实").
        if label in ("我的推断", "纯推测") and tier in _STRONG_EVIDENCE_TIERS and source_ref:
            findings.append(
                f"编造/取数（反向）：'{desc}' 已有 {tier} 级一手源却仍标 {label!r}，"
                f"可能把已证实关系错标未证实"
            )
        if c.get("fast_changing") and not c.get("independently_reverified"):
            findings.append(
                f"时效守门：'{desc}' 为快变字段（backlog/订单/指引/客户名单类），"
                f"未标记独立重核 as-of 前 60 天新数据"
            )

    reverified_count = sum(1 for c in measurable if c.get("independently_reverified"))
    required = min(MIN_INDEPENDENT_REVERIFY, len(measurable))
    if measurable and reverified_count < required:
        findings.append(
            f"编造/取数：独立联网重核数字仅 {reverified_count} 个，未达到 {required} 个门槛"
            f"（复核纪律：≥{MIN_INDEPENDENT_REVERIFY} 个关键数字）"
        )

    # 2. 重大遗漏 (material omission)
    if omission_checklist:
        missed = [k for k, checked in omission_checklist.items() if not checked]
        if missed:
            findings.append(f"重大遗漏：以下检查项未完成 {missed}")

    # 3. 逻辑 + 反偏误
    if not bear_before_bull:
        findings.append("逻辑/顺序：风险(bear)段未写在利好(bull)段之前，顺序倒置")
    if not falsification_questions:
        findings.append("逻辑/反偏误：证伪问题（falsification_questions）为空，反方先行未完成")
    if user_directional_hint and not counter_pressure_applied:
        findings.append("反确认偏误：用户原话有方向性暗示，但复核未记录反向加压检查")

    # 4. 迎合 (catering to user / narrative momentum)
    if not catering_check_passed:
        findings.append("迎合检查：结论可能迎合用户倾向或叙事热度，需按框架重新核对是否成立")

    # 5. 可读性 (Chinese-output jargon leak + bold overuse)
    if rendered_text:
        leaked = [kw for kw in _INTERNAL_JARGON_PATTERNS if kw in rendered_text]
        if leaked:
            findings.append(f"可读性：检测到内部代号/黑话泄漏到成品文本 {leaked}")
        bold_count = len(_BOLD_MARKER_PATTERN.findall(rendered_text))
        if bold_count > _MAX_BOLD_MARKERS:
            findings.append(f"可读性：加粗标记 {bold_count} 处，超过上限 {_MAX_BOLD_MARKERS}")

    degraded = not sub_agent_available
    if degraded:
        findings = [f"{DEGRADED_REVIEW_TAG} {f}" for f in findings]
        findings.append(
            f"{DEGRADED_REVIEW_TAG} 本次复核在无独立 sub-agent 环境下降级为自查 stopgap，"
            f"非真正独立复核，结论应主动降一档信念档或标记未独立复核"
        )

    status = "revise" if findings else "pass"
    return IndependentReviewVerdict(status=status, findings=findings, degraded=degraded)


def attach_independent_review(
    db,
    review_case_id: int,
    verdict: IndependentReviewVerdict,
    *,
    reviewer: str,
) -> dict:
    """Attach an IndependentReviewVerdict onto an existing ReviewCase.

    Additive-only: merges an 'independent_review' key into the existing
    review_payload_json without touching any other payload field or
    first-class column. This is the storage counterpart of
    run_independent_review — the pure function above computes the verdict,
    this function records it against the ReviewCase it was run for.
    Raises ValueError if the review case does not exist.
    Always calls audit_write after a successful update.
    """
    from backend.data.database import ReviewCase

    row = db.query(ReviewCase).filter(ReviewCase.id == review_case_id).first()
    if row is None:
        raise ValueError(f"review case {review_case_id} not found")

    payload = json.loads(row.review_payload_json) if row.review_payload_json else {}
    payload["independent_review"] = {
        "status": verdict.status,
        "findings": verdict.findings,
        "degraded": verdict.degraded,
        "reviewer": reviewer,
        "reviewed_at": _iso(_utc_now()),
    }
    row.review_payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    row.updated_at = _utc_now()
    db.flush()

    audit_write(
        db,
        "review_loop.attach_independent_review",
        (
            f"independent review status={verdict.status} degraded={verdict.degraded} "
            f"findings={len(verdict.findings)} reviewer={reviewer!r} "
            f"review_case_id={review_case_id}"
        ),
        related_symbol=row.symbol,
    )
    db.commit()
    return _rc_to_dict(row)
