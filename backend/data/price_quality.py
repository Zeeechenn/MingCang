"""Local price quality gates used by read-only data envelopes."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from backend.data.database import Price

PriceQualityStatus = Literal["not_applicable", "unavailable", "passed", "warning", "blocked"]


@dataclass(frozen=True)
class PriceQualityPolicy:
    recent_window: int = 20
    stale_warning_days: int = 7
    extreme_price_range_ratio: float = 20.0
    cn_required_provenance: tuple[str, ...] = ("source", "fetched_at", "adjustment")


@dataclass(frozen=True)
class PriceQualityGate:
    status: PriceQualityStatus
    blockers: list[str]
    warnings: list[str]
    recent_sources: list[str]
    recent_adjustments: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "recent_sources": self.recent_sources,
            "recent_adjustments": self.recent_adjustments,
        }


DEFAULT_PRICE_QUALITY_POLICY = PriceQualityPolicy()


def not_applicable_price_quality_gate() -> PriceQualityGate:
    return PriceQualityGate(
        status="not_applicable",
        blockers=[],
        warnings=[],
        recent_sources=[],
        recent_adjustments=[],
    )


def evaluate_price_quality(
    *,
    market: str,
    row: Mapping[str, Any] | None,
    recent_rows: Sequence[Price],
    policy: PriceQualityPolicy = DEFAULT_PRICE_QUALITY_POLICY,
) -> PriceQualityGate:
    """Return local DB price quality warnings without fetching remote providers."""
    blockers: list[str] = []
    warnings: list[str] = []

    if row is None:
        return PriceQualityGate(
            status="unavailable",
            blockers=["no_local_price_row"],
            warnings=[],
            recent_sources=[],
            recent_adjustments=[],
        )

    for field in ("open", "high", "low", "close", "volume"):
        value = row.get(field)
        if value is None:
            blockers.append(f"missing_{field}")
            continue
        if field != "volume" and float(value) <= 0:
            blockers.append(f"non_positive_{field}")

    high = row.get("high")
    low = row.get("low")
    open_ = row.get("open")
    close = row.get("close")
    if high is not None and low is not None and float(high) < float(low):
        blockers.append("high_below_low")
    if high is not None and low is not None:
        for field_name, value in (("open", open_), ("close", close)):
            if value is not None and not (float(low) <= float(value) <= float(high)):
                blockers.append(f"{field_name}_outside_daily_range")

    if market.upper() == "CN":
        for field in policy.cn_required_provenance:
            if not row.get(field):
                blockers.append(f"missing_provenance_{field}")

    try:
        latest_date = date.fromisoformat(str(row.get("date")))
        days_old = (date.today() - latest_date).days
        if days_old > policy.stale_warning_days:
            warnings.append(f"stale_latest_bar_{days_old}d")
    except (TypeError, ValueError):
        blockers.append("invalid_price_date")

    sources = sorted({str(item.source) for item in recent_rows if item.source})
    adjustments = sorted({str(item.adjustment) for item in recent_rows if item.adjustment})
    if len(adjustments) > 1:
        blockers.append("mixed_recent_adjustments")
    if len(sources) > 1:
        warnings.append("mixed_recent_sources")

    closes = [float(item.close) for item in recent_rows if item.close and float(item.close) > 0]
    if closes:
        min_close = min(closes)
        max_close = max(closes)
        if min_close > 0 and max_close / min_close > policy.extreme_price_range_ratio:
            blockers.append("extreme_recent_price_range")

    status: PriceQualityStatus = "passed" if not blockers and not warnings else "warning"
    if blockers:
        status = "blocked"
    return PriceQualityGate(
        status=status,
        blockers=sorted(set(blockers)),
        warnings=sorted(set(warnings)),
        recent_sources=sources,
        recent_adjustments=adjustments,
    )
