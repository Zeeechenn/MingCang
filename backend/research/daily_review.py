"""Human research choices bound to committed daily evidence.

Uses the existing pending-action store as a reviewed, non-executable record.
Never calls the action registry, changes the research queue, or places trades.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from backend.data.models.decision import PendingAIAction
from backend.evidence.daily_panel import CARD_TYPES
from backend.ops.run_envelope import select_complete_daily_run

ACTION = "daily.research_review"
VERSION = "daily_research_review.v1"
CHOICES = {"accepted", "modified", "rejected"}
OUTCOMES = {"supported", "contradicted", "inconclusive", "not_observed"}
REPO_ROOT = Path(__file__).resolve().parents[2]


class ReviewError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _load_panel(db, as_of: str | None) -> tuple[dict, str]:
    selection = select_complete_daily_run(db, as_of=as_of)
    if selection.get("status") != "selected":
        raise ReviewError("panel_run_not_unique_or_complete")
    row = selection.get("job_run")
    envelope = selection.get("run_envelope") or {}
    ref = getattr(row, "artifact_path", None)
    if not ref or not str(ref).endswith(".daily_panel.json"):
        raise ReviewError("committed_panel_missing")
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        content = path.read_bytes()
        panel = json.loads(content)
        cards = panel["cards"]
        stored = panel["run_envelope"]
        contract = panel["artifact_contract"]
        day = date.fromisoformat(panel["as_of"])
        if (panel.get("schema_version") != "daily_panel.v1"
                or panel.get("ledger_commit_state") != "committed"
                or stored.get("status") != "complete" or panel["as_of"] != envelope.get("as_of")
                or stored.get("run_id") != envelope.get("run_id")
                or stored.get("batch_id") != envelope.get("batch_id")
                or contract.get("source_job_run_id") != envelope.get("run_id")
                or contract.get("close_confirmed") is not True
                or [c.get("card_type") for c in cards] != list(CARD_TYPES)
                or any((c.get("run_ref") or {}).get("run_id") != envelope.get("run_id") for c in cards)
                or day > _now().astimezone(ZoneInfo("Asia/Shanghai")).date()):
            raise ReviewError("panel_binding_invalid")
        return panel, hashlib.sha256(content).hexdigest()
    except (OSError, KeyError, TypeError, AttributeError, ValueError) as exc:
        if isinstance(exc, ReviewError):
            raise
        raise ReviewError("panel_unreadable") from exc


def _expiry(item: dict) -> tuple[str | None, str]:
    entry = item.get("entry_card")
    if not isinstance(entry, dict):
        entry = {}
    raw = item.get("expires_at") or item.get("valid_until") or entry.get("expires_at") or entry.get("valid_until")
    if not raw:
        return None, "unknown"
    try:
        if len(str(raw)) == 10:
            expired = date.fromisoformat(str(raw)) < _now().astimezone(ZoneInfo("Asia/Shanghai")).date()
        else:
            expiry = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                return str(raw), "unknown"
            expired = expiry < _now()
    except ValueError:
        return str(raw), "unknown"
    return str(raw), "expired" if expired else "valid"


def _items(panel: dict, digest: str) -> list[dict]:
    items: dict[str, dict] = {}
    for card in panel["cards"]:
        kind = card["card_type"]
        if kind not in {"candidate", "position_health", "human_confirmation"}:
            continue
        raw_items = (card.get("payload") or {}).get("pending_queue" if kind == "human_confirmation" else "items") or []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            subject = raw.get("symbol") or raw.get("target")
            if not isinstance(subject, str) or not subject.strip():
                continue
            source = {"panel_as_of": panel["as_of"], "run_id": panel["run_envelope"]["run_id"],
                      "panel_sha256": digest, "card_type": kind, "subject": subject, "original": raw}
            # Exact duplicates share one review identity. Changed evidence is a new proposal.
            item_id = _hash(source)
            expires_at, validity = _expiry(raw)
            items[item_id] = {"item_id": item_id, **source, "name": raw.get("name") or subject,
                              "summary": raw.get("reason") or raw.get("recommendation") or card.get("summary") or "原始研究记录",
                              "expires_at": expires_at, "validity": validity,
                              "source_status": card.get("status"),
                              "reviewable": kind == "human_confirmation" or card.get("status") in {"ready", "ready_zero"}}
    return list(items.values())


def _serialize(row: PendingAIAction) -> dict:
    return {"review_id": row.action_id, "source": json.loads(row.payload_json),
            "result": json.loads(row.result_json or "{}"), "can_execute": False}


def list_reviews(db, *, as_of: str | None = None) -> dict:
    history = db.query(PendingAIAction).filter(PendingAIAction.action == ACTION).order_by(PendingAIAction.created_at.desc()).limit(100).all()
    warning = None
    try:
        panel, digest = _load_panel(db, as_of)
        items = _items(panel, digest)
        ids = ["daily-review:" + item["item_id"] for item in items]
        rows = db.query(PendingAIAction).filter(PendingAIAction.action == ACTION, PendingAIAction.action_id.in_(ids)).all() if ids else []
        by_id = {row.action_id: _serialize(row) for row in rows}
        for item in items:
            item["review"] = by_id.get("daily-review:" + item["item_id"])
    except ReviewError as exc:
        items, panel, digest, warning = [], {}, None, str(exc)
    return {"schema_version": VERSION, "panel_as_of": panel.get("as_of"), "panel_sha256": digest,
            "items": items, "history": [_serialize(row) for row in history], "warning": warning,
            "history_limit": 100, "can_execute": False, "queue_automatically_completed": False}


def record_review(db, *, as_of: str, panel_sha256: str, item_id: str, choice: str,
                  rationale: str, revised_text: str = "") -> dict:
    if choice not in CHOICES or not rationale.strip() or len(rationale) > 4000 or len(revised_text) > 4000:
        raise ReviewError("invalid_review", 422)
    if (choice == "modified") != bool(revised_text.strip()):
        raise ReviewError("revision_required_only_for_modified", 422)
    review_id = "daily-review:" + item_id
    decision = {"choice": choice, "rationale": rationale.strip(), "revised_text": revised_text.strip()}
    existing = db.query(PendingAIAction).filter(PendingAIAction.action_id == review_id, PendingAIAction.action == ACTION).first()
    if existing:
        saved = _serialize(existing)
        if (saved["source"].get("panel_sha256") != panel_sha256 or saved["source"].get("panel_as_of") != as_of
                or saved["result"].get("decision") != decision):
            raise ReviewError("review_already_recorded_with_different_choice")
        return saved
    panel, digest = _load_panel(db, as_of)
    if digest != panel_sha256:
        raise ReviewError("panel_changed_reload_required")
    item = next((item for item in _items(panel, digest) if item["item_id"] == item_id), None)
    if not item:
        raise ReviewError("source_item_not_found", 404)
    if choice != "rejected" and (item["validity"] == "expired" or not item["reviewable"]):
        raise ReviewError("source_expired_or_unverified")
    now = _now()
    result = {"version": 1, "decision": decision, "recorded_at": now.isoformat(), "outcomes": [],
              "actual_execution": "not_recorded", "queue_task_completed": False}
    row = PendingAIAction(action_id=review_id, action=ACTION, payload_json=_json(item),
                          status="reviewed", result_json=_json(result), user_message=rationale.strip(),
                          created_at=now.replace(tzinfo=None))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(PendingAIAction).filter(PendingAIAction.action_id == review_id, PendingAIAction.action == ACTION).first() is None:
            raise ReviewError("review_identity_conflict") from None
        return record_review(db, as_of=as_of, panel_sha256=panel_sha256, item_id=item_id,
                             choice=choice, rationale=rationale, revised_text=revised_text)
    return _serialize(row)


def record_outcome(db, *, review_id: str, expected_version: int, observation_id: str,
                   status: str, note: str) -> dict:
    if status not in OUTCOMES or not note.strip() or len(note) > 4000 or not observation_id or len(observation_id) > 80:
        raise ReviewError("invalid_outcome", 422)
    row = db.query(PendingAIAction).filter(PendingAIAction.action_id == review_id, PendingAIAction.action == ACTION).first()
    if row is None:
        raise ReviewError("review_not_found", 404)
    old = row.result_json
    result = json.loads(old or "{}")
    for entry in result["outcomes"]:
        if entry["observation_id"] == observation_id:
            if entry["status"] == status and entry["note"] == note.strip():
                return _serialize(row)
            raise ReviewError("observation_id_conflict")
    if result["version"] != expected_version:
        raise ReviewError("review_version_conflict_reload_required")
    if len(result["outcomes"]) >= 100:
        raise ReviewError("outcome_limit_reached")
    result["outcomes"].append({"observation_id": observation_id, "status": status, "note": note.strip(),
                               "recorded_at": _now().isoformat(), "source": "human_reported_not_independently_verified"})
    result["version"] += 1
    changed = db.execute(update(PendingAIAction).where(PendingAIAction.action_id == review_id,
                        PendingAIAction.action == ACTION, PendingAIAction.result_json == old)
                        .values(result_json=_json(result)), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.rollback()
        raise ReviewError("review_version_conflict_reload_required")
    db.commit()
    db.refresh(row)
    return _serialize(row)
