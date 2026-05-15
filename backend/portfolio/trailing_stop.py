"""
Trailing Stop 跟踪（阶段B）

替换原"持有满5日强制平仓"的逻辑：
  • 初始止损 = 买入价 - ATR×2
  • 持仓期间记录最高收盘价 highest_close
  • 每日动态止损 = max(初始止损, highest_close - ATR×trailing_atr_mult)
  • 触及止损 → 平仓；触及止盈 → 平仓
  • 时间退出默认关闭，仅在回测/实验显式开启

落库位置：~/.stock-sage/positions.json
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

from backend.config import settings

POSITIONS_PATH = Path.home() / ".stock-sage" / "positions.json"


@dataclass
class TrailingStopTracker:
    symbol: str
    entry_date: str
    entry_price: float
    entry_atr: float
    initial_stop: float
    take_profit: float
    highest_close: float
    current_stop: float
    days_held: int = 0
    status: str = "open"   # open / stopped / take_profit / timeout
    exit_date: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @classmethod
    def open(cls, symbol: str, entry_date: str, entry_price: float, atr: float,
             atr_mult: float | None = None, rr: float | None = None) -> "TrailingStopTracker":
        """Create a new open position tracker with initial stop and take-profit levels."""
        atr_mult = atr_mult or settings.atr_multiplier
        rr = rr or settings.risk_reward_ratio
        stop = entry_price - atr * atr_mult
        take = entry_price + atr * atr_mult * rr
        return cls(
            symbol=symbol,
            entry_date=entry_date,
            entry_price=entry_price,
            entry_atr=atr,
            initial_stop=round(stop, 3),
            take_profit=round(take, 3),
            highest_close=entry_price,
            current_stop=round(stop, 3),
        )


def update_trailing_stop(pos: TrailingStopTracker, current_high: float,
                         current_low: float, current_close: float,
                         current_date: str) -> TrailingStopTracker:
    """
    每个交易日调用一次。更新 highest_close 与 current_stop，必要时关闭持仓。

    关闭优先级：止损 > 止盈 > 可选时间退出
    """
    pos.days_held += 1

    if current_low <= pos.current_stop:
        pos.status = "stopped"
        pos.exit_date = current_date
        pos.exit_price = pos.current_stop
        pos.exit_reason = "止损"
        return pos

    if current_high >= pos.take_profit:
        pos.status = "take_profit"
        pos.exit_date = current_date
        pos.exit_price = pos.take_profit
        pos.exit_reason = "止盈"
        return pos

    if settings.time_exit_enabled and pos.days_held >= settings.max_hold_days:
        pos.status = "timeout"
        pos.exit_date = current_date
        pos.exit_price = current_close
        pos.exit_reason = "超时"
        return pos

    if settings.trailing_stop_enabled:
        if current_close > pos.highest_close:
            pos.highest_close = current_close
            trailing = current_close - pos.entry_atr * settings.trailing_atr_mult
            pos.current_stop = round(max(pos.current_stop, trailing), 3)

    return pos


def save_positions(positions: list[TrailingStopTracker]) -> None:
    """Persist position list to disk as JSON."""
    POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSITIONS_PATH.write_text(
        json.dumps([asdict(p) for p in positions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_positions() -> list[TrailingStopTracker]:
    """Load persisted positions from disk, returning empty list if not found."""
    if not POSITIONS_PATH.exists():
        return []
    data = json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
    return [TrailingStopTracker(**d) for d in data]
