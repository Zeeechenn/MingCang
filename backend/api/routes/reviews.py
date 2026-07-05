"""Daily and long-term review aggregation routes."""
from __future__ import annotations

import json
import logging
from datetime import datetime, time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.agent.http_guard import agent_write_guard
from backend.data.database import ReviewRun, get_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_now(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value)
    return datetime.now().astimezone()


def _review_to_dict(row: ReviewRun) -> dict:
    payload = {}
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = {}
    return {
        "id": row.id,
        "kind": row.kind,
        "as_of": row.as_of,
        "summary": row.summary,
        "path": row.path,
        "status": row.status,
        "payload": payload,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


def _review_content(row: ReviewRun) -> str:
    if row.path:
        try:
            path = Path(row.path)
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8")
        except Exception:
            logger.warning("reviews._review_content: reading review file failed, using fallback", exc_info=True)
            pass
    payload = {}
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = {}
    if payload.get("content"):
        return str(payload["content"])
    return row.summary or ""


@router.get("/reviews")
def list_reviews(kind: str | None = None, limit: int = 20, db: Session = Depends(get_db)):
    """Return recent review run records."""
    query = db.query(ReviewRun)
    if kind:
        query = query.filter(ReviewRun.kind == kind)
    rows = query.order_by(ReviewRun.as_of.desc(), ReviewRun.created_at.desc()).limit(limit).all()
    return [_review_to_dict(row) for row in rows]


@router.get("/reviews/latest")
def latest_reviews(db: Session = Depends(get_db)):
    """Return the latest daily and long-term review records."""
    result = {}
    for kind in ("daily", "long_term"):
        row = (
            db.query(ReviewRun)
            .filter(ReviewRun.kind == kind)
            .order_by(ReviewRun.as_of.desc(), ReviewRun.created_at.desc())
            .first()
        )
        result[kind] = _review_to_dict(row) if row else None
    return result


@router.get("/reviews/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db)):
    """Return a review record with full report content when available."""
    row = db.query(ReviewRun).filter(ReviewRun.id == review_id).first()
    if row is None:
        raise HTTPException(404, "review not found")
    data = _review_to_dict(row)
    data["content"] = _review_content(row)
    return data


def _time_from_setting(value: str, fallback: time) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except Exception:
        logger.debug("reviews._time_from_setting: parsing schedule time failed, using fallback", exc_info=True)
        return fallback


_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _dow_from_setting(value: str, fallback: int) -> int:
    return _DOW.get((value or "").lower(), fallback)


@router.post(
    "/reviews/daily/ensure",
    dependencies=[Depends(agent_write_guard("review.daily.ensure"))],
)
def ensure_daily_review(
    as_of: str | None = None,
    now: str | None = None,
    db: Session = Depends(get_db),
):
    """Create today's daily review once after 15:00 local time."""
    from backend.config import settings

    local_now = _parse_now(now)
    day = as_of or local_now.date().isoformat()
    existing = db.query(ReviewRun).filter(ReviewRun.kind == "daily", ReviewRun.as_of == day).first()
    if existing:
        return {"status": "existing", "review": _review_to_dict(existing)}
    due_time = _time_from_setting(settings.schedule_daily_review_time, time(15, 0))
    if local_now.time() < due_time:
        return {"status": "too_early", "review": None}

    from backend.skills.daily_review import build_daily_review

    review = build_daily_review(db, as_of=day, persist=True)
    row = ReviewRun(
        kind="daily",
        as_of=day,
        summary=review.summary,
        path=str(review.path) if review.path else None,
        status="created",
        payload_json=json.dumps(review.to_dict(), ensure_ascii=False),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(ReviewRun).filter(ReviewRun.kind == "daily", ReviewRun.as_of == day).first()
        return {"status": "existing", "review": _review_to_dict(existing) if existing else None}
    db.refresh(row)
    return {"status": "created", "review": _review_to_dict(row)}


def _run_long_term_review(day: str, db: Session) -> dict:
    from backend.data.database import LongTermLabel as LongTermLabelRow
    from backend.data.database import Stock
    from backend.scheduler import job_weekly_longterm

    job_weekly_longterm()
    rows = (
        db.query(LongTermLabelRow)
        .filter(LongTermLabelRow.date == day)
        .order_by(LongTermLabelRow.score.desc())
        .all()
    )
    names = {row.symbol: row.name for row in db.query(Stock.symbol, Stock.name).all()}
    label_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row.label] = label_counts.get(row.label, 0) + 1
    summary = (
        f"{day} 长期研究团队已运行，生成 {len(rows)} 条长期标签。"
        if rows else f"{day} 长期研究团队已运行，暂无可展示标签。"
    )
    lines = [
        f"# MingCang 长期复盘 — {day}",
        "",
        "## 摘要",
        f"- 长期标签：{len(rows)} 条",
        *[f"- {label}：{count} 条" for label, count in sorted(label_counts.items())],
        "",
        "## 长期标签明细",
    ]
    if rows:
        lines.append("| 股票 | 标签 | 评分 | 到期 | 关键发现 | 投票 |")
        lines.append("|---|---|---:|---|---|---|")
        for row in rows:
            try:
                findings = json.loads(row.key_findings_json) if row.key_findings_json else []
            except Exception:
                logger.warning("reviews._run_long_term_review: parsing key findings failed, using fallback", exc_info=True)
                findings = []
            try:
                votes = json.loads(row.votes_json) if row.votes_json else {}
            except Exception:
                logger.warning("reviews._run_long_term_review: parsing votes failed, using fallback", exc_info=True)
                votes = {}
            lines.append(
                f"| {row.symbol} {names.get(row.symbol, '')} | {row.label} | "
                f"{row.score:.1f} | {row.expires_at} | "
                f"{'；'.join(findings) or '-'} | "
                f"{'；'.join(f'{k}:{v}' for k, v in votes.items()) or '-'} |"
            )
    else:
        lines.append("- 当前没有长期标签明细，可能是长期团队未启用、无自选股，或运行失败。")
    lines.extend([
        "",
        "## 使用说明",
        "- 长期标签用于约束短线信号，不直接生成交易。",
        "- “估值偏高”会降低仓位建议，“规避”可阻断买入。",
        "- 本报告记录长期研究团队输出，供后续短线决策和复盘读取。",
    ])
    return {"summary": summary, "content": "\n".join(lines)}


@router.post(
    "/reviews/long-term/ensure",
    dependencies=[Depends(agent_write_guard("review.long_term.ensure"))],
)
def ensure_long_term_review(
    as_of: str | None = None,
    now: str | None = None,
    db: Session = Depends(get_db),
):
    """Create a long-term review record for due Monday/Friday runs."""
    from backend.config import settings

    local_now = _parse_now(now)
    day = as_of or local_now.date().isoformat()
    existing = db.query(ReviewRun).filter(ReviewRun.kind == "long_term", ReviewRun.as_of == day).first()
    if existing:
        return {"status": "existing", "review": _review_to_dict(existing)}

    monday_time = _time_from_setting(settings.schedule_longterm_monday_time, time(9, 0))
    friday_time = _time_from_setting(settings.schedule_longterm_friday_time, time(15, 0))
    monday_dow = _dow_from_setting(settings.schedule_longterm_monday_dow, 0)
    friday_dow = _dow_from_setting(settings.schedule_longterm_friday_dow, 4)
    due = (local_now.weekday() == monday_dow and local_now.time() >= monday_time) or (
        local_now.weekday() == friday_dow and local_now.time() >= friday_time
    )
    if not due:
        return {"status": "not_due", "review": None}

    payload = _run_long_term_review(day, db)
    row = ReviewRun(
        kind="long_term",
        as_of=day,
        summary=payload["summary"],
        status="created",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(ReviewRun).filter(ReviewRun.kind == "long_term", ReviewRun.as_of == day).first()
        return {"status": "existing", "review": _review_to_dict(existing) if existing else None}
    db.refresh(row)
    return {"status": "created", "review": _review_to_dict(row)}
