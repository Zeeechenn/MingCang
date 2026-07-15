"""Canonical market identity, clock, and microstructure contracts.

The profiles intentionally share an interface rather than one rule set.  They
describe research/simulation assumptions only; broker-specific restrictions
remain outside MingCang and no profile authorizes real orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

SUPPORTED_MARKETS = ("CN", "HK", "US")


@dataclass(frozen=True)
class MarketCostProfile:
    """Auditable percentage/per-share assumptions used by local replay."""

    commission_buy: float
    commission_sell: float
    tax_buy: float
    tax_sell: float
    regulatory_buy: float
    regulatory_sell: float
    slippage_buy: float
    slippage_sell: float
    sell_fee_per_share: float = 0.0
    sell_fee_cap: float | None = None
    version: str = "m67-v1"

    @property
    def percentage_round_trip(self) -> float:
        return sum((
            self.commission_buy,
            self.commission_sell,
            self.tax_buy,
            self.tax_sell,
            self.regulatory_buy,
            self.regulatory_sell,
            self.slippage_buy,
            self.slippage_sell,
        ))

    def estimate_round_trip(self, *, notional: float, shares: float = 0.0) -> dict[str, float | str]:
        percentage_cost = max(0.0, float(notional)) * self.percentage_round_trip
        sell_share_fee = max(0.0, float(shares)) * self.sell_fee_per_share
        if self.sell_fee_cap is not None:
            sell_share_fee = min(sell_share_fee, self.sell_fee_cap)
        amount = percentage_cost + sell_share_fee
        return {
            "amount": round(amount, 6),
            "rate": round(amount / notional, 10) if notional > 0 else 0.0,
            "percentage_rate": round(self.percentage_round_trip, 10),
            "sell_share_fee": round(sell_share_fee, 6),
            "version": self.version,
        }


@dataclass(frozen=True)
class MarketProfile:
    market: str
    label: str
    exchange: str
    currency: str
    timezone: str
    calendar_code: str
    benchmark_symbol: str
    benchmark_name: str
    premarket_time: time
    regular_open: time
    regular_close: time
    postmarket_time: time
    settlement_days: int
    same_day_sell_allowed: bool
    default_lot_size: int | None
    odd_lot_supported: bool
    fractional_supported: bool
    price_limit_model: str
    broker_constraints_required: bool
    costs: MarketCostProfile


_PROFILES = {
    "CN": MarketProfile(
        market="CN",
        label="A股",
        exchange="SSE/SZSE/BSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        calendar_code="XSHG",
        benchmark_symbol="sh000300",
        benchmark_name="沪深300",
        premarket_time=time(8, 30),
        regular_open=time(9, 30),
        regular_close=time(15, 0),
        postmarket_time=time(16, 0),
        settlement_days=1,
        same_day_sell_allowed=False,
        default_lot_size=100,
        odd_lot_supported=False,
        fractional_supported=False,
        price_limit_model="cn_board_specific",
        broker_constraints_required=False,
        costs=MarketCostProfile(
            commission_buy=0.0005,
            commission_sell=0.0005,
            tax_buy=0.0,
            tax_sell=0.001,
            regulatory_buy=0.0,
            regulatory_sell=0.0,
            slippage_buy=0.001,
            slippage_sell=0.001,
            version="cn-m67-v1",
        ),
    ),
    "HK": MarketProfile(
        market="HK",
        label="港股",
        exchange="HKEX",
        currency="HKD",
        timezone="Asia/Hong_Kong",
        calendar_code="XHKG",
        benchmark_symbol="^HSI",
        benchmark_name="恒生指数",
        premarket_time=time(8, 30),
        regular_open=time(9, 30),
        regular_close=time(16, 10),
        postmarket_time=time(16, 30),
        settlement_days=2,
        same_day_sell_allowed=True,
        default_lot_size=None,
        odd_lot_supported=True,
        fractional_supported=False,
        price_limit_model="hk_session_controls_no_daily_limit",
        broker_constraints_required=True,
        costs=MarketCostProfile(
            commission_buy=0.0003,
            commission_sell=0.0003,
            tax_buy=0.001,
            tax_sell=0.001,
            regulatory_buy=0.000085,
            regulatory_sell=0.000085,
            slippage_buy=0.001,
            slippage_sell=0.001,
            version="hk-m67-2026-07",
        ),
    ),
    "US": MarketProfile(
        market="US",
        label="美股",
        exchange="NYSE/Nasdaq",
        currency="USD",
        timezone="America/New_York",
        calendar_code="XNYS",
        benchmark_symbol="^GSPC",
        benchmark_name="S&P 500",
        premarket_time=time(9, 0),
        regular_open=time(9, 30),
        regular_close=time(16, 0),
        postmarket_time=time(16, 20),
        settlement_days=1,
        same_day_sell_allowed=True,
        default_lot_size=1,
        odd_lot_supported=True,
        fractional_supported=True,
        price_limit_model="us_luld_and_market_circuit_breakers",
        broker_constraints_required=True,
        costs=MarketCostProfile(
            commission_buy=0.0,
            commission_sell=0.0,
            tax_buy=0.0,
            tax_sell=0.0,
            regulatory_buy=0.0,
            regulatory_sell=0.0000206,
            slippage_buy=0.0005,
            slippage_sell=0.0005,
            sell_fee_per_share=0.000195,
            sell_fee_cap=9.79,
            version="us-m67-2026-07",
        ),
    ),
}


def normalize_market(market: str | None) -> str:
    value = str(market or "CN").strip().upper()
    if value not in _PROFILES:
        raise ValueError(f"unsupported market: {market}")
    return value


def normalize_symbol(symbol: str, market: str) -> str:
    value = str(symbol).strip().upper()
    normalized_market = normalize_market(market)
    if normalized_market == "CN":
        if len(value) == 8 and value[:2] in {"SH", "SZ"} and value[2:].isdigit():
            return value.lower()
        for suffix in (".SH", ".SZ", ".BJ"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
                break
        return value.zfill(6) if value.isdigit() else value
    if normalized_market == "HK":
        if value.endswith(".HK"):
            value = value[:-3]
        return value.zfill(5) if value.isdigit() else value
    for suffix in (".O", ".N", ".US"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value


def instrument_key(market: str, symbol: str) -> str:
    normalized_market = normalize_market(market)
    return f"{normalized_market}:{normalize_symbol(symbol, normalized_market)}"


def get_market_profile(market: str) -> MarketProfile:
    return _PROFILES[normalize_market(market)]


@lru_cache(maxsize=3)
def _optional_exchange_calendar(market: str):
    """Load exchange-calendars when installed; keep core runtime dependency optional."""
    try:
        import exchange_calendars as xcals
    except ImportError:
        return None
    return xcals.get_calendar(get_market_profile(market).calendar_code)


def is_scheduled_session(market: str, session_date: date) -> tuple[bool, str]:
    calendar = _optional_exchange_calendar(normalize_market(market))
    if calendar is not None:
        return bool(calendar.is_session(session_date.isoformat())), "exchange_calendars"
    return session_date.weekday() < 5, "weekday_fallback_requires_fresh_bar_gate"


def market_now(market: str, now: datetime | None = None) -> datetime:
    profile = get_market_profile(market)
    zone = ZoneInfo(profile.timezone)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def expected_completed_session(market: str, now: datetime | None = None) -> dict[str, str | bool]:
    """Return the latest session expected to have a close-confirmed daily bar.

    When the optional exchange calendar is unavailable the scheduler may wake on
    holidays, but downstream jobs must still require a fresh provider bar for
    this expected date before persisting signals.
    """
    profile = get_market_profile(market)
    local_now = market_now(market, now)
    candidate = local_now.date()
    if local_now.time() < profile.postmarket_time:
        candidate -= timedelta(days=1)
    source = ""
    for _ in range(10):
        is_session, source = is_scheduled_session(market, candidate)
        if is_session:
            return {
                "market": profile.market,
                "date": candidate.isoformat(),
                "timezone": profile.timezone,
                "calendar_source": source,
                "close_confirmed_by_clock": True,
            }
        candidate -= timedelta(days=1)
    raise RuntimeError(f"unable to resolve recent session for {market}")


def market_profile_payload(market: str) -> dict[str, object]:
    profile = get_market_profile(market)
    return {
        "market": profile.market,
        "label": profile.label,
        "exchange": profile.exchange,
        "currency": profile.currency,
        "timezone": profile.timezone,
        "calendar_code": profile.calendar_code,
        "benchmark_symbol": profile.benchmark_symbol,
        "benchmark_name": profile.benchmark_name,
        "premarket_time": profile.premarket_time.isoformat(timespec="minutes"),
        "regular_open": profile.regular_open.isoformat(timespec="minutes"),
        "regular_close": profile.regular_close.isoformat(timespec="minutes"),
        "postmarket_time": profile.postmarket_time.isoformat(timespec="minutes"),
        "settlement_days": profile.settlement_days,
        "same_day_sell_allowed": profile.same_day_sell_allowed,
        "default_lot_size": profile.default_lot_size,
        "odd_lot_supported": profile.odd_lot_supported,
        "fractional_supported": profile.fractional_supported,
        "price_limit_model": profile.price_limit_model,
        "broker_constraints_required": profile.broker_constraints_required,
        "cost_model": {
            "percentage_round_trip": profile.costs.percentage_round_trip,
            "sell_fee_per_share": profile.costs.sell_fee_per_share,
            "sell_fee_cap": profile.costs.sell_fee_cap,
            "version": profile.costs.version,
        },
    }


def all_market_profiles_payload() -> dict[str, dict[str, object]]:
    return {market: market_profile_payload(market) for market in SUPPORTED_MARKETS}
