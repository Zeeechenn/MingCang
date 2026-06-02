"""LLM 成本/天可观测性（M25.3）

提供每次 LLM 调用后的 token 估算、持久化和 7 天汇总。

用法（在每个 complete_structured 调用点附近）::

    from backend.ops.llm_usage import log_llm_usage
    result = provider.complete_structured(prompt=..., tool=..., ...)
    log_llm_usage(
        bucket="sentiment",
        prompt_text=full_prompt,
        response_text=json.dumps(result),
    )

估算方式：中英混合文本约 3 字符/token（粗略，仅用于监控趋势，不用于精确计费）。
Haiku 定价（2024Q4）：$0.25/$1.25 per 1M tokens in/out；CNY 汇率 7.2。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token / cost estimation
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 3.0           # mixed Chinese/English heuristic
_COST_IN_PER_TOKEN_CNY = 0.25 * 7.2 / 1_000_000    # Haiku input
_COST_OUT_PER_TOKEN_CNY = 1.25 * 7.2 / 1_000_000   # Haiku output

VALID_BUCKETS = frozenset(
    ["sentiment", "copilot", "debate", "chat", "deep_research", "red_team_review", "other"]
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def cost_cny(tokens_in: int, tokens_out: int) -> float:
    return round(
        tokens_in * _COST_IN_PER_TOKEN_CNY + tokens_out * _COST_OUT_PER_TOKEN_CNY,
        6,
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_llm_usage(
    bucket: str,
    prompt_text: str,
    response_text: str,
    db=None,
) -> None:
    """Estimate tokens for one LLM call and persist to llm_usage_log.

    db is optional — when None the function opens its own session.
    Silently swallows errors so a logging failure never breaks the LLM path.
    """
    if bucket not in VALID_BUCKETS:
        bucket = "other"
    tokens_in = estimate_tokens(prompt_text)
    tokens_out = estimate_tokens(response_text)
    cny = cost_cny(tokens_in, tokens_out)

    _persist(bucket, tokens_in, tokens_out, cny, db)


def _persist(bucket, tokens_in, tokens_out, cny, db_provided) -> None:
    from backend.data.database import LlmUsageLog, SessionLocal

    close_after = db_provided is None
    db = db_provided or SessionLocal()
    try:
        row = LlmUsageLog(
            bucket=bucket,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate_cny=cny,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(row)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("llm_usage log failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if close_after:
            db.close()


# ---------------------------------------------------------------------------
# Summary query (7-day rolling)
# ---------------------------------------------------------------------------

def get_usage_summary(days: int = 7, db=None) -> dict:
    """Return daily totals and bucket breakdown for the last ``days`` days.

    Returns::

        {
          "days": 7,
          "daily": [
            {"date": "2026-05-27", "tokens_in": 1200, "tokens_out": 400,
             "cost_estimate_cny": 0.0035, "calls": 12},
            ...
          ],
          "buckets": {
            "sentiment": {"tokens_in": ..., "tokens_out": ..., "cost_estimate_cny": ..., "calls": ...},
            ...
          },
          "total": {"tokens_in": ..., "tokens_out": ..., "cost_estimate_cny": ..., "calls": ...},
        }
    """
    from datetime import timedelta

    from backend.data.database import LlmUsageLog, SessionLocal

    close_after = db is None
    db = db or SessionLocal()
    try:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        rows = (
            db.query(LlmUsageLog)
            .filter(LlmUsageLog.created_at >= cutoff)
            .all()
        )
    finally:
        if close_after:
            db.close()

    # Aggregate
    daily: dict[str, dict] = {}
    buckets: dict[str, dict] = {}
    total = {"tokens_in": 0, "tokens_out": 0, "cost_estimate_cny": 0.0, "calls": 0}

    for r in rows:
        day = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        if day not in daily:
            daily[day] = {"date": day, "tokens_in": 0, "tokens_out": 0, "cost_estimate_cny": 0.0, "calls": 0}
        daily[day]["tokens_in"] += r.tokens_in
        daily[day]["tokens_out"] += r.tokens_out
        daily[day]["cost_estimate_cny"] = round(daily[day]["cost_estimate_cny"] + r.cost_estimate_cny, 6)
        daily[day]["calls"] += 1

        bk = r.bucket or "other"
        if bk not in buckets:
            buckets[bk] = {"tokens_in": 0, "tokens_out": 0, "cost_estimate_cny": 0.0, "calls": 0}
        buckets[bk]["tokens_in"] += r.tokens_in
        buckets[bk]["tokens_out"] += r.tokens_out
        buckets[bk]["cost_estimate_cny"] = round(buckets[bk]["cost_estimate_cny"] + r.cost_estimate_cny, 6)
        buckets[bk]["calls"] += 1

        total["tokens_in"] += r.tokens_in
        total["tokens_out"] += r.tokens_out
        total["cost_estimate_cny"] = round(total["cost_estimate_cny"] + r.cost_estimate_cny, 6)
        total["calls"] += 1

    # Sort daily by date descending
    sorted_daily = sorted(daily.values(), key=lambda x: x["date"], reverse=True)
    return {"days": days, "daily": sorted_daily, "buckets": buckets, "total": total}


# ---------------------------------------------------------------------------
# Budget alert helper (called from system health)
# ---------------------------------------------------------------------------

def check_daily_budget_alert(
    budget_cny: float,
    db=None,
) -> dict:
    """Return alert status for today's LLM spend vs budget_cny.

    Returns {"alert": bool, "today_cny": float, "budget_cny": float}.
    """
    summary = get_usage_summary(days=1, db=db)
    today_str = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
    today_data = next((d for d in summary["daily"] if d["date"] == today_str), None)
    today_cny = today_data["cost_estimate_cny"] if today_data else 0.0
    return {
        "alert": today_cny > budget_cny,
        "today_cny": today_cny,
        "budget_cny": budget_cny,
    }
