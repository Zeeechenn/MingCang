"""PIT-gated HK/US financial normalization for M67 gray research."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from backend.data.market_profiles import get_market_profile, normalize_market, normalize_symbol


def _frame_value(frame: pd.DataFrame, row_names: tuple[str, ...], period: pd.Timestamp) -> float | None:
    if frame is None or frame.empty or period not in frame.columns:
        return None
    for name in row_names:
        if name in frame.index and pd.notna(frame.at[name, period]):
            return float(frame.at[name, period])
    return None


def _earnings_dates(ticker) -> list[datetime]:
    try:
        frame = ticker.get_earnings_dates(limit=40)
    except Exception:
        return []
    if frame is None or frame.empty:
        return []
    rows: list[datetime] = []
    for raw in frame.index:
        stamp = pd.Timestamp(raw)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        rows.append(stamp.to_pydatetime())
    return sorted(rows)


def _disclosure_for_period(period: pd.Timestamp, earnings: list[datetime], as_of: datetime) -> datetime | None:
    start = period.to_pydatetime()
    cutoff = min(as_of, start + timedelta(days=190))
    candidates = [value for value in earnings if start < value <= cutoff]
    return min(candidates) if candidates else None


def fetch_yfinance_financial_rows(
    symbol: str,
    market: str,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch only periods with an observed earnings disclosure date."""
    import yfinance as yf

    from backend.data.market_utils import hk_yfinance_ticker

    normalized_market = normalize_market(market)
    if normalized_market not in {"HK", "US"}:
        raise ValueError("global financial adapter supports HK/US only")
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    ticker_symbol = hk_yfinance_ticker(normalized_symbol) if normalized_market == "HK" else normalized_symbol
    ticker = yf.Ticker(ticker_symbol)
    financials = ticker.quarterly_financials
    balance = ticker.quarterly_balance_sheet
    cashflow = ticker.quarterly_cashflow
    periods = sorted(
        set(financials.columns if financials is not None else [])
        | set(balance.columns if balance is not None else [])
        | set(cashflow.columns if cashflow is not None else []),
        reverse=True,
    )
    current = (as_of or datetime.now(UTC)).replace(tzinfo=None)
    earnings = _earnings_dates(ticker)
    rows: list[dict[str, Any]] = []
    for raw_period in periods:
        period = pd.Timestamp(raw_period).tz_localize(None)
        disclosure = _disclosure_for_period(period, earnings, current)
        if disclosure is None:
            continue
        revenue = _frame_value(financials, ("Total Revenue", "Operating Revenue"), period)
        net_profit = _frame_value(financials, ("Net Income", "Net Income Common Stockholders"), period)
        gross_profit = _frame_value(financials, ("Gross Profit",), period)
        total_assets = _frame_value(balance, ("Total Assets",), period)
        total_equity = _frame_value(balance, ("Stockholders Equity", "Total Equity Gross Minority Interest"), period)
        current_assets = _frame_value(balance, ("Current Assets", "Total Current Assets"), period)
        current_liabilities = _frame_value(balance, ("Current Liabilities", "Total Current Liabilities"), period)
        long_term_debt = _frame_value(balance, ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"), period)
        operating_cf = _frame_value(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"), period)
        shares = _frame_value(balance, ("Ordinary Shares Number", "Share Issued"), period)
        rows.append({
            "report_date": period.strftime("%Y-%m-%d"),
            "disclosure_date": disclosure.strftime("%Y-%m-%d"),
            "period_type": "Q1" if period.month == 3 else "Q2" if period.month == 6 else "Q3" if period.month == 9 else "Annual",
            "revenue": revenue,
            "net_profit": net_profit,
            "total_assets": total_assets,
            "total_equity": total_equity,
            "long_term_debt": long_term_debt,
            "current_ratio": current_assets / current_liabilities if current_assets and current_liabilities else None,
            "operating_cf": operating_cf,
            "shares_outstanding": shares,
            "gross_margin": gross_profit / revenue * 100 if gross_profit is not None and revenue else None,
            "roe": net_profit / total_equity * 100 if net_profit is not None and total_equity else None,
            "asset_turnover": revenue / total_assets if revenue is not None and total_assets else None,
            "source": "yfinance_global",
            "provider_symbol": ticker_symbol,
        })
    return rows


def _attach_yoy(rows: list[dict[str, Any]]) -> None:
    by_period = {row["report_date"]: row for row in rows}
    for row in rows:
        previous_date = f"{int(row['report_date'][:4]) - 1}{row['report_date'][4:]}"
        previous = by_period.get(previous_date)
        if not previous:
            continue
        if row.get("revenue") is not None and previous.get("revenue"):
            row["revenue_yoy"] = round((row["revenue"] / previous["revenue"] - 1) * 100, 2)
        if row.get("net_profit") is not None and previous.get("net_profit"):
            row["net_profit_yoy"] = round((row["net_profit"] / previous["net_profit"] - 1) * 100, 2)


def sync_global_financial_metrics(symbol: str, market: str, db, *, as_of: datetime | None = None) -> int:
    """Persist PIT-safe HK/US rows; future or unverified periods are skipped."""
    from backend.data.database import FinancialMetric
    from backend.data.market_profiles import instrument_key

    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    key = instrument_key(normalized_market, normalized_symbol)
    profile = get_market_profile(normalized_market)
    rows = fetch_yfinance_financial_rows(normalized_symbol, normalized_market, as_of=as_of)
    _attach_yoy(rows)
    inserted = 0
    for row in rows:
        if db.query(FinancialMetric.id).filter(
            FinancialMetric.asset_key == key,
            FinancialMetric.report_date == row["report_date"],
        ).first():
            continue
        db.add(FinancialMetric(
            symbol=normalized_symbol,
            market=normalized_market,
            currency=profile.currency,
            source=str(row["source"]),
            report_date=str(row["report_date"]),
            disclosure_date=str(row["disclosure_date"]),
            period_type=str(row["period_type"]),
            revenue=row.get("revenue"),
            revenue_yoy=row.get("revenue_yoy"),
            net_profit=row.get("net_profit"),
            net_profit_yoy=row.get("net_profit_yoy"),
            total_assets=row.get("total_assets"),
            total_equity=row.get("total_equity"),
            long_term_debt=row.get("long_term_debt"),
            current_ratio=row.get("current_ratio"),
            operating_cf=row.get("operating_cf"),
            shares_outstanding=row.get("shares_outstanding"),
            gross_margin=row.get("gross_margin"),
            roe=row.get("roe"),
            asset_turnover=row.get("asset_turnover"),
            raw_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
        ))
        inserted += 1
    db.commit()
    return inserted
