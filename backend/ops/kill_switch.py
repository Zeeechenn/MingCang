"""
Kill Switch（Tier 4）

从"被动观察"升级到"主动安全"。监控四类风险：
  (a) 连续 N 笔信号亏损（默认 N=5）
  (b) 单日组合回撤 > X%（默认 5%，需外部 trades 计算后调用 trigger）
  (c) DB 不可达 / 数据陈旧（最新价格距今 > N 天）
  (d) 手动触发（用户判断异常）

触发后：
  • 写状态文件 ~/.stock-sage/kill_switch.json
  • scheduler 的 job_postmarket / job_stoploss_check 入口先 check is_active()，true 则跳过
  • Bark 推送告警（若配置）
  • /api/system/health 上报状态

reset() 显式清除状态（需要用户主动操作）。
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

STATE_PATH = Path.home() / ".stock-sage" / "kill_switch.json"

DEFAULT_CONSECUTIVE_LOSSES = 8   # M2.2 测试期 2-3 个月震荡市预留
DEFAULT_DRAWDOWN_PCT = 7.0       # 单日组合回撤阈值 %（A 股单日 -5% 时常出现，7% 留缓冲）
DEFAULT_DATA_STALE_DAYS = 14     # 数据最新日期距今 > N 天视为陈旧（M2.2 测试期 2-3 个月，含国庆/春节级长假冗余）


@dataclass
class KillSwitchState:
    active: bool
    reason: str
    triggered_at: str   # ISO 时间戳
    metadata: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _read_state() -> KillSwitchState | None:
    """Read kill switch state from disk, returning None if absent or corrupt."""
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return KillSwitchState(**data)
    except Exception as e:
        logger.warning("kill_switch 状态文件读取失败: %s", e)
        return None


def _write_state(state: KillSwitchState | None) -> None:
    """Write kill switch state to disk, or delete the file if state is None."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if state is None:
        if STATE_PATH.exists():
            STATE_PATH.unlink()
        return
    STATE_PATH.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_active() -> bool:
    """Return True if the kill switch is currently active."""
    state = _read_state()
    return bool(state and state.active)


def current_state() -> dict | None:
    """Return the current kill switch state as a dict, or None if not triggered."""
    state = _read_state()
    return state.to_dict() if state else None


def trigger(reason: str, metadata: dict | None = None, push: bool = True) -> KillSwitchState:
    """显式触发熔断。push=True 时尝试 Bark 推送。"""
    state = KillSwitchState(
        active=True,
        reason=reason,
        triggered_at=datetime.utcnow().isoformat(timespec="seconds"),
        metadata=metadata or {},
    )
    _write_state(state)
    logger.warning("🛑 Kill switch triggered: %s | %s", reason, metadata or {})
    if push:
        try:
            from backend.notification import bark
            bark.send(
                title=f"🛑 StockSage 熔断：{reason[:30]}",
                body=f"{reason}｜元数据 {json.dumps(metadata or {}, ensure_ascii=False)[:150]}",
                sound="alarm",
            )
        except Exception as e:
            logger.warning("kill_switch Bark 推送失败: %s", e)
    return state


def reset() -> None:
    """清除熔断状态。需要用户主动调用。"""
    _write_state(None)
    logger.info("✅ Kill switch reset by user.")


# ── 自动检测规则 ────────────────────────────────────────────────────

def detect_consecutive_losses(
    trade_returns: Iterable[float],
    threshold: int = DEFAULT_CONSECUTIVE_LOSSES,
) -> int:
    """
    扫描收益序列尾部，返回最近连续亏损笔数。
    用于盘后 job 调用：把过去 N 笔信号收益传进来。
    """
    streak = 0
    for r in reversed(list(trade_returns)):
        if r < 0:
            streak += 1
        else:
            break
    return streak


def check_consecutive_losses(
    trade_returns: Iterable[float],
    threshold: int = DEFAULT_CONSECUTIVE_LOSSES,
) -> KillSwitchState | None:
    """Trigger kill switch if consecutive losses meet or exceed threshold."""
    streak = detect_consecutive_losses(trade_returns, threshold)
    if streak >= threshold:
        return trigger(
            reason=f"连续 {streak} 笔信号亏损（阈值 {threshold}）",
            metadata={"consecutive_losses": streak, "threshold": threshold},
        )
    return None


def check_daily_drawdown(
    drawdown_pct: float,
    threshold_pct: float = DEFAULT_DRAWDOWN_PCT,
) -> KillSwitchState | None:
    """Trigger kill switch if daily drawdown exceeds threshold; drawdown_pct is a positive number."""
    if drawdown_pct >= threshold_pct:
        return trigger(
            reason=f"单日回撤 {drawdown_pct:.2f}% ≥ 阈值 {threshold_pct:.2f}%",
            metadata={"drawdown_pct": drawdown_pct, "threshold": threshold_pct},
        )
    return None


def check_data_staleness(
    latest_price_date: str | None,
    today: datetime | None = None,
    threshold_days: int = DEFAULT_DATA_STALE_DAYS,
) -> KillSwitchState | None:
    """Trigger kill switch if latest_price_date is None or older than threshold_days."""
    if not latest_price_date:
        return trigger(reason="DB 中无价格数据",
                       metadata={"latest_price_date": None})
    today = today or datetime.utcnow()
    try:
        last = datetime.strptime(latest_price_date, "%Y-%m-%d")
    except ValueError:
        return trigger(reason=f"latest_price_date 格式异常：{latest_price_date}",
                       metadata={"latest_price_date": latest_price_date})
    age_days = (today - last).days
    if age_days > threshold_days:
        return trigger(
            reason=f"数据陈旧：最新价格日 {latest_price_date}，距今 {age_days} 天 > {threshold_days}",
            metadata={"latest_price_date": latest_price_date, "age_days": age_days},
        )
    return None


def run_all_checks(
    trade_returns: Iterable[float] | None = None,
    drawdown_pct: float | None = None,
    latest_price_date: str | None = None,
) -> KillSwitchState | None:
    """
    一次性跑全部自动检查。返回第一个触发的状态；都通过返回 None。
    已激活时直接返回当前状态（不重复触发）。
    """
    existing = _read_state()
    if existing and existing.active:
        return existing
    if trade_returns is not None:
        s = check_consecutive_losses(trade_returns)
        if s:
            return s
    if drawdown_pct is not None:
        s = check_daily_drawdown(drawdown_pct)
        if s:
            return s
    if latest_price_date is not None:
        s = check_data_staleness(latest_price_date)
        if s:
            return s
    return None
