"""Safety vetter for financial skill outputs."""
from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class VetterReview:
    """Result of a financial skill safety review."""

    status: str
    risk_flags: list[str]
    blocked_actions: list[str]
    notes: list[str]

    def to_dict(self) -> dict:
        """Serialize the review for API and report payloads."""
        return {
            "status": self.status,
            "risk_flags": self.risk_flags,
            "blocked_actions": self.blocked_actions,
            "notes": self.notes,
        }


AUTO_TRADE_TERMS = (
    "自动下单",
    "自动买入",
    "自动卖出",
    "直接下单",
    "place_order",
    "execute_order",
)

PRICE_PREDICTION_TERMS = (
    "一定涨",
    "一定跌",
    "必涨",
    "必跌",
    "涨停",
    "跌停",
    "guaranteed",
)


def _flatten_text(payload: dict) -> str:
    """Return a compact text view of nested output for rule checks."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def vet_skill_output(payload: dict) -> VetterReview:
    """
    Check that a financial skill output stays inside StockSage safety bounds.

    The vetter is intentionally deterministic and conservative. It does not
    judge investment quality; it only blocks behaviors that violate project
    constraints and flags outputs that lack enough evidence for decision use.
    """
    text = _flatten_text(payload)
    evidence = payload.get("evidence") or payload.get("inputs", {}).get("evidence") or []
    allowed_actions = payload.get("allowed_actions") or []

    risk_flags: list[str] = []
    blocked_actions: list[str] = []
    notes: list[str] = []

    if any(term in text for term in AUTO_TRADE_TERMS) or any(
        term in str(action) for action in allowed_actions for term in AUTO_TRADE_TERMS
    ):
        risk_flags.append("auto_trade_requested")
        blocked_actions.append("auto_trade")
        notes.append("StockSage 只做辅助决策，不允许自动交易。")

    if any(term in text for term in PRICE_PREDICTION_TERMS):
        risk_flags.append("price_prediction")
        notes.append("输出包含确定性价格预测，应降级或改写为条件化风险描述。")

    if not evidence:
        risk_flags.append("missing_evidence")
        notes.append("输出缺少可追溯证据。")

    status = "pass"
    if blocked_actions:
        status = "block"
    elif risk_flags:
        status = "warn"

    return VetterReview(
        status=status,
        risk_flags=risk_flags,
        blocked_actions=blocked_actions,
        notes=notes,
    )

