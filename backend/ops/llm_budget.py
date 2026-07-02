"""LLM token 预算护栏（M54 阶段7c）。

只做**判定**，不做拦截——是否降级/跳过 LLM 调用由调用方（v2 编排器）决定。
本模块读取 backend/ops/llm_usage.py 已有的按桶用量统计，对 DB 异常容错：
异常时不让预算查询把管线弄挂，返回 unknown=True 且不判定超限（放行）。

用法::

    from backend.ops.llm_budget import check_budget
    status = check_budget("news_v2", limit_tokens=50_000)
    if status.exceeded:
        # 调用方自行决定降级路径（例如退回 title_only 打分）
        ...

default-safe: limit_tokens <= 0 表示不设限（关闭护栏），exceeded 恒为 False。
"""
from __future__ import annotations

from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    bucket: str
    spent_tokens: int
    limit_tokens: int
    exceeded: bool
    unknown: bool = False


def get_today_spend(bucket: str, db=None) -> tuple[int, bool]:
    """Return (spent_tokens, unknown) for ``bucket``'s spend in the current day window.

    Reuses get_usage_summary(days=1) from llm_usage.py (same day-boundary semantics
    as the existing check_daily_budget_alert helper). Fully fault-tolerant: any DB
    or import failure returns (0, True) rather than raising, so a budget query can
    never break the v2 pipeline.
    """
    try:
        from backend.ops.llm_usage import get_usage_summary

        summary = get_usage_summary(days=1, db=db)
        bucket_data = summary.get("buckets", {}).get(bucket)
        if bucket_data is None:
            return 0, False
        spent = int(bucket_data.get("tokens_in", 0)) + int(bucket_data.get("tokens_out", 0))
        return spent, False
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_today_spend failed for bucket=%s (non-fatal): %s", bucket, exc)
        return 0, True


def check_budget(bucket: str, limit_tokens: int, db=None) -> BudgetStatus:
    """Pure(-ish) judgement of whether ``bucket`` has exceeded ``limit_tokens`` today.

    - ``limit_tokens <= 0`` means no limit configured (default-safe off switch):
      always returns exceeded=False, unknown=False, spent_tokens still reported
      best-effort.
    - On DB/query failure, ``unknown=True`` and ``exceeded=False`` (fail open —
      never blocks the caller due to an observability failure).
    - This function only *judges*; it does not raise, log usage, or intercept the
      caller. Enforcement/degradation is the v2 orchestrator's responsibility.
    """
    if limit_tokens <= 0:
        spent_tokens, unknown = get_today_spend(bucket, db=db)
        return BudgetStatus(
            bucket=bucket,
            spent_tokens=spent_tokens,
            limit_tokens=limit_tokens,
            exceeded=False,
            unknown=unknown,
        )

    spent_tokens, unknown = get_today_spend(bucket, db=db)
    if unknown:
        return BudgetStatus(
            bucket=bucket,
            spent_tokens=spent_tokens,
            limit_tokens=limit_tokens,
            exceeded=False,
            unknown=True,
        )

    return BudgetStatus(
        bucket=bucket,
        spent_tokens=spent_tokens,
        limit_tokens=limit_tokens,
        exceeded=spent_tokens >= limit_tokens,
        unknown=False,
    )
