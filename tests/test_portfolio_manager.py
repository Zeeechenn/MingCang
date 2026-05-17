"""M4.3 Portfolio Manager 测试。

覆盖：
  • 单股上限裁剪
  • 板块上限裁剪
  • 总仓位上限裁剪
  • EXIT 信号 → 平仓
  • 持仓 + 非 ENTRY 信号 → hold
  • 新候选 + 非 ENTRY → reject
  • 组合回撤 < -8% → 冻结新仓
  • 候选按综合分降序处理
  • disabled 时沿用 trader 建议
  • 极小仓位归零
"""
from __future__ import annotations
from unittest.mock import patch

from backend.agents.portfolio_manager import (
    PortfolioCandidate,
    decision_to_dict,
    manage,
)


def _candidate(
    sym: str, sector: str = "半导体", score: float = 30,
    rec: str = "可小仓试错", conf: str = "中",
    suggested: float = 0.10,
    existing: bool = False, current: float = 0.0,
) -> PortfolioCandidate:
    return PortfolioCandidate(
        symbol=sym, sector=sector,
        composite_score=score, recommendation=rec, confidence=conf,
        suggested_position_pct=suggested,
        is_existing=existing, current_position_pct=current,
    )


def _patch_settings(**overrides):
    """统一 patch 配置（仓位上限等）"""
    defaults = dict(
        portfolio_manager_enabled=True,
        max_position_per_stock=0.15,
        max_position_per_sector=0.30,
        max_total_equity_pct=0.80,
    )
    defaults.update(overrides)
    return patch("backend.agents.portfolio_manager.settings", **{
        k: v for k, v in defaults.items()
    })


# ── 基础约束 ─────────────────────────────────────────────────────────

def test_single_stock_cap_applied():
    """建议 25% 应被裁到 15% 单股上限"""
    with _patch_settings():
        d = manage([_candidate("600519", suggested=0.25)])
    alloc = d.allocations[0]
    assert alloc.action == "open"
    assert alloc.target_position_pct == 0.15
    assert "裁剪" in alloc.rationale or alloc.target_position_pct < 0.25


def test_sector_cap_applied():
    """同板块 3 只 15% → 第 3 只受板块 30% 上限约束"""
    with _patch_settings():
        cands = [
            _candidate("600519", sector="半导体", suggested=0.15, score=80),
            _candidate("000001", sector="半导体", suggested=0.15, score=70),
            _candidate("000002", sector="半导体", suggested=0.15, score=60),
        ]
        d = manage(cands)
    # 前两只应进入，第3只被板块上限拒绝
    actions = [a.action for a in d.allocations]
    assert actions.count("open") == 2
    assert actions.count("reject") == 1
    rejected = [a for a in d.allocations if a.action == "reject"][0]
    assert "板块" in rejected.rationale


def test_total_equity_cap_applied():
    """80% 总上限：6 只 15% 无法全部进入"""
    with _patch_settings():
        cands = [
            _candidate(f"sym{i}", sector=f"行业{i}",
                       suggested=0.15, score=100 - i)
            for i in range(6)
        ]
        d = manage(cands)
    # 5 只能进入（5×0.15 = 0.75 < 0.80），第6只仍可进 0.05
    used = sum(a.target_position_pct for a in d.allocations if a.action == "open")
    assert used <= 0.80 + 1e-6


def test_score_order_priority():
    """高分候选优先获取预算"""
    with _patch_settings(max_position_per_sector=0.15):
        cands = [
            _candidate("low", sector="半导体", suggested=0.15, score=40),
            _candidate("high", sector="半导体", suggested=0.15, score=80),
        ]
        d = manage(cands)
    high = next(a for a in d.allocations if a.symbol == "high")
    low = next(a for a in d.allocations if a.symbol == "low")
    assert high.action == "open"
    assert low.action == "reject"


# ── EXIT / hold / reject ─────────────────────────────────────────────

def test_exit_signal_closes_position():
    with _patch_settings():
        d = manage([_candidate(
            "600519", rec="规避", suggested=0.0,
            existing=True, current=0.10,
        )])
    alloc = d.allocations[0]
    assert alloc.action == "close"
    assert alloc.target_position_pct == 0.0
    assert alloc.delta_position_pct == -0.10


def test_exit_signal_no_position_rejects():
    with _patch_settings():
        d = manage([_candidate("600519", rec="规避", suggested=0.0)])
    assert d.allocations[0].action == "reject"


def test_hold_existing_with_non_entry_signal():
    """已持仓但信号变成'可关注' → hold"""
    with _patch_settings():
        d = manage([_candidate(
            "600519", rec="可关注", suggested=0.0,
            existing=True, current=0.10,
        )])
    alloc = d.allocations[0]
    assert alloc.action == "hold"
    assert alloc.target_position_pct == 0.10


def test_reduce_existing_releases_budget():
    """已有仓位超过单股上限时，减仓应释放板块与总仓预算"""
    with _patch_settings(max_position_per_stock=0.15, max_position_per_sector=0.30):
        d = manage([_candidate(
            "600519", sector="食品饮料", suggested=0.30,
            existing=True, current=0.20,
        )])
    alloc = d.allocations[0]
    assert alloc.action == "reduce"
    assert alloc.target_position_pct == 0.15
    assert d.sector_usage["食品饮料"] == 0.15
    assert d.available_capital_pct == 0.85


def test_reject_new_non_entry():
    """新候选 + 非 ENTRY 信号 → reject"""
    with _patch_settings():
        d = manage([_candidate("600519", rec="可关注", suggested=0.0)])
    assert d.allocations[0].action == "reject"


# ── 回撤冻结 ─────────────────────────────────────────────────────────

def test_drawdown_freeze_blocks_new_positions():
    """组合回撤 -9% → 禁开新仓"""
    with _patch_settings():
        d = manage(
            [_candidate("600519", suggested=0.15)],
            portfolio_drawdown_pct=-9.0,
        )
    assert d.allocations[0].action == "reject"
    assert "回撤" in d.allocations[0].rationale
    assert any("冻结" in n for n in d.notes)


def test_drawdown_freeze_allows_close():
    """回撤冻结期可平仓"""
    with _patch_settings():
        d = manage(
            [_candidate("600519", rec="规避", existing=True, current=0.10)],
            portfolio_drawdown_pct=-9.0,
        )
    assert d.allocations[0].action == "close"


# ── 极小仓位归零 ─────────────────────────────────────────────────────

def test_tiny_position_dropped():
    """约束后仓位 < 2% → 拒绝"""
    with _patch_settings(max_position_per_sector=0.16):
        cands = [
            _candidate("a", sector="半导体", suggested=0.15, score=90),
            _candidate("b", sector="半导体", suggested=0.15, score=80),  # 剩余 0.01
        ]
        d = manage(cands)
    b = next(a for a in d.allocations if a.symbol == "b")
    assert b.action == "reject"
    assert "太小" in b.rationale


# ── disabled 路径 ────────────────────────────────────────────────────

def test_disabled_passthrough():
    """portfolio_manager_enabled=False → 沿用 trader 建议"""
    with _patch_settings(portfolio_manager_enabled=False):
        d = manage([_candidate("600519", suggested=0.25)])
    assert d.allocations[0].target_position_pct == 0.25
    assert "沿用" in d.allocations[0].rationale


# ── 序列化 ───────────────────────────────────────────────────────────

def test_decision_to_dict():
    with _patch_settings():
        d = manage([_candidate("600519", suggested=0.10)])
    out = decision_to_dict(d)
    assert "allocations" in out
    assert "sector_usage" in out
    assert "rejected" in out
    assert out["allocations"][0]["symbol"] == "600519"
