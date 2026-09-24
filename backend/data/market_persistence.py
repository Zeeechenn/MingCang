"""Database read/write helpers for market data."""
import logging
from collections.abc import Callable
from datetime import date, timedelta
from statistics import median as _median

import pandas as pd

logger = logging.getLogger("backend.data.market")

BACKFILL_YEARS = 5          # 首次初始化回填年数
BACKFILL_THRESHOLD_DAYS = 1   # 最新数据距今超过此天数才触发回填（日常运营=1）
REFRESH_WINDOW_DAYS = 5  # refresh_today=True 时覆盖回写的最近窗口


class PriceBasisWriteBlocked(RuntimeError):
    """Raised only when a caller explicitly enables strict basis protection."""


def _price_write_provenance_conflicts(
    db,
    *,
    asset_key: str,
    source: str | None,
    adjustment: str | None,
) -> list[str]:
    """Return reasons why appending this provider would splice stored history."""
    from backend.data.database import Price

    rows = (
        db.query(Price.source, Price.adjustment)
        .filter(Price.asset_key == asset_key)
        .distinct()
        .all()
    )
    if not rows:
        return []
    stored_sources = {str(row.source) if row.source else "missing" for row in rows}
    stored_adjustments = {
        str(row.adjustment) if row.adjustment else "missing" for row in rows
    }
    conflicts: list[str] = []
    if source is None:
        conflicts.append("fetched_source_missing")
    elif stored_sources != {source}:
        conflicts.append(
            "stored_source_mismatch:" + ",".join(sorted(stored_sources))
        )
    if adjustment is None:
        conflicts.append("fetched_adjustment_missing")
    elif stored_adjustments != {adjustment}:
        conflicts.append(
            "stored_adjustment_mismatch:" + ",".join(sorted(stored_adjustments))
        )
    return conflicts


def _strict_warmup_stored_provenance_conflicts(db, *, asset_key: str) -> list[str]:
    """Reject known mixed history before spending a provider call on strict refresh."""
    from backend.data.database import Price

    rows = (
        db.query(Price.source, Price.adjustment)
        .filter(Price.asset_key == asset_key)
        .distinct()
        .all()
    )
    if not rows:
        return ["stored_price_provenance_missing"]

    sources = {
        str(row.source) if row.source and str(row.source).strip() else "missing"
        for row in rows
    }
    adjustments = {
        str(row.adjustment)
        if row.adjustment and str(row.adjustment).strip()
        else "missing"
        for row in rows
    }
    conflicts: list[str] = []
    if "missing" in sources:
        conflicts.append("stored_source_missing")
    if len(sources - {"missing"}) > 1:
        conflicts.append("stored_sources_mixed:" + ",".join(sorted(sources - {"missing"})))
    if "missing" in adjustments:
        conflicts.append("stored_adjustment_missing")
    if len(adjustments - {"missing"}) > 1:
        conflicts.append(
            "stored_adjustments_mixed:" + ",".join(sorted(adjustments - {"missing"}))
        )
    return conflicts


def _check_adjustment_basis_drift(db, *, symbol: str, asset_key: str,
                                  fetched: pd.DataFrame, source: str | None) -> bool | None:
    """Warn (and record) when stored history sits on a stale adjustment basis.

    Detect-and-report only: we deliberately do NOT rewrite history here.  These
    rows back a real-money ledger, so re-basing them is an explicit operator
    decision (see ``backend.tools.rebase_price_history``), not a side effect of
    a routine backfill.

    We record the *stored* rows' provider alongside the fetch provider.  Without
    it a drift event is ambiguous: "the provider re-based this series" and "a
    different provider answered today, on its own basis" are indistinguishable,
    and the 2026-09-02 audit found the 47 recorded events split across four
    providers.  A same-source event is a genuine re-basing that an operator must
    clear; a cross-source event says the stored history is spliced and needs a
    single-source rebuild instead.
    """
    from backend.data.database import Price
    from backend.data.price_quality import detect_adjustment_basis_drift

    try:
        fetched_closes = {
            str(day): float(row["close"])
            for day, row in fetched.iterrows()
            if row.get("close") is not None and not pd.isna(row["close"])
        }
        if not fetched_closes:
            return False
        stored_rows = (
            db.query(Price.date, Price.close, Price.source)
            .filter(
                Price.asset_key == asset_key,
                Price.date.in_(list(fetched_closes)),
            )
            .all()
        )
        stored_closes = {r.date: float(r.close) for r in stored_rows if r.close}
        stored_sources = sorted({
            str(r.source) for r in stored_rows if r.close and r.source is not None
        })
        drift = detect_adjustment_basis_drift(fetched_closes, stored_closes)
        if not drift.detected:
            return False

        logger.warning(
            "M69 复权基准漂移：%s（provider=%s）——%s。"
            "库内历史与新 bar 基准不一致，跨接缝的盈亏/止损位/ATR 均不可直接比较；"
            "未自动改写历史，如确认需重基请跑 backend.tools.rebase_price_history。",
            symbol, source or "unknown", drift.describe(),
        )
        _record_basis_drift_event(
            db, symbol=symbol, source=source, drift=drift, stored_sources=stored_sources,
        )
        return True
    except Exception as exc:  # pragma: no cover - detection must never break ingestion
        logger.warning("M69 复权基准漂移检查失败 %s: %s", symbol, exc)
        return None


def _record_basis_drift_event(
    db, *, symbol: str, source: str | None, drift,
    stored_sources: list[str] | None = None,
) -> None:
    import json

    try:
        from backend.data.models.degradation import DegradationEvent
        from backend.data.price_quality import classify_drift_source

        payload = drift.to_payload()
        payload["symbol"] = symbol
        payload["stored_sources"] = list(stored_sources or [])
        payload["cross_source"] = classify_drift_source(source, stored_sources)
        db.add(DegradationEvent(
            component="market_persistence",
            category="adjustment_basis_drift",
            provider=source or "unknown",
            error=f"{symbol}: {drift.describe()}"[:500],
            context_json=json.dumps(payload, ensure_ascii=False),
        ))
        db.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("M69 漂移事件落库失败 %s: %s", symbol, exc)
        db.rollback()


def load_price_df(symbol: str, db, days: int = 200, market: str | None = None) -> pd.DataFrame:
    """
    从 Price 表读取历史行情，返回 OHLCV DataFrame（index=date str，升序）。
    days=200 确保 MA60 / ATR14 有足够数据。
    """
    from backend.data.database import Price

    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    query = db.query(Price).filter(Price.symbol == symbol, Price.date >= cutoff)
    if market is not None:
        query = query.filter(Price.market == market)
    rows = (
        query
        .order_by(Price.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(
        [{"date": r.date, "open": r.open, "high": r.high,
          "low": r.low, "close": r.close, "volume": r.volume}
         for r in rows]
    ).set_index("date")


def sync_index_to_db(
    db,
    index_symbol: str = "sh000300",
    days: int = 365,
    *,
    fetch_cn_index_fn: Callable[..., pd.DataFrame],
    market: str = "CN",
) -> int:
    """
    拉取指数日线并写入 index_prices 表，跳过已存在的日期。
    返回新写入条数。
    """
    from backend.data.database import IndexPrice
    from backend.data.market_profiles import get_market_profile, instrument_key, normalize_market

    market = normalize_market(market)
    profile = get_market_profile(market)
    index_asset_key = instrument_key(market, index_symbol)
    df = fetch_cn_index_fn(index_symbol, days=days)
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")
    existing = {
        r[0] for r in db.query(IndexPrice.date)
        .filter(IndexPrice.symbol == index_symbol, IndexPrice.market == market).all()
    }
    records = [
        IndexPrice(
            symbol=index_symbol,
            asset_key=index_asset_key,
            market=market,
            currency=profile.currency,
            date=d,
            close=float(row["close"]),
            change_pct=float(row["change_pct"]) if pd.notna(row.get("change_pct")) else None,
            source=source,
            fetched_at=fetched_at,
            adjustment=adjustment,
        )
        for d, row in df.iterrows()
        if d not in existing
    ]
    if records:
        db.bulk_save_objects(records)
        db.commit()
    return len(records)


def backfill_if_needed(
    symbol: str,
    market: str,
    db,
    years: int | None = None,
    refresh_today: bool = False,
    expected_latest: str | None = None,
    *,
    fetch_daily_fn: Callable[..., pd.DataFrame],
    backfill_years: int = BACKFILL_YEARS,
    backfill_threshold_days: int = BACKFILL_THRESHOLD_DAYS,
    refresh_window_days: int = REFRESH_WINDOW_DAYS,
    strict_basis_write_guard: bool = False,
    factor_warmup_rows: int | None = None,
) -> int:
    """
    检查该股历史数据是否充足。若最新记录距今超过阈值（或无记录），
    自动从 AkShare/yfinance 回填最多 BACKFILL_YEARS 年数据。

    refresh_today=True 时绕过阈值短路，强制重抓最近 REFRESH_WINDOW_DAYS 天并
    覆盖写入，用于盘前/盘后任务校正当日已有价格（避免被 provider 修正前的脏数据
    污染下游技术分/ATR/止损止盈）。

    factor_warmup_rows is an explicit, strict research/maintenance candidate.
    It requests enough same-provider history before the write window and rejects
    incomplete context. Routine callers retain the existing fetch/write behavior.

    返回新写入或更新的记录条数。
    """
    from backend.analysis.factors import add_all_factors
    from backend.data.database import Price
    from backend.data.market_profiles import (
        get_market_profile,
        instrument_key,
        normalize_market,
        normalize_symbol,
    )

    if factor_warmup_rows is not None:
        if type(factor_warmup_rows) is not int or not 14 <= factor_warmup_rows <= 2000:
            raise ValueError("factor_warmup_rows must be an integer in [14, 2000]")
        if not strict_basis_write_guard:
            raise ValueError("factor warmup requires strict_basis_write_guard")
        if expected_latest is None:
            raise ValueError("factor warmup requires expected_latest")
        if date.fromisoformat(expected_latest).isoformat() != expected_latest:
            raise ValueError("factor warmup requires a canonical expected_latest date")

    reference_date = date.today()
    if expected_latest is not None:
        try:
            parsed_expected_latest = date.fromisoformat(expected_latest)
        except (TypeError, ValueError) as exc:
            raise ValueError("expected_latest must be an ISO date") from exc
        if parsed_expected_latest.isoformat() != expected_latest:
            raise ValueError("expected_latest must be a canonical ISO date")
        reference_date = parsed_expected_latest

    market = normalize_market(market)
    symbol = normalize_symbol(symbol, market)
    asset_key = instrument_key(market, symbol)
    profile = get_market_profile(market)

    latest = db.query(Price.date).filter(Price.asset_key == asset_key).order_by(Price.date.desc()).first()
    latest_date_str = latest[0] if latest else None
    if factor_warmup_rows is not None and latest_date_str is None:
        raise PriceBasisWriteBlocked("factor warmup requires existing history; seed full history separately")
    strict_warmup_refresh = strict_basis_write_guard and factor_warmup_rows is not None
    if strict_warmup_refresh:
        stored_conflicts = _strict_warmup_stored_provenance_conflicts(db, asset_key=asset_key)
        if stored_conflicts:
            raise PriceBasisWriteBlocked(
                f"strict warmup refresh blocked before provider: {', '.join(stored_conflicts)}; "
                "repair full stored history before enabling this symbol"
            )

    if latest_date_str:
        latest_date = date.fromisoformat(latest_date_str)
        if expected_latest is not None and latest_date > reference_date:
            raise PriceBasisWriteBlocked("expected_latest precedes newest stored price")
        days_old = (reference_date - latest_date).days
        if days_old < backfill_threshold_days and not refresh_today:
            return 0
        fetch_days = max(days_old + 10, refresh_window_days + 2 if refresh_today else 0)
    else:
        fetch_days = (years or backfill_years) * 365 + 10

    if factor_warmup_rows is not None:
        # Providers differ between calendar-day and row-count limits. Request a
        # conservative span, then verify the actual preceding-row coverage.
        fetch_days = max(fetch_days, 2 * (factor_warmup_rows + refresh_window_days + 2) + 10)

    if expected_latest is not None:
        df = fetch_daily_fn(symbol, market, days=fetch_days, expected_latest=expected_latest)
    else:
        df = fetch_daily_fn(symbol, market, days=fetch_days)
    source = df.attrs.get("source")
    fetched_at = df.attrs.get("fetched_at")
    adjustment = df.attrs.get("adjustment")

    if df.empty:
        if strict_warmup_refresh:
            raise PriceBasisWriteBlocked(
                "strict warmup refresh blocked: provider returned no rows; no prices were written"
            )
        return 0

    if factor_warmup_rows is not None:
        if not df.index.is_unique or not df.index.is_monotonic_increasing:
            raise PriceBasisWriteBlocked("factor warmup requires unique ascending dates")
        try:
            valid_dates = all(isinstance(day, str) and date.fromisoformat(day).isoformat() == day for day in df.index)
        except ValueError:
            valid_dates = False
        if not valid_dates or df.index[-1] != expected_latest:
            raise PriceBasisWriteBlocked("factor warmup requires canonical dates through expected_latest")
        if expected_latest is not None and any(str(day) > expected_latest for day in df.index):
            raise PriceBasisWriteBlocked("factor warmup contains rows after expected_latest")
        values = df[["open", "high", "low", "close"]]
        import numpy as np
        if not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any().any():
            raise PriceBasisWriteBlocked("factor warmup requires finite positive OHLC")
        if (df.high < df[["open", "low", "close"]].max(axis=1)).any() or (df.low > df[["open", "high", "close"]].min(axis=1)).any():
            raise PriceBasisWriteBlocked("factor warmup requires valid OHLC ordering")

    df_factors = add_all_factors(df)

    # M69: before we filter down to "rows we don't have yet", compare the
    # overlap between what the provider just returned and what we already hold.
    # Same provider + same date must reproduce the same close; when it does not,
    # the provider has re-based the series (typically an ex-dividend) and our
    # stored history is now on a different basis than the bars we are about to
    # append.  Left undetected this silently breaks P&L, stop/target levels and
    # ATR across the seam — 600900 on 2026-07-15 carried a 0.79 offset that the
    # 3x ratio guard below could never see.
    drift_detected = _check_adjustment_basis_drift(
        db,
        symbol=symbol,
        asset_key=asset_key,
        fetched=df,
        source=source,
    )
    provenance_conflicts = _price_write_provenance_conflicts(
        db,
        asset_key=asset_key,
        source=str(source) if source else None,
        adjustment=str(adjustment) if adjustment else None,
    )
    if strict_basis_write_guard and (drift_detected is not False or provenance_conflicts):
        details = list(provenance_conflicts)
        if drift_detected is True:
            details.append("overlap_close_drift")
        elif drift_detected is None:
            details.append("drift_check_failed")
        raise PriceBasisWriteBlocked(
            f"strict price-basis guard blocked {asset_key}: {', '.join(details)}"
        )

    if refresh_today and latest_date_str:
        window_start = (reference_date - timedelta(days=refresh_window_days)).isoformat()
        df_factors = df_factors[df_factors.index >= window_start]
    elif latest_date_str:
        df_factors = df_factors[df_factors.index > latest_date_str]

    if df_factors.empty:
        if strict_warmup_refresh:
            raise PriceBasisWriteBlocked(
                "strict warmup refresh blocked: no rows remain in the refresh window; no prices were written"
            )
        return 0

    if factor_warmup_rows is not None:
        first_position = df.index.get_indexer([df_factors.index[0]])[0]
        if first_position < factor_warmup_rows:
            raise PriceBasisWriteBlocked(
                f"factor warmup insufficient: {first_position} preceding rows; requires {factor_warmup_rows}"
            )

    candidate_dates = list(df_factors.index) if refresh_today else []

    # M42/M58: build a rolling window of the last 10 *committed* closes for
    # each candidate row so the write-time adjustment-jump guard (up-splice
    # M42 + down-splice M58) has a baseline.  We initialise from existing DB
    # rows (already committed) and extend with rows we have already accepted
    # in this batch.  This means:
    #   - First N rows of a brand-new symbol have < 10 preceding closes →
    #     guard returns False (passes through) as documented in
    #     check_adjustment_basis_jump.
    #   - For refresh_today the seed is strictly before the first candidate,
    #     so no stale row inside the replacement window can leak into the
    #     write-time baseline.
    from backend.data.price_quality import (  # local import avoids circular at module level
        HFQ_JUMP_RATIO_THRESHOLD,
        check_adjustment_basis_jump,
    )

    preceding_window = 10
    # Seed the window from existing DB closes (up to preceding_window rows),
    # ordered ascending so we keep the most-recent ones at the end.
    seed_query = db.query(Price.close).filter(Price.asset_key == asset_key)
    if candidate_dates:
        # Only rows strictly before the first candidate are valid seed context.
        # Later stored rows may lie inside the refreshed window and must not
        # influence acceptance of earlier candidate bars.
        seed_query = seed_query.filter(Price.date < min(candidate_dates))
    seed_rows = seed_query.order_by(Price.date.desc()).limit(preceding_window).all()
    # rows come back newest-first; reverse so list is oldest→newest
    preceding_closes: list[float] = [float(r.close) for r in reversed(seed_rows) if r.close]

    records = []
    rejected = 0
    for date_str, row in df_factors.iterrows():
        close_val = float(row["close"])
        # M42/M58 write-time guard: reject probable adjustment-basis-splice
        # rows, both the up-direction hfq-scale jump (M42) and the symmetric
        # down-direction splice (M58).
        if check_adjustment_basis_jump(close_val, preceding_closes):
            usable = [c for c in preceding_closes if c > 0]
            logger.warning(
                "M42/M58 adjustment-jump guard: rejected %s %s close=%.4f "
                "(preceding 10-day median=%.4f, threshold=%.1f×) — skipping row",
                symbol, date_str, close_val,
                _median(usable) if usable else 0,
                HFQ_JUMP_RATIO_THRESHOLD,
            )
            rejected += 1
            continue
        atr = row.get("atr14")
        records.append(Price(
            symbol=symbol,
            asset_key=asset_key,
            market=market,
            currency=profile.currency,
            date=date_str,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=close_val,
            volume=float(row["volume"]),
            atr14=float(atr) if atr is not None and not pd.isna(atr) else None,
            source=source,
            fetched_at=fetched_at,
            adjustment=adjustment,
        ))
        # Slide the window forward with the accepted close.
        preceding_closes.append(close_val)
        if len(preceding_closes) > preceding_window:
            preceding_closes.pop(0)

    if rejected:
        logger.warning(
            "M42 hfq-jump guard: rejected %d/%d rows for %s",
            rejected,
            rejected + len(records),
            symbol,
        )

    if strict_warmup_refresh and rejected:
        raise PriceBasisWriteBlocked(
            f"strict warmup refresh blocked: {rejected} candidate rows failed the jump guard; "
            "no prices were written"
        )

    # A refresh may only replace rows after at least one candidate has passed
    # validation. Keep delete+insert in one transaction so rejected/empty input
    # cannot erase a usable stored window.
    if not records:
        if strict_warmup_refresh:
            raise PriceBasisWriteBlocked(
                "strict warmup refresh blocked: no candidate rows passed validation; no prices were written"
            )
        return 0
    dates_to_replace = [record.date for record in records] if refresh_today else []
    try:
        if dates_to_replace:
            db.query(Price).filter(
                Price.asset_key == asset_key,
                Price.date.in_(dates_to_replace),
            ).delete(synchronize_session=False)
        db.bulk_save_objects(records)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(records)
