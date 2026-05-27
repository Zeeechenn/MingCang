"""
风险经理 — 对交易员输出有否决权。

否决（一票否决，veto_reason 置位）：
  • 大盘 RSRS 极度看空 (rsrs_z < -1.0)
  • 综合组合回撤超过 -8%（kill switch 软线）
  • 长期标签为「规避」且通过质量门

降级（不否决，下调 final_recommendation / adjusted_position_pct）：
  • 板块扩散指标极弱 (< 0.2)：强买→可关注；其他多头仓位减半

执行约束提示（仅 append 到 risk_notes，不影响 veto / final_rec / 仓位的策略层）：
  • 涨停板买入：仓位 ×0.5 表示次日观察折扣，但不否决
  • 跌停板"卖出"：无买盘无法成交，仅追 note 等次日开盘

注意：各阈值均从 settings 读取，不是硬编码常量，可在 .env 覆盖。
M17.2 文档订正：跌停日卖出不是策略否决条件，是市场执行约束；旧文档把它列入
「否决条件」与 `risk_manager.py:95-96` 仅追 note 的实现不一致。

输出（保持 trader 提案不变 + 风险评论 + 调整后建议）：
  • approved: bool        — 是否放行
  • adjusted_position_pct — 即使放行也可降仓
  • veto_reason           — 否决理由
  • risk_notes            — 风险提示
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.agents.trader import TraderProposal
from backend.analysis.timing.regime import RegimeReport
from backend.config import settings
from backend.decision.signal_policy import ENTRY_RECS, EXIT_RECS, LEGACY_ENTRY_RECS

LONG_RECS = ENTRY_RECS | LEGACY_ENTRY_RECS
STRONG_LONG_RECS = {"可小仓试错", "强买"}


@dataclass
class RiskDecision:
    approved: bool
    adjusted_position_pct: float
    veto_reason: str | None
    risk_notes: list[str]
    final_recommendation: str       # 可能被降级为 "观望" 或 "建议减仓"


def review(
    proposal: TraderProposal,
    regime: RegimeReport | None,
    limit_status: dict | None = None,
    portfolio_drawdown_pct: float = 0.0,
    *,
    long_term_label=None,                   # LongTermLabel | None
) -> RiskDecision:
    """评审 trader 提案"""
    if not settings.risk_manager_enabled:
        return RiskDecision(
            approved=True,
            adjusted_position_pct=proposal.position_pct,
            veto_reason=None,
            risk_notes=[],
            final_recommendation=proposal.recommendation,
        )

    notes: list[str] = []
    veto: str | None = None
    adjusted_pos = proposal.position_pct
    final_rec = proposal.recommendation

    # 1. 大盘极度看空 → 否决买入
    if regime and regime.rsrs_z is not None and regime.rsrs_z < -1.0:
        if proposal.recommendation in LONG_RECS:
            veto = f"大盘 RSRS={regime.rsrs_z:.2f} 极度看空，拒绝建仓"
            final_rec = "观望"
            adjusted_pos = 0.0

    # 2. 板块极弱 → 降级买入
    if regime and regime.diffusion is not None and regime.diffusion < 0.2:
        if proposal.recommendation in STRONG_LONG_RECS:
            notes.append(f"板块扩散={regime.diffusion:.2f} 极弱，降级为可关注")
            final_rec = "可关注"
            adjusted_pos *= 0.7
        elif proposal.recommendation in LONG_RECS:
            notes.append(f"板块扩散={regime.diffusion:.2f} 极弱，仓位减半")
            adjusted_pos *= 0.5

    # 3. 组合回撤超线 → kill switch 软线
    if portfolio_drawdown_pct < -8.0:
        if proposal.recommendation in LONG_RECS:
            veto = f"组合回撤 {portfolio_drawdown_pct:.1f}% 超过 -8%，暂停建仓"
            final_rec = "观望"
            adjusted_pos = 0.0
        else:
            notes.append("组合回撤超线，仅允许平仓操作")

    # 4. 涨跌停约束
    if limit_status:
        if limit_status.get("limit_up") and proposal.recommendation in LONG_RECS:
            notes.append("涨停板买入难成交，建议次日观察")
            adjusted_pos *= 0.5
        if limit_status.get("limit_down") and proposal.recommendation in EXIT_RECS:
            notes.append("跌停板无法卖出，等次日开盘")

    # 5. 极小持仓 → 直接归零
    if 0 < adjusted_pos < 0.02:
        notes.append(f"仓位 {adjusted_pos:.2%} 太小，归零")
        adjusted_pos = 0.0

    # 6. 长期分析师团约束：只有通过质量门且显式启用 enforcement 的标签能改动作/仓位。
    if long_term_label and settings.long_term_team_enabled:
        lbl = long_term_label.label
        kf = (long_term_label.key_findings or [""])[0]
        eligible = bool(getattr(long_term_label, "constraint_eligible", False))
        if not eligible:
            notes.append(f"长期标签未通过质量门，仅展示不约束: {kf}")
        elif not settings.long_term_constraints_enabled:
            notes.append(f"长期标签处于验证模式，仅展示不约束官方动作: {kf}")
        elif lbl == "规避" and proposal.recommendation in LONG_RECS \
                and settings.long_term_avoid_blocks_buy:
            veto = f"长期团判定'规避'：{kf}"
            final_rec = "观望"
            adjusted_pos = 0.0
        elif lbl == "估值偏高" and proposal.recommendation in LONG_RECS:
            factor = settings.long_term_overvalued_position_factor
            notes.append(f"长期团'估值偏高'，仓位 ×{factor}")
            adjusted_pos *= factor
        elif lbl == "观望":
            notes.append(f"长期团'观望'（综合分已截断）: {kf}")

    approved = veto is None
    return RiskDecision(
        approved=approved,
        adjusted_position_pct=round(adjusted_pos, 4),
        veto_reason=veto,
        risk_notes=notes,
        final_recommendation=final_rec,
    )
