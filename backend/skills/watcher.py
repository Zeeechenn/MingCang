"""Watchlist event scanner for price, volume, and risk conditions."""
from __future__ import annotations

from dataclasses import dataclass, asdict

from backend.data.database import Price, Signal, Stock


@dataclass(frozen=True)
class WatchEvent:
    """A deterministic watchlist event."""

    symbol: str
    name: str
    as_of: str
    event_type: str
    severity: str
    message: str
    evidence: dict

    def to_dict(self) -> dict:
        """Serialize the event for reports and APIs."""
        return asdict(self)


def _latest_prices(db, symbol: str, as_of: str | None) -> list[Price]:
    query = db.query(Price).filter(Price.symbol == symbol)
    if as_of:
        query = query.filter(Price.date <= as_of)
    return query.order_by(Price.date.desc()).limit(6).all()


def scan_watch_events(
    db,
    *,
    as_of: str | None = None,
    price_move_pct: float = 5.0,
    volume_spike_mult: float = 2.0,
    near_stop_pct: float = 2.0,
    near_take_pct: float = 3.0,
) -> list[WatchEvent]:
    """
    Scan active watchlist stocks for deterministic alert conditions.

    The scanner only emits informational events. It does not modify signals or
    trigger trades; notification routing can consume the returned events later.
    """
    events: list[WatchEvent] = []
    stocks = db.query(Stock).filter(Stock.active == True).all()

    for stock in stocks:
        rows = _latest_prices(db, stock.symbol, as_of)
        if not rows:
            continue
        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        event_date = latest.date

        if previous and previous.close:
            change_pct = (latest.close - previous.close) / previous.close * 100
            if abs(change_pct) >= price_move_pct:
                direction = "上涨" if change_pct > 0 else "下跌"
                events.append(WatchEvent(
                    symbol=stock.symbol,
                    name=stock.name,
                    as_of=event_date,
                    event_type="price_move",
                    severity="high" if abs(change_pct) >= price_move_pct * 1.5 else "medium",
                    message=f"{stock.symbol} {direction} {change_pct:.2f}%",
                    evidence={"change_pct": round(change_pct, 2), "close": latest.close},
                ))

        history = rows[1:]
        avg_volume = sum((row.volume or 0) for row in history) / len(history) if history else 0
        if avg_volume and (latest.volume or 0) >= avg_volume * volume_spike_mult:
            events.append(WatchEvent(
                symbol=stock.symbol,
                name=stock.name,
                as_of=event_date,
                event_type="volume_spike",
                severity="medium",
                message=f"{stock.symbol} 放量 {latest.volume / avg_volume:.1f}x",
                evidence={"volume": latest.volume, "avg_volume": round(avg_volume, 2)},
            ))

        sig = (
            db.query(Signal)
            .filter(Signal.symbol == stock.symbol)
            .order_by(Signal.date.desc())
            .first()
        )
        if sig and latest.close:
            if sig.stop_loss:
                distance = (latest.close - sig.stop_loss) / latest.close * 100
                if 0 <= distance <= near_stop_pct:
                    events.append(WatchEvent(
                        symbol=stock.symbol,
                        name=stock.name,
                        as_of=event_date,
                        event_type="near_stop_loss",
                        severity="high",
                        message=f"{stock.symbol} 距止损 {distance:.2f}%",
                        evidence={"close": latest.close, "stop_loss": sig.stop_loss},
                    ))
            if sig.take_profit:
                distance = (sig.take_profit - latest.close) / latest.close * 100
                if 0 <= distance <= near_take_pct:
                    events.append(WatchEvent(
                        symbol=stock.symbol,
                        name=stock.name,
                        as_of=event_date,
                        event_type="near_take_profit",
                        severity="medium",
                        message=f"{stock.symbol} 距止盈 {distance:.2f}%",
                        evidence={"close": latest.close, "take_profit": sig.take_profit},
                    ))

    return events

