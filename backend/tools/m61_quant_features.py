"""M61 enriched LightGBM feature matrix builder.

This module intentionally lives as a standalone tool file for M61 §7.5. It
does not change the legacy qlib feature builder or any production scoring path.
The old LightGBM "关门" verdict remains valid for the old, price-only feature
space; this file defines a new preregistered enriched-feature hypothesis.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd

from backend.analysis.alpha_factors import add_cross_sectional_alpha_factors
from backend.data.database import CorporateEvent, FinancialMetric, FundFlow, LhbRecord, Price, ResearchReport, Stock
from backend.data.qlib_data import FEATURE_COLS, _build_features
from backend.tools.m52_flow_floor import compute_s_flow_data

NON_PRICE_QFEATURE_COLS = {
    "roe",
    "revenue_yoy",
    "net_profit_yoy",
    "gross_margin",
    "asset_turnover",
    "log_market_cap",
    "margin_balance",
}
PRICE_FEATURE_COLS = [col for col in FEATURE_COLS if col not in NON_PRICE_QFEATURE_COLS]
M61_FEATURE_COLS = [
    *PRICE_FEATURE_COLS,
    "lhb_appeared_5d",
    "lhb_net_buy_5d_sum",
    "days_to_next_unlock",
    "had_regulatory_event_30d",
    "report_count_90d",
    "eps_forecast_revision",
    "roe",
    "revenue_yoy",
    "net_profit_yoy",
    "s_flow",
    "main_net_5d_sum",
]


def _date_str(value: object) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _as_timestamp(value: object) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _load_price_block(symbols: list[str], start: str, end: str, db) -> pd.DataFrame:
    """Build qlib-derived price features with formulas imported from qlib_data.

    PIT rationale: every price feature is rolling or lagged from rows dated
    ``<= date``. We load pre-start history for rolling windows, compute features
    per symbol through ``qlib_data._build_features``, then filter to the user
    window. Cross-sectional sector-relative strength is computed same-date from
    the requested universe only; it uses no future rows.
    """
    rows = (
        db.query(Price)
        .filter(Price.symbol.in_(symbols), Price.date <= end)
        .order_by(Price.symbol, Price.date)
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["symbol", "date", *PRICE_FEATURE_COLS])

    industries = {
        row.symbol: row.industry or "UNKNOWN"
        for row in db.query(Stock.symbol, Stock.industry).filter(Stock.symbol.in_(symbols)).all()
    }
    parts: list[pd.DataFrame] = []
    for symbol in symbols:
        local_rows = [row for row in rows if row.symbol == symbol]
        if not local_rows:
            continue
        local = pd.DataFrame(
            [
                {
                    "date": row.date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume or 0.0,
                }
                for row in local_rows
            ]
        )
        feats = _build_features(local)
        feats["symbol"] = symbol
        feats["industry"] = industries.get(symbol, "UNKNOWN")
        parts.append(feats[["symbol", "industry", "date", *PRICE_FEATURE_COLS]])
    if not parts:
        return pd.DataFrame(columns=["symbol", "date", *PRICE_FEATURE_COLS])

    panel = pd.concat(parts, ignore_index=True)
    panel = add_cross_sectional_alpha_factors(panel)
    panel["date"] = panel["date"].map(_date_str)
    return panel[(panel["date"] >= start) & (panel["date"] <= end)][["symbol", "date", *PRICE_FEATURE_COLS]]


def _known_event_rows(rows: Iterable[CorporateEvent], as_of: pd.Timestamp) -> list[CorporateEvent]:
    """Return corporate events knowable by ``as_of``.

    PIT rationale: ``CorporateEvent`` has no separate announcement date, so this
    tool uses ``fetched_at`` as the available knowledge timestamp. Rows fetched
    after an evaluation date are invisible to that date, including future unlock
    events backfilled later.
    """
    out: list[CorporateEvent] = []
    for row in rows:
        fetched_at = pd.Timestamp(row.fetched_at).normalize() if row.fetched_at else None
        if fetched_at is None or fetched_at <= as_of:
            out.append(row)
    return out


def _event_type_or_title(row: CorporateEvent) -> str:
    return f"{row.event_type or ''} {row.title or ''}"


def _is_unlock(row: CorporateEvent) -> bool:
    return "解禁" in _event_type_or_title(row)


def _is_regulatory(row: CorporateEvent) -> bool:
    text = _event_type_or_title(row)
    return any(token in text for token in ("监管", "问询", "处罚", "立案", "警示", "违规"))


def _lhb_features(rows: list[LhbRecord], as_of: pd.Timestamp) -> dict[str, object]:
    """5-calendar-day LHB activity known at ``as_of``.

    PIT rationale: LHB rows use ``trade_date`` and are only included when
    ``trade_date <= date``. Future appearances cannot enter the rolling sum.
    """
    start = as_of - pd.Timedelta(days=4)
    visible = [row for row in rows if start <= _as_timestamp(row.trade_date) <= as_of]
    values = [row.net_buy_amount for row in visible if row.net_buy_amount is not None]
    return {
        "lhb_appeared_5d": bool(visible),
        "lhb_net_buy_5d_sum": float(sum(values)) if values else np.nan,
    }


def _event_features(rows: list[CorporateEvent], as_of: pd.Timestamp) -> dict[str, object]:
    """Unlock and regulatory-event features with event/fetch-date PIT guards.

    ``days_to_next_unlock`` uses known future unlock events, capped at 90; if no
    known future unlock exists, it is set to 999 as requested. Regulatory events
    are backward-looking over 30 calendar days and require both event_date and
    fetched_at to be visible by ``date``.
    """
    visible = _known_event_rows(rows, as_of)
    future_unlock_days = [
        (_as_timestamp(row.event_date) - as_of).days
        for row in visible
        if _is_unlock(row) and _as_timestamp(row.event_date) >= as_of
    ]
    if future_unlock_days:
        days_to_next_unlock = min(min(future_unlock_days), 90)
    else:
        days_to_next_unlock = 999

    cutoff = as_of - pd.Timedelta(days=30)
    had_regulatory = any(
        _is_regulatory(row) and cutoff <= _as_timestamp(row.event_date) <= as_of for row in visible
    )
    return {
        "days_to_next_unlock": days_to_next_unlock,
        "had_regulatory_event_30d": bool(had_regulatory),
    }


def _report_features(rows: list[ResearchReport], as_of: pd.Timestamp) -> dict[str, object]:
    """Research-report count and EPS revision using publication dates only.

    PIT rationale: a report is visible only when ``publish_date <= date``. EPS
    revision compares mean ``eps_forecast_y1`` in the latest 90 calendar days
    with the preceding 90 calendar days; it is NaN when either bucket lacks a
    numeric EPS mean or the prior mean is zero.
    """
    recent_start = as_of - pd.Timedelta(days=89)
    prior_start = as_of - pd.Timedelta(days=179)
    recent_values: list[float] = []
    prior_values: list[float] = []
    recent_count = 0
    for row in rows:
        published = _as_timestamp(row.publish_date)
        if recent_start <= published <= as_of:
            recent_count += 1
            if row.eps_forecast_y1 is not None:
                recent_values.append(float(row.eps_forecast_y1))
        elif prior_start <= published < recent_start and row.eps_forecast_y1 is not None:
            prior_values.append(float(row.eps_forecast_y1))

    if recent_values and prior_values:
        prior_mean = float(np.mean(prior_values))
        revision = float(np.mean(recent_values)) / prior_mean - 1 if prior_mean != 0 else np.nan
    else:
        revision = np.nan
    return {"report_count_90d": int(recent_count), "eps_forecast_revision": revision}


def _financial_known_date(row: FinancialMetric) -> pd.Timestamp:
    """Return the PIT known date for a financial metric row.

    The real ``FinancialMetric`` model has ``disclosure_date``. This tool uses
    it when present; when missing, it applies the requested conservative
    ``report_date + 45d`` lag instead of qlib_data's older report-date fallback.
    """
    if row.disclosure_date:
        return _as_timestamp(row.disclosure_date)
    return _as_timestamp(row.report_date) + pd.Timedelta(days=45)


def _financial_features(rows: list[FinancialMetric], as_of: pd.Timestamp) -> dict[str, object]:
    """Latest-known fundamentals as of ``date`` with no zero filling."""
    visible = [row for row in rows if _financial_known_date(row) <= as_of]
    if not visible:
        return {"roe": np.nan, "revenue_yoy": np.nan, "net_profit_yoy": np.nan}
    latest = max(visible, key=lambda row: _financial_known_date(row))
    return {
        "roe": latest.roe if latest.roe is not None else np.nan,
        "revenue_yoy": latest.revenue_yoy if latest.revenue_yoy is not None else np.nan,
        "net_profit_yoy": latest.net_profit_yoy if latest.net_profit_yoy is not None else np.nan,
    }


def _fund_flow_features(rows: list[FundFlow], as_of: pd.Timestamp) -> dict[str, object]:
    """PIT fund-flow features preserving missing values.

    PIT rationale: both ``s_flow`` and ``main_net_5d_sum`` use only fund-flow
    rows with ``trade_date <= date``. ``s_flow`` reuses the M52 formula via
    ``compute_s_flow_data``. Missing coverage remains NaN; this function never
    fills missing fund-flow values with 0, to avoid the D3 fake-feature disease.
    """
    visible = sorted(
        [row for row in rows if _as_timestamp(row.trade_date) <= as_of],
        key=lambda row: _as_timestamp(row.trade_date),
    )
    if not visible:
        return {"s_flow": np.nan, "main_net_5d_sum": np.nan}
    raw = [
        {
            "trade_date": row.trade_date,
            "main_net": row.main_net,
            "super_large_net": row.super_large_net,
            "large_net": row.large_net,
            "medium_net": row.medium_net,
            "small_net": row.small_net,
        }
        for row in visible[-65:]
    ]
    s_flow = compute_s_flow_data(raw)
    recent_main = [row.main_net for row in visible[-5:] if row.main_net is not None]
    return {
        "s_flow": float(s_flow) if s_flow is not None else np.nan,
        "main_net_5d_sum": float(sum(recent_main)) if recent_main else np.nan,
    }


def build_feature_matrix_v2(symbols: list[str], start: str, end: str, db) -> pd.DataFrame:
    """Build the M61 v2 enriched feature matrix indexed by ``(symbol, date)``.

    Feature PIT summary:
    - price: imported qlib rolling formulas over rows ``<= date``;
    - LHB: 5-day backward window by ``trade_date``;
    - events: future unlocks only if the event row was already fetched by date,
      and regulatory events only if event/fetch timestamps are visible;
    - reports: ``publish_date <= date`` only;
    - financials: latest row whose ``disclosure_date`` is visible, else
      ``report_date + 45d`` as a conservative availability lag;
    - fund_flow: M52 formula and rolling 5-row main-net sum over rows
      ``<= date``; missing flow stays NaN, never zero-filled.
    """
    symbols = [str(symbol) for symbol in symbols]
    if not symbols:
        return pd.DataFrame(columns=M61_FEATURE_COLS).set_index(pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"]))

    price_block = _load_price_block(symbols, start, end, db)
    if price_block.empty:
        index = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
        return pd.DataFrame(columns=M61_FEATURE_COLS, index=index)

    lhb_rows = {
        symbol: list(
            db.query(LhbRecord)
            .filter(LhbRecord.symbol == symbol, LhbRecord.trade_date <= datetime.fromisoformat(end) + timedelta(days=1))
            .order_by(LhbRecord.trade_date)
            .all()
        )
        for symbol in symbols
    }
    event_rows = {
        symbol: list(db.query(CorporateEvent).filter(CorporateEvent.symbol == symbol).order_by(CorporateEvent.event_date).all())
        for symbol in symbols
    }
    report_rows = {
        symbol: list(
            db.query(ResearchReport)
            .filter(ResearchReport.symbol == symbol, ResearchReport.publish_date <= datetime.fromisoformat(end) + timedelta(days=1))
            .order_by(ResearchReport.publish_date)
            .all()
        )
        for symbol in symbols
    }
    financial_rows = {
        symbol: list(
            db.query(FinancialMetric)
            .filter(FinancialMetric.symbol == symbol)
            .order_by(FinancialMetric.report_date)
            .all()
        )
        for symbol in symbols
    }
    flow_rows = {
        symbol: list(
            db.query(FundFlow)
            .filter(FundFlow.symbol == symbol, FundFlow.trade_date <= datetime.fromisoformat(end) + timedelta(days=1))
            .order_by(FundFlow.trade_date)
            .all()
        )
        for symbol in symbols
    }

    records: list[dict[str, object]] = []
    for row in price_block.sort_values(["symbol", "date"]).to_dict("records"):
        symbol = str(row["symbol"])
        as_of = _as_timestamp(row["date"])
        record = {col: row.get(col, np.nan) for col in PRICE_FEATURE_COLS}
        record.update(_lhb_features(lhb_rows.get(symbol, []), as_of))
        record.update(_event_features(event_rows.get(symbol, []), as_of))
        record.update(_report_features(report_rows.get(symbol, []), as_of))
        record.update(_financial_features(financial_rows.get(symbol, []), as_of))
        record.update(_fund_flow_features(flow_rows.get(symbol, []), as_of))
        record["symbol"] = symbol
        record["date"] = _date_str(as_of)
        records.append(record)

    out = pd.DataFrame(records)
    if out.empty:
        index = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
        return pd.DataFrame(columns=M61_FEATURE_COLS, index=index)
    out = out.set_index(["symbol", "date"]).sort_index()
    return out[M61_FEATURE_COLS]
