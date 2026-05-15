"""Hermes-style lightweight memory decision heuristic."""
from __future__ import annotations


POSITIVE_HINTS = (
    "记住", "remember", "已买入", "买入了", "持仓", "仓位",
    "风险预警", "预警", "测试规则", "规则切换", "偏好",
)
NEGATIVE_HINTS = (
    "今天查一下", "临时", "一次性", "随便看看", "是什么", "新闻",
    "现在价格", "当前价格", "帮我算一下",
)


def should_remember(text: str, *, category: str | None = None) -> bool:
    """Heuristically decide whether a piece of text should be persisted to memory."""
    normalized = text.strip().lower()
    if not normalized:
        return False
    if category in {"position", "risk", "decision", "preference", "rule"}:
        return True
    if any(h.lower() in normalized for h in POSITIVE_HINTS):
        return True
    if any(h.lower() in normalized for h in NEGATIVE_HINTS):
        return False
    return False
