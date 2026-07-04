"""
LongTermLabel 持久化

  • save_label(label, db)           — 写 DB + 镜像 JSON
  • get_active_label(symbol, db)    — 取 TTL 未过期的最新一条
  • bulk_get_labels(symbols, db)    — 批量取（盘后 job 用）
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from backend.agents.long_term.base import LabelQuality, LongTermLabel, VoteLabel
from backend.config import settings
from backend.data.database import LongTermLabel as LongTermLabelORM

logger = logging.getLogger(__name__)

MIRROR_PATH: Path | None = None


def _mirror_path() -> Path | None:
    """Return the optional label mirror path; empty means DB-only storage."""
    if MIRROR_PATH is not None:
        return MIRROR_PATH
    configured = settings.long_term_label_mirror_path.strip()
    return Path(configured).expanduser() if configured else None


def _json_list(raw: str | None) -> list:
    return json.loads(raw) if raw else []


def save_label(label: LongTermLabel, db) -> None:
    """幂等：同 (symbol, date) 已存在则更新，否则插入"""
    existing = (db.query(LongTermLabelORM)
                  .filter(LongTermLabelORM.symbol == label.symbol,
                          LongTermLabelORM.date == label.date)
                  .first())
    payload = dict(
        symbol=label.symbol,
        date=label.date,
        label=label.label,
        score=label.score,
        votes_json=json.dumps(label.votes, ensure_ascii=False),
        key_findings_json=json.dumps(label.key_findings, ensure_ascii=False),
        expires_at=label.expires_at,
        quality=label.quality,
        constraint_eligible=label.constraint_eligible,
        quality_notes_json=json.dumps(label.quality_notes, ensure_ascii=False),
    )
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
    else:
        db.add(LongTermLabelORM(**payload))
    db.commit()
    _write_mirror(db)


def _write_mirror(db) -> None:
    """把所有 active label 写到可选镜像 JSON 文件。"""
    mirror_path = _mirror_path()
    if mirror_path is None:
        return
    try:
        today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
        rows = (db.query(LongTermLabelORM)
                  .filter(LongTermLabelORM.expires_at >= today)
                  .all())
        out = {}
        for r in rows:
            out[r.symbol] = {
                "label": r.label,
                "score": r.score,
                "date": r.date,
                "votes": json.loads(r.votes_json) if r.votes_json else {},
                "key_findings": json.loads(r.key_findings_json) if r.key_findings_json else [],
                "expires_at": r.expires_at,
                "quality": getattr(r, "quality", "degraded") or "degraded",
                "constraint_eligible": bool(getattr(r, "constraint_eligible", False)),
                "quality_notes": json.loads(r.quality_notes_json) if getattr(r, "quality_notes_json", None) else [],
                "prompt_version": "m61_p3" if "prompt_version=m61_p3" in (getattr(r, "quality_notes_json", "") or "") else "legacy",
            }
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        mirror_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("镜像写入失败: %s", e)


def get_active_label(symbol: str, db) -> LongTermLabel | None:
    """取 TTL 未过期的最新一条（按 date 倒序），过期返回 None"""
    today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
    row = (db.query(LongTermLabelORM)
             .filter(LongTermLabelORM.symbol == symbol,
                     LongTermLabelORM.expires_at >= today)
             .order_by(LongTermLabelORM.date.desc())
             .first())
    if row is None:
        return None
    return LongTermLabel(
        symbol=row.symbol,
        date=row.date,
        label=row.label,
        score=row.score,
        votes=json.loads(row.votes_json) if row.votes_json else {},
        key_findings=json.loads(row.key_findings_json) if row.key_findings_json else [],
        expires_at=row.expires_at,
        quality=cast(LabelQuality, getattr(row, "quality", "degraded") or "degraded"),
        constraint_eligible=bool(getattr(row, "constraint_eligible", False)),
        quality_notes=_json_list(getattr(row, "quality_notes_json", None)),
        prompt_version="m61_p3" if "prompt_version=m61_p3" in (getattr(row, "quality_notes_json", "") or "") else "legacy",
    )


def bulk_get_labels(symbols: list[str], db) -> dict[str, LongTermLabel]:
    """批量取，盘后 job 一次性查 10+ 只股"""
    today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
    rows = (db.query(LongTermLabelORM)
              .filter(LongTermLabelORM.symbol.in_(symbols),
                      LongTermLabelORM.expires_at >= today)
              .all())
    # 每 symbol 取最新一条
    by_symbol: dict[str, LongTermLabelORM] = {}
    for r in rows:
        if r.symbol not in by_symbol or r.date > by_symbol[r.symbol].date:
            by_symbol[r.symbol] = r
    return {
        sym: LongTermLabel(
            symbol=r.symbol,
            date=r.date,
            label=cast(VoteLabel, r.label),
            score=r.score,
            votes=json.loads(r.votes_json) if r.votes_json else {},
            key_findings=json.loads(r.key_findings_json) if r.key_findings_json else [],
            expires_at=r.expires_at,
            quality=cast(LabelQuality, getattr(r, "quality", "degraded") or "degraded"),
            constraint_eligible=bool(getattr(r, "constraint_eligible", False)),
            quality_notes=_json_list(getattr(r, "quality_notes_json", None)),
            prompt_version="m61_p3" if "prompt_version=m61_p3" in (getattr(r, "quality_notes_json", "") or "") else "legacy",
        )
        for sym, r in by_symbol.items()
    }
