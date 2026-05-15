"""
QFII Outflow 反向规避分析师

只做"反向规避"，不做正向加分。理由（与 PROJECT.md 设计讨论一致）：
  • 披露滞后 30-90 天，正向信号到手时行情多半已走完
  • 北向通道走的仓位看不到，正向信号样本严重偏少 → 小盘股偏差
  • 反向"持续撤离"语义更稳：QFII 长期看空通常先减仓再公开看空

触发规则（settings 全部可调，默认严格）：
  • 最近 quarters 季内（默认 4）
  • 至少 min_distinct_holders 家不同 QFII（默认 2）
  • 累计净减仓季度 ≥ min_consecutive_drop_quarters（默认 2）
  • 减仓总量占历史峰值持股的 ≥ drop_ratio_threshold（默认 0.20）
  • 满足 → label_vote="规避"，score=-70；不满足 → confidence=0（不影响聚合）
"""
from __future__ import annotations
import logging
from collections import defaultdict

from backend.agents.long_term.base import LongTermReport
from backend.config import settings
from backend.data.qfii_holdings import get_qfii_history

logger = logging.getLogger(__name__)

ROLE = "flow"


def _holder_timelines(history: dict[str, list[dict]]) -> dict[str, list[tuple[str, int]]]:
    """
    把 {quarter: [holdings]} 转成 {holder: [(quarter, shares), ...]}，按时间正序。

    退出前十大的季度记为 shares=0，便于"完全退出"也算减仓。
    """
    quarters_sorted = sorted(history.keys())
    all_holders: set[str] = set()
    for rows in history.values():
        for row in rows:
            all_holders.add(row["holder"])

    timelines: dict[str, list[tuple[str, int]]] = {}
    for holder in all_holders:
        seen_any = False
        line: list[tuple[str, int]] = []
        for q in quarters_sorted:
            row = next((r for r in history[q] if r["holder"] == holder), None)
            if row is not None:
                seen_any = True
                line.append((q, int(row.get("shares") or 0)))
            elif seen_any:
                line.append((q, 0))
        if line:
            timelines[holder] = line
    return timelines


def _holder_drop_stats(timeline: list[tuple[str, int]]) -> dict:
    """单个 holder 的减仓统计：减仓季数、累计减仓量、历史峰值"""
    drop_quarters = 0
    peak = 0
    total_drop = 0
    last_shares = None
    for _, shares in timeline:
        peak = max(peak, shares)
        if last_shares is not None and shares < last_shares:
            drop_quarters += 1
            total_drop += last_shares - shares
        last_shares = shares
    final = timeline[-1][1] if timeline else 0
    net_change = final - timeline[0][1] if timeline else 0
    return {
        "drop_quarters": drop_quarters,
        "peak": peak,
        "total_drop": total_drop,
        "net_change": net_change,
        "final": final,
    }


def _evaluate(history: dict[str, list[dict]]) -> dict:
    """聚合所有 QFII 的减仓情况，返回触发判定 + 证据"""
    timelines = _holder_timelines(history)

    holders_in_drop: list[str] = []
    total_peak = 0
    total_net_drop = 0
    drop_quarter_counts: list[int] = []

    for holder, line in timelines.items():
        stats = _holder_drop_stats(line)
        total_peak += stats["peak"]
        if stats["net_change"] < 0:
            holders_in_drop.append(holder)
            total_net_drop += -stats["net_change"]
            drop_quarter_counts.append(stats["drop_quarters"])

    distinct_holders_dropping = len(holders_in_drop)
    max_consecutive_drop = max(drop_quarter_counts) if drop_quarter_counts else 0
    drop_ratio = (total_net_drop / total_peak) if total_peak > 0 else 0.0

    return {
        "distinct_holders_dropping": distinct_holders_dropping,
        "max_consecutive_drop": max_consecutive_drop,
        "drop_ratio": drop_ratio,
        "total_peak_shares": total_peak,
        "total_net_drop": total_net_drop,
        "holders_in_drop": holders_in_drop,
        "all_holders_count": len(timelines),
    }


def _triggers_avoid(stats: dict) -> bool:
    """Return True if aggregated QFII stats cross the avoid-trigger thresholds."""
    return (
        stats["distinct_holders_dropping"] >= settings.qfii_flow_min_holders
        and stats["max_consecutive_drop"] >= settings.qfii_flow_min_drop_quarters
        and stats["drop_ratio"] >= settings.qfii_flow_drop_ratio
    )


def analyze(symbol: str, db=None, history: dict[str, list[dict]] | None = None) -> LongTermReport:
    """
    db 参数为兼容 team 调用签名保留，未使用。
    history 注入用于测试；生产路径走 get_qfii_history 拉缓存/AkShare。
    """
    if history is None:
        try:
            history = get_qfii_history(symbol, quarters=settings.qfii_flow_lookback_quarters)
        except Exception as e:
            logger.warning("QFII 历史拉取失败 %s: %s", symbol, e)
            history = {}

    has_any_qfii = any(rows for rows in history.values())
    if not has_any_qfii:
        return LongTermReport(
            role=ROLE,
            score=0.0,
            confidence=0.0,
            label_vote="观望",
            key_findings=[],
            raw={"reason": "无 QFII 进入前十大流通股东", "history": history},
        )

    stats = _evaluate(history)

    if _triggers_avoid(stats):
        findings = [
            f"近 {settings.qfii_flow_lookback_quarters} 季 {stats['distinct_holders_dropping']} 家外资 QFII 持续减仓",
            f"累计净减仓占历史峰值 {stats['drop_ratio'] * 100:.1f}%（阈值 {settings.qfii_flow_drop_ratio * 100:.0f}%）",
            f"撤离机构：{', '.join(stats['holders_in_drop'][:3])}",
        ]
        return LongTermReport(
            role=ROLE,
            score=-70.0,
            confidence=0.8,
            label_vote="规避",
            key_findings=findings,
            raw={"stats": stats, "history": history},
        )

    return LongTermReport(
        role=ROLE,
        score=0.0,
        confidence=0.0,
        label_vote="观望",
        key_findings=[],
        raw={"stats": stats, "history": history, "reason": "未触发反向规避阈值"},
    )
