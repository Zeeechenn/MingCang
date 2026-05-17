"""
M4.3 Portfolio Manager Agent —— 组合层仓位统筹。

输入：当日所有候选信号（已通过 trader+risk_manager）+ 现有持仓
输出：每只候选的目标仓位 + 拒绝列表 + 板块/总仓位使用情况

差异点（相对 portfolio/combo_weights.py）：
  • combo_weights 假设候选都进场，按算法分配权重
  • PortfolioManager 看 trader 已建议的仓位，再做组合约束裁剪
  • PortfolioManager 知道现有持仓 → 计算可用资金、增减仓动作
  • PortfolioManager 是 Agent，可被 director 调用、可解释决策原因

约束（来自 settings）：
  • max_position_per_stock     (默认 15%)
  • max_position_per_sector    (默认 30%)
  • max_total_equity_pct       (默认 80%)
"""
from __future__ import annotations
from dataclasses import dataclass, field

from backend.config import settings
from backend.decision.signal_policy import ENTRY_RECS, LEGACY_ENTRY_RECS, EXIT_RECS


ENTRY_SET = ENTRY_RECS | LEGACY_ENTRY_RECS


@dataclass
class PortfolioCandidate:
    """单只股票的候选信息（合并 trader 输出 + 现状）"""
    symbol: str
    sector: str
    composite_score: float
    recommendation: str
    confidence: str                    # 高/中/低
    suggested_position_pct: float      # trader/agg 建议仓位 (0~1)
    is_existing: bool = False
    current_position_pct: float = 0.0


@dataclass
class PortfolioAllocation:
    """对单只股票的最终决策"""
    symbol: str
    sector: str
    target_position_pct: float
    delta_position_pct: float          # 与 current 的差（正=加仓 / 负=减仓）
    action: str                        # open / hold / add / reduce / close / reject
    rationale: str


@dataclass
class PortfolioDecision:
    allocations: list[PortfolioAllocation]
    available_capital_pct: float       # 决策后仍剩余的资金比例
    sector_usage: dict[str, float]     # 板块 → 已用占比
    rejected: list[dict] = field(default_factory=list)   # [{symbol, reason}]
    notes: list[str] = field(default_factory=list)


def _action_label(target: float, current: float, is_existing: bool) -> str:
    """根据 target/current 判断动作类型"""
    if target <= 0 and current <= 0:
        return "reject"
    if target <= 0 and is_existing:
        return "close"
    if not is_existing and target > 0:
        return "open"
    if target > current + 1e-6:
        return "add"
    if target < current - 1e-6:
        return "reduce"
    return "hold"


def manage(
    candidates: list[PortfolioCandidate],
    *,
    portfolio_drawdown_pct: float = 0.0,
) -> PortfolioDecision:
    """
    主入口：分配资金 + 检查约束 + 生成动作。

    流程：
      1. 现有持仓占用统计（按板块 + 总额）
      2. 候选按 composite_score 降序排序
      3. 贪心分配：每只取 min(建议仓位, 单股上限, 剩余板块预算, 剩余总预算)
      4. 处理现有持仓（保留 / 减仓 / 平仓）
      5. EXIT 推荐 → 平仓；非 ENTRY 且非 EXIT → 保持现状
    """
    if not settings.portfolio_manager_enabled:
        # 关闭时直接返回 trader 原建议
        allocs = [
            PortfolioAllocation(
                symbol=c.symbol, sector=c.sector,
                target_position_pct=c.suggested_position_pct,
                delta_position_pct=c.suggested_position_pct - c.current_position_pct,
                action=_action_label(c.suggested_position_pct, c.current_position_pct, c.is_existing),
                rationale="PortfolioManager 关闭，沿用 trader 建议",
            )
            for c in candidates
        ]
        return PortfolioDecision(
            allocations=allocs,
            available_capital_pct=1.0 - sum(c.suggested_position_pct for c in candidates),
            sector_usage={},
        )

    max_stock = settings.max_position_per_stock
    max_sector = settings.max_position_per_sector
    max_total = settings.max_total_equity_pct

    # 1. 现有持仓 → 起始板块/总仓位（仅统计非 EXIT 的持仓）
    sector_used: dict[str, float] = {}
    total_used = 0.0
    for c in candidates:
        if c.is_existing and c.recommendation not in EXIT_RECS:
            sector_used[c.sector] = sector_used.get(c.sector, 0.0) + c.current_position_pct
            total_used += c.current_position_pct

    allocations: list[PortfolioAllocation] = []
    rejected: list[dict] = []
    notes: list[str] = []

    # 1.5 组合回撤超 -8% → 禁开新仓 + 减仓提示
    drawdown_freeze = portfolio_drawdown_pct < -8.0
    if drawdown_freeze:
        notes.append(f"组合回撤 {portfolio_drawdown_pct:.1f}% < -8%，冻结新仓")

    # 2. EXIT 推荐 → 直接平仓（释放预算）
    survivors: list[PortfolioCandidate] = []
    for c in candidates:
        if c.recommendation in EXIT_RECS:
            if c.is_existing and c.current_position_pct > 0:
                allocations.append(PortfolioAllocation(
                    symbol=c.symbol, sector=c.sector,
                    target_position_pct=0.0,
                    delta_position_pct=-c.current_position_pct,
                    action="close",
                    rationale=f"信号={c.recommendation}，平仓释放 {c.current_position_pct:.1%}",
                ))
                sector_used[c.sector] = max(0.0, sector_used.get(c.sector, 0.0) - c.current_position_pct)
                total_used -= c.current_position_pct
            else:
                allocations.append(PortfolioAllocation(
                    symbol=c.symbol, sector=c.sector,
                    target_position_pct=0.0, delta_position_pct=0.0,
                    action="reject",
                    rationale=f"信号={c.recommendation}，且无持仓",
                ))
        else:
            survivors.append(c)

    # 3. 按综合分降序处理剩余候选
    survivors.sort(key=lambda c: c.composite_score, reverse=True)

    for c in survivors:
        is_entry = c.recommendation in ENTRY_SET
        suggested = c.suggested_position_pct

        # 现有持仓但非 ENTRY → 维持现状
        if not is_entry:
            if c.is_existing:
                allocations.append(PortfolioAllocation(
                    symbol=c.symbol, sector=c.sector,
                    target_position_pct=c.current_position_pct,
                    delta_position_pct=0.0,
                    action="hold",
                    rationale=f"信号={c.recommendation}，保持现仓 {c.current_position_pct:.1%}",
                ))
            else:
                allocations.append(PortfolioAllocation(
                    symbol=c.symbol, sector=c.sector,
                    target_position_pct=0.0, delta_position_pct=0.0,
                    action="reject",
                    rationale=f"信号={c.recommendation}，不达入场标准",
                ))
            continue

        # 新建仓 / 加仓需要预算
        if drawdown_freeze and not c.is_existing:
            rejected.append({"symbol": c.symbol, "reason": "组合回撤冻结新仓"})
            allocations.append(PortfolioAllocation(
                symbol=c.symbol, sector=c.sector,
                target_position_pct=c.current_position_pct,
                delta_position_pct=0.0,
                action="reject",
                rationale="组合回撤冻结新仓",
            ))
            continue

        # 约束链：单股 → 板块剩余 → 总仓剩余
        sector_remaining = max(0.0, max_sector - sector_used.get(c.sector, 0.0))
        total_remaining = max(0.0, max_total - total_used)
        target = min(suggested, max_stock, sector_remaining, total_remaining)
        # 增量必须从 current 起算
        if c.is_existing:
            target = max(target, c.current_position_pct)   # 不强制减仓
            target = min(target, c.current_position_pct + (max_stock - c.current_position_pct))

        # 极小仓位归零（< 2%）
        if 0 < target < 0.02:
            rejected.append({"symbol": c.symbol, "reason": f"约束后仓位 {target:.2%} 太小"})
            allocations.append(PortfolioAllocation(
                symbol=c.symbol, sector=c.sector,
                target_position_pct=c.current_position_pct,
                delta_position_pct=0.0,
                action="reject",
                rationale=f"约束后仓位太小（{target:.2%}），归零",
            ))
            continue

        # 板块/总仓预算耗尽
        if target == 0 and is_entry:
            reasons = []
            if sector_remaining == 0:
                reasons.append(f"板块 {c.sector} 已达上限 {max_sector:.0%}")
            if total_remaining == 0:
                reasons.append(f"总仓位已达上限 {max_total:.0%}")
            reason = "; ".join(reasons) or "无可用预算"
            rejected.append({"symbol": c.symbol, "reason": reason})
            allocations.append(PortfolioAllocation(
                symbol=c.symbol, sector=c.sector,
                target_position_pct=c.current_position_pct,
                delta_position_pct=0.0,
                action="reject",
                rationale=reason,
            ))
            continue

        # 接受
        delta = target - c.current_position_pct
        action = _action_label(target, c.current_position_pct, c.is_existing)
        sector_used[c.sector] = max(0.0, sector_used.get(c.sector, 0.0) + delta)
        total_used = max(0.0, total_used + delta)

        rationale = (
            f"综合分 {c.composite_score:+.0f}，建议 {suggested:.1%}，"
            f"约束后 {target:.1%}（单股上限 {max_stock:.0%}）"
        )
        if target < suggested:
            rationale += " — 受约束裁剪"

        allocations.append(PortfolioAllocation(
            symbol=c.symbol, sector=c.sector,
            target_position_pct=round(target, 4),
            delta_position_pct=round(delta, 4),
            action=action,
            rationale=rationale,
        ))

    available = max(0.0, 1.0 - total_used)
    return PortfolioDecision(
        allocations=allocations,
        available_capital_pct=round(available, 4),
        sector_usage={k: round(v, 4) for k, v in sector_used.items()},
        rejected=rejected,
        notes=notes,
    )


def decision_to_dict(decision: PortfolioDecision) -> dict:
    """序列化 PortfolioDecision（写入 audit/前端）"""
    return {
        "allocations": [
            {
                "symbol": a.symbol,
                "sector": a.sector,
                "target_position_pct": a.target_position_pct,
                "delta_position_pct": a.delta_position_pct,
                "action": a.action,
                "rationale": a.rationale,
            }
            for a in decision.allocations
        ],
        "available_capital_pct": decision.available_capital_pct,
        "sector_usage": decision.sector_usage,
        "rejected": decision.rejected,
        "notes": decision.notes,
    }
