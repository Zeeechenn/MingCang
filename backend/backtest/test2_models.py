"""Tracked replay models shared by M58/M60 and the local test2 runner.

This module contains only public code and constants. Personal replay state,
universes, reports, and real-money records remain outside version control.
"""

from __future__ import annotations

from dataclasses import dataclass, field

START_DATE = "2026-07-03"
COMMISSION_ROUND_TRIP_PCT = 0.20
POSITION_PCT = 0.15
DEFAULT_MAX_POSITIONS = 3
SIGNAL_REVERSAL_THRESHOLD = -15.0
SIGNAL_REVERSAL_MIN_HOLD_DAYS = 2

SECTOR_CAP_PCT = 0.30
MAX_PER_SECTOR = int(SECTOR_CAP_PCT / POSITION_PCT)

_SEMI_AI_KEYWORDS = ("光模块", "半导体", "算力", "存储")
SEMI_AI_THEME = "半导体/AI算力"


def broad_sector(fine: str) -> str:
    """Collapse fine-grained semiconductor/AI labels into one risk bucket."""
    if fine and any(keyword in fine for keyword in _SEMI_AI_KEYWORDS):
        return SEMI_AI_THEME
    return fine or "未分类"


@dataclass(frozen=True)
class Framework:
    key: str
    label: str
    quant_weight: float
    tech_weight: float
    sent_weight: float
    entry_threshold: float


FRAMEWORKS: dict[str, Framework] = {
    "A_quant_on": Framework("A_quant_on", "A组 quant_on", 0.45, 0.40, 0.15, 20.0),
    "B_quant_off": Framework("B_quant_off", "B组 quant_off", 0.0, 0.60, 0.40, 25.0),
}

QUANT_SWEEP_FRAMEWORKS: dict[str, Framework] = {
    "Q000": Framework("Q000", "Q=0.00", 0.000, 0.600, 0.400, 20.0),
    "Q225": Framework("Q225", "Q=0.225", 0.225, 0.465, 0.310, 20.0),
    "Q450": Framework("Q450", "Q=0.45", 0.450, 0.330, 0.220, 20.0),
}


@dataclass(frozen=True)
class Signal:
    symbol: str
    name: str
    date: str
    quant: float
    tech: float
    sent: float
    stop_loss: float | None
    take_profit: float | None


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class Holding:
    symbol: str
    name: str
    entry_signal_date: str
    entry_date: str
    entry_price: float
    stop_loss: float | None
    take_profit: float | None


@dataclass
class Trade:
    symbol: str
    name: str
    entry_signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    gross_return_pct: float
    net_return_pct: float


@dataclass
class FrameworkResult:
    framework: Framework
    open_holdings: list[Holding] = field(default_factory=list)
    closed_trades: list[Trade] = field(default_factory=list)
    daily_entries: dict[str, list[str]] = field(default_factory=dict)


def composite_for(signal: Signal, framework: Framework) -> float:
    score = (
        signal.quant * framework.quant_weight
        + signal.tech * framework.tech_weight
        + signal.sent * framework.sent_weight
    )
    return round(max(-100.0, min(100.0, score)), 1)
