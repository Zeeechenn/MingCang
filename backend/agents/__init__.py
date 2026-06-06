"""
阶段C 多 Agent 架构（参考 TradingAgents 论文 + FinMem 分层记忆）

角色分工：
  Analysts:    technical / sentiment / quant / news 四路独立产出结构化报告
  Researchers: bull / bear 多空辩论（保留现有 LLM 仲裁逻辑）
  Trader:     综合所有 analyst + researcher 输出 → 推荐 + 仓位
  RiskManager: 对 trader 输出有否决权（结合 regime/历史回撤）

Pipeline 通过 settings.multi_agent_enabled 控制；关闭时退化为原 aggregator 逻辑。
"""
from backend.agents.pipeline import AgentDecision, PipelineInputs, run_pipeline
from backend.agents.portfolio_manager import (
    PortfolioAllocation,
    PortfolioCandidate,
    PortfolioDecision,
    decision_to_dict,
)
from backend.agents.portfolio_manager import (
    manage as run_portfolio_manager,
)

__all__ = [
    "run_pipeline",
    "PipelineInputs",
    "AgentDecision",
    "run_portfolio_manager",
    "PortfolioCandidate",
    "PortfolioAllocation",
    "PortfolioDecision",
    "decision_to_dict",
]
