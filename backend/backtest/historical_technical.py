#!/usr/bin/env python3
"""Frozen, offline technical-only market baseline over saved daily JSON (v4)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DEFAULT_FIXED25 = REPO / "scripts" / "research_checks" / "universe" / "baseline-universe.json"
MIN_BARS = 61
BREAK_ABS_TOL = 0.011


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_code(ts_code: str) -> str:
    return str(ts_code).split(".", 1)[0]


def compact_day(value: Any) -> str:
    return str(value).replace("-", "")[:8]


def _technical_runtime_config() -> dict[str, Any]:
    import numpy as np

    from backend.analysis.technical import market_technical_rule
    from backend.config import settings

    return {
        "market": "CN",
        "market_rule": market_technical_rule("CN"),
        "adx_filter_enabled": bool(settings.adx_filter_enabled),
        "adx_threshold": float(settings.adx_threshold),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def _freeze_top_decile(rows: list[dict[str, Any]]) -> list[str]:
    """Freeze picks using only date-known features; labels are not an input."""
    ordered = sorted(rows, key=lambda row: (-float(row["technical_score"]), str(row["symbol"])))
    count = math.ceil(len(ordered) * 0.10) if ordered else 0
    return [str(row["symbol"]) for row in ordered[:count]]


def _load_factor_source(
    factor_root: Path, expected_days: list[str]
) -> tuple[dict[tuple[str, str], float], dict[str, Any]]:
    """Load an offline, receipt-pinned Tushare adj_factor panel keyed by full ts_code/date."""
    scope_path = factor_root / "scope.json"
    scope = load_json(scope_path)
    days = [compact_day(day) for day in scope.get("days", [])]
    if days != expected_days:
        raise ValueError("factor scope days must exactly match market scope days")
    if (
        not str(scope.get("provider", "")).lower().startswith("tushare")
        or scope.get("api") != "adj_factor"
        or scope.get("source_fallback", False) is not False
        or scope.get("automatic_retries", 0) != 0
    ):
        raise ValueError("factor scope provider/fallback/retry policy invalid")
    values: dict[tuple[str, str], float] = {}
    files: dict[str, str] = {"scope.json": sha256(scope_path)}
    factor_rows_by_day: dict[str, dict[str, float]] = {}
    for day in days:
        data_path = factor_root / f"{day}.json"
        receipt_path = factor_root / f"{day}.receipt.json"
        receipt = load_json(receipt_path)
        if int(receipt.get("api_code", receipt.get("code", -1))) != 0:
            raise ValueError(f"factor request failed for {day}")
        if receipt.get("sha256") != sha256(data_path):
            raise ValueError(f"factor receipt hash mismatch for {day}")
        payload = load_json(data_path)
        fields = payload.get("data", {}).get("fields", [])
        items = payload.get("data", {}).get("items", [])
        if int(payload.get("code", -1)) != 0 or not {
            "ts_code",
            "trade_date",
            "adj_factor",
        }.issubset(fields):
            raise ValueError(f"malformed factor response for {day}")
        ix = {key: fields.index(key) for key in ("ts_code", "trade_date", "adj_factor")}
        day_values: dict[str, float] = {}
        for item in items:
            code = str(item[ix["ts_code"]])
            code_parts = code.split(".")
            if (
                len(code_parts) != 2
                or len(code_parts[0]) != 6
                or not code_parts[0].isdecimal()
                or code_parts[1] not in {"SH", "SZ", "BJ"}
            ):
                raise ValueError(f"malformed full ts_code in factor response: {code!r}/{day}")
            row_day = compact_day(item[ix["trade_date"]])
            if row_day != day:
                raise ValueError(f"factor trade_date mismatch: {code}/{row_day}, expected {day}")
            raw_factor = item[ix["adj_factor"]]
            factor = float(raw_factor)
            if not math.isfinite(factor) or factor <= 0:
                raise ValueError(f"factor must be finite and positive: {code}/{day}")
            if code in day_values:
                raise ValueError(f"duplicate full factor key: {code}/{day}")
            day_values[code] = factor
            values[(code, day)] = factor
        if len(items) != int(receipt.get("rows", -1)):
            raise ValueError(f"factor receipt/item count mismatch for {day}")
        factor_rows_by_day[day] = day_values
        files[f"{day}.json"] = sha256(data_path)
        files[f"{day}.receipt.json"] = sha256(receipt_path)
    return values, {
        "root": str(factor_root.resolve()),
        "scope_sha256": files["scope.json"],
        "files_sha256": files,
        "rows_by_day": {day: len(rows) for day, rows in factor_rows_by_day.items()},
        "provider": scope["provider"],
        "key": "full ts_code + trade_date",
    }


def _factor_adjusted_window(
    rows: list[dict[str, Any]], factor_map: dict[tuple[str, str], float]
) -> list[dict[str, Any]]:
    """Call the canonical qfq normalizer on one symbol's decision-limited history."""
    if not rows:
        return []
    code = str(rows[-1]["ts_code"])
    if any(str(row["ts_code"]) != code for row in rows):
        raise ValueError("symbol code changed within factor-adjusted window")
    if any(_validate_bar(row) is not None for row in rows):
        raise ValueError("invalid raw OHLCV before factor normalization")
    factors = []
    for row in rows:
        key = (code, row["date"])
        if key not in factor_map:
            raise ValueError(f"missing factor {code}/{row['date']}")
        factors.append({"trade_date": row["date"], "adj_factor": factor_map[key]})
    daily = pd.DataFrame(
        [
            {
                "trade_date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "vol": row["volume"],
            }
            for row in rows
        ]
    )
    adj = pd.DataFrame(factors)
    from backend.data.tushare_qfq import _normalize_qfq

    normalized = _normalize_qfq(daily, adj)
    normalized = normalized.reset_index()
    by_date = {
        compact_day(value): rec
        for value, rec in zip(normalized["date"], normalized.to_dict("records"), strict=True)
    }
    result = []
    for old in rows:
        rec = by_date.get(old["date"])
        if rec is None:
            raise ValueError(f"canonical qfq helper omitted {code}/{old['date']}")
        adjusted = {
            **old,
            "open": float(rec["open"]),
            "high": float(rec["high"]),
            "low": float(rec["low"]),
            "close": float(rec["close"]),
            "volume": float(rec["volume"]),
        }
        adjusted["invalid_reason"] = _validate_bar(adjusted)
        if adjusted["invalid_reason"]:
            raise ValueError(f"invalid normalized OHLCV:{adjusted['invalid_reason']}")
        result.append(adjusted)
    return result


def _adjusted_preclose_status(
    symbol: str,
    code: str,
    days: list[str],
    by_day: dict[str, dict[str, dict[str, Any]]],
    factor_map: dict[tuple[str, str], float],
    start: int,
    end: int,
) -> str | None:
    for i in range(max(1, start), end + 1):
        current = by_day[days[i]].get(symbol)
        previous = by_day[days[i - 1]].get(symbol)
        if current is None or previous is None:
            return "missing_bar_for_adjusted_preclose_check"
        current_factor = factor_map.get((code, days[i]))
        previous_factor = factor_map.get((code, days[i - 1]))
        if current_factor is None or previous_factor is None:
            return "missing_adj_factor_for_preclose_check"
        pre_close, prev_close = current.get("pre_close"), previous.get("close")
        if (
            pre_close is None
            or prev_close is None
            or not math.isfinite(float(pre_close))
            or not math.isfinite(float(prev_close))
        ):
            return "missing_pre_close_for_adjusted_check"
        expected = float(prev_close) * previous_factor / current_factor
        if abs(float(pre_close) - expected) > BREAK_ABS_TOL:
            return "adjusted_preclose_break_or_action_uncertain"
    return None


def day_artifacts(source_root: Path, day: str, reuse_day: str | None = None) -> tuple[Path, Path]:
    data_path = source_root / f"{day}.json"
    receipt_path = source_root / f"{day}.receipt.json"
    if data_path.is_file() and receipt_path.is_file():
        return data_path, receipt_path
    if reuse_day == day:
        preflight = source_root.parent / "source-preflight"
        data_path = preflight / f"daily-{day}.json"
        receipt_path = preflight / f"daily-{day}.receipt.json"
        if data_path.is_file() and receipt_path.is_file():
            return data_path, receipt_path
    raise FileNotFoundError(f"missing raw day and receipt for {day} under {source_root}")


def freeze_protocol(
    source_root: Path,
    out_dir: Path,
    fixed25_path: Path,
    industry_path: Path,
    factor_source: Path | None = None,
) -> dict[str, Any]:
    scope_path = source_root / "scope.json"
    scope = load_json(scope_path)
    days = [compact_day(day) for day in scope.get("days", [])]
    decisions = [compact_day(day) for day in scope.get("decisions", [])]
    if days != sorted(set(days)):
        raise ValueError("scope.days must be unique and sorted")
    if not days or not decisions or not set(decisions).issubset(days):
        raise ValueError("scope must pin non-empty decisions drawn from scope.days")
    if scope.get("raw_not_adjusted") is not True:
        raise ValueError("scope must declare raw, unadjusted prices")
    if scope.get("source_fallback", False) is not False or scope.get("automatic_retries", 0) != 0:
        raise ValueError("scope fallback/retry policy differs from frozen policy")
    reuse_day = compact_day(scope.get("reuse_day")) if scope.get("reuse_day") else None
    calendar_source = scope.get("calendar_source")
    calendar = None
    if calendar_source:
        calendar_path = Path(str(calendar_source)).expanduser()
        if not calendar_path.is_absolute():
            calendar_path = source_root / calendar_path
        if not calendar_path.is_file():
            raise FileNotFoundError(f"scope-pinned calendar source missing: {calendar_path}")
        calendar_hash = sha256(calendar_path)
        declared_calendar_hash = scope.get("calendar_source_sha256")
        if declared_calendar_hash and declared_calendar_hash != calendar_hash:
            raise ValueError("scope-pinned calendar source hash mismatch")
        calendar = {
            "path": str(calendar_path.resolve()),
            "sha256": calendar_hash,
            "source_sha256_declared": declared_calendar_hash,
        }

    receipts: dict[str, dict[str, Any]] = {}
    files: dict[str, str] = {"scope.json": sha256(scope_path)}
    for day in days:
        data_path, receipt_path = day_artifacts(source_root, day, reuse_day)
        if not data_path.is_file() or not receipt_path.is_file():
            raise FileNotFoundError(f"missing raw day or receipt for {day}")
        receipt = load_json(receipt_path)
        if int(receipt.get("api_code", receipt.get("code", -1))) != 0:
            raise ValueError(f"source request failed for {day}: {receipt}")
        if receipt.get("sha256") != sha256(data_path):
            raise ValueError(f"receipt hash mismatch for {day}")
        receipts[day] = {
            "rows": int(receipt.get("rows", -1)),
            "sha256": sha256(data_path),
            "receipt_sha256": sha256(receipt_path),
            "data_path": str(data_path.resolve()),
            "receipt_path": str(receipt_path.resolve()),
            "reused": day == reuse_day,
        }
        files[f"{day}.json"] = receipts[day]["sha256"]
        files[f"{day}.receipt.json"] = receipts[day]["receipt_sha256"]

    fixed = load_json(fixed25_path)
    fixed_rows = fixed.get("stocks", fixed) if isinstance(fixed, dict) else fixed
    fixed_symbols = [str(row.get("symbol") if isinstance(row, dict) else row) for row in fixed_rows]
    fixed_symbols = sorted(set(fixed_symbols))
    if len(fixed_symbols) != 25:
        raise ValueError(
            f"fixed comparison must contain 25 unique symbols; got {len(fixed_symbols)}"
        )
    source_modules = {
        "runner": Path(__file__).resolve(),
        "config": REPO / "backend" / "config.py",
        "technical": REPO / "backend" / "analysis" / "technical.py",
        "factors": REPO / "backend" / "analysis" / "factors.py",
        "cross_sectional": REPO / "backend" / "backtest" / "statistics" / "cross_sectional.py",
    }
    if factor_source is not None:
        source_modules["tushare_qfq"] = REPO / "backend" / "data" / "tushare_qfq.py"
        _, factor_manifest = _load_factor_source(factor_source, days)
    else:
        factor_manifest = None
    protocol = {
        "protocol_version": "technical-only-market-baseline.v4",
        "frozen_before_results": True,
        "purpose": (
            "descriptive historical all-market technical ranking with decision-anchored adj_factor OHLC and factor-adjusted direction diagnostic; not the historical GPT/news arm and not NAV"
            if factor_source is not None
            else "descriptive historical all-market technical ranking and raw-price direction diagnostic; not the historical GPT/news arm and not NAV"
        ),
        "source": {
            "provider": scope.get("provider"),
            "raw_not_adjusted": True,
            "scope_sha256": files["scope.json"],
            "calendar_source": calendar,
            "days": days,
            "decisions": decisions,
            "day_count": len(days),
            "daily_receipts": receipts,
            "all_input_file_sha256": files,
            "method_code_sha256": {name: sha256(path) for name, path in source_modules.items()},
            "method_code_paths": {
                name: str(path.resolve()) for name, path in source_modules.items()
            },
            "runtime_technical_config": _technical_runtime_config(),
            "factor_source": factor_manifest,
            "rows_by_day_receipt": {day: item["rows"] for day, item in receipts.items()},
            "fallback": False,
            "automatic_retries": 0,
        },
        "universe": {
            "full_market_definition": "symbols present in each historical day's source daily response, restricted to .SH/.SZ/.BJ common-stock codes; report daily raw response rows and valid feature/label denominators separately",
            "not_a_claim": "provider-day rows are an observed market universe, not independently certified complete point-in-time listed/security membership; do not backfill today's active list into history",
            "fixed25_path": str(fixed25_path),
            "fixed25_sha256": sha256(fixed25_path),
            "fixed25_symbols": fixed_symbols,
            "current_industry_metadata_path": str(industry_path),
            "current_industry_metadata_sha256": sha256(industry_path),
            "industry_use": "descriptive coverage only; not a PIT factor, neutralizer, or eligibility gate",
        },
        "decisions": decisions,
        "warmup": {"required_bars_including_decision_bar": MIN_BARS, "price_start": days[0]},
        "technical_rule": {
            "implementation": "backend.analysis.technical.technical_score",
            "market": "CN",
            "inputs": (
                [
                    "decision-anchored qfq open",
                    "decision-anchored qfq high",
                    "decision-anchored qfq low",
                    "decision-anchored qfq close",
                    "raw volume",
                ]
                if factor_source is not None
                else ["raw open", "raw high", "raw low", "raw close", "raw volume"]
            ),
            "rank": "descending existing technical_score; ties broken by normalized symbol ascending; top-decile names are frozen on features before labels are inspected",
            "quant": "off; no Qlib/current trained model",
            "news": "off; no saved or newly scored news input; this is technical-only",
            "external_model_or_api": "none",
        },
        "labels": {
            "type": (
                "adj_factor-adjusted close-to-close direction/return diagnostic; not executable trade return or NAV"
                if factor_source is not None
                else "diagnostic close-to-close raw-price direction/return; not executable trade return"
            ),
            "horizons_trading_sessions": [3, 5],
            "date_alignment": "exact global market session index from scope.days; any missing symbol bar from decision through endpoint makes that horizon label missing",
            "price_break_check": (
                f"for each session compare raw pre_close to prior raw close * prior adj_factor/current adj_factor; mismatch > {BREAK_ABS_TOL} CNY is flagged and excluded; no missing action is inferred"
                if factor_source is not None
                else f"for each forward session compare pre_close with that symbol's prior global-session close; missing pre_close or absolute difference > {BREAK_ABS_TOL} CNY is flagged and excluded from that horizon IC/top-decile return, but counted in denominator"
            ),
            "company_actions": "factor-adjusted direction diagnostic only; no complete authoritative cash-action/tradability ledger or point-in-time membership proof; not economic or NAV certification",
            "costs_and_fills": "not modeled",
        },
        "statistics": {
            "implementation": "backend.backtest.statistics.cross_sectional.cross_sectional_ic and summarize_ic",
            "min_names_per_ic_date": 5,
            "top_decile": "ceil(10% of feature-scored candidates) by rank, frozen before labels; missing/uncertain selected labels are not replaced; report selected count, valid labels and exclusions",
            "benchmark": "equal-weight mean endpoint return of all eligible names in the same universe/date/horizon",
            "fixed25": "same source bars, decisions, score, labels, and rules restricted to frozen 25-symbol list",
        },
        "limitations": [
            "five decision dates are a workflow pilot, not statistical evidence of strategy efficacy",
            (
                "technical indicators use only factor-adjusted history through each decision; adjusted pre_close continuity mismatches anywhere in the 61-bar lookback invalidate that feature row"
                if factor_source is not None
                else "technical indicators use raw history; a detected raw pre_close discontinuity anywhere in the 61-bar feature lookback invalidates that feature row"
            ),
            "absence of a daily row is retained as missing/suspended-or-unreported; it is never forward-filled",
            "current industry classifications are descriptive only",
            "NAV, future signals, GPT/news effects, and certified economic returns are out of scope",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    return protocol


def _load_rows(
    source_root: Path, protocol: dict[str, Any]
) -> tuple[list[str], dict[str, dict[str, dict[str, Any]]]]:
    days = protocol["source"]["days"]
    by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for day in days:
        expected = protocol["source"]["daily_receipts"][day]
        path = Path(expected["data_path"])
        receipt_path = Path(expected["receipt_path"])
        if sha256(path) != expected["sha256"] or sha256(receipt_path) != expected["receipt_sha256"]:
            raise ValueError(f"frozen source file changed after protocol freeze: {day}")
        payload = load_json(path)
        if int(payload.get("code", -1)) != 0:
            raise ValueError(f"daily source response unsuccessful for {day}")
        fields = payload["data"]["fields"]
        items = payload["data"]["items"]
        index = {name: idx for idx, name in enumerate(fields)}
        needed = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol"}
        if not needed.issubset(index):
            raise ValueError(f"required raw daily fields missing for {day}: {needed - set(index)}")
        rows: dict[str, dict[str, Any]] = {}
        for item in items:
            ts_code = str(item[index["ts_code"]])
            suffix = ts_code.rsplit(".", 1)[-1]
            if suffix not in {"SH", "SZ", "BJ"}:
                continue
            symbol = normalize_code(ts_code)
            if symbol in rows:
                raise ValueError(f"duplicate symbol/day key: {symbol}/{day}")
            if str(item[index["trade_date"]]) != day:
                raise ValueError(f"trade_date mismatch: {ts_code}/{day}")

            def val(name: str, row_item: list[Any], field_index: dict[str, int]) -> float | None:
                raw = row_item[field_index[name]]
                return None if raw is None or raw == "" else float(raw)

            rows[symbol] = {
                "symbol": symbol,
                "date": day,
                "open": val("open", item, index),
                "high": val("high", item, index),
                "low": val("low", item, index),
                "close": val("close", item, index),
                "pre_close": val("pre_close", item, index),
                "volume": val("vol", item, index),
                "ts_code": ts_code,
            }
            rows[symbol]["invalid_reason"] = _validate_bar(rows[symbol])
        by_day[day] = rows
        if len(items) != expected["rows"]:
            raise ValueError(
                f"receipt/item row count mismatch: {day}: {len(items)} != {expected['rows']}"
            )
    return days, by_day


def _validate_bar(row: dict[str, Any]) -> str | None:
    values = [row.get(key) for key in ("open", "high", "low", "close", "volume")]
    if any(value is None for value in values):
        return "missing_ohlcv"
    numeric_values = [float(value) for value in values if value is not None]
    if not all(math.isfinite(value) for value in numeric_values):
        return "nonfinite_ohlcv"
    open_, high, low, close, volume = numeric_values
    if min(open_, high, low, close) <= 0:
        return "nonpositive_ohlc"
    if high < max(open_, low, close):
        return "invalid_high"
    if low > min(open_, high, close):
        return "invalid_low"
    if volume < 0:
        return "negative_volume"
    return None


def _industry_map(path: Path) -> dict[str, str]:
    payload = load_json(path)
    fields = payload["data"]["fields"]
    ix = {name: fields.index(name) for name in ("ts_code", "industry")}
    result = {}
    for row in payload["data"]["items"]:
        code = normalize_code(str(row[ix["ts_code"]]))
        result[code] = str(row[ix["industry"]] or "unknown")
    return result


def _fixed25(path: Path) -> tuple[list[str], dict[str, str]]:
    payload = load_json(path)
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    symbols, sectors = [], {}
    for row in rows:
        if isinstance(row, dict):
            symbol = str(row.get("symbol"))
            sectors[symbol] = str(row.get("sector") or "unknown")
        else:
            symbol = str(row)
            sectors[symbol] = "unknown"
        symbols.append(symbol)
    return sorted(set(symbols)), sectors


def _preclose_status(
    symbol: str, days: list[str], by_day: dict[str, dict[str, dict[str, Any]]], start: int, end: int
) -> str | None:
    for i in range(max(1, start), end + 1):
        current = by_day[days[i]].get(symbol)
        previous = by_day[days[i - 1]].get(symbol)
        if current is None or previous is None:
            return "missing_bar_for_preclose_check"
        pre_close = current.get("pre_close")
        prev_close = previous.get("close")
        if (
            pre_close is None
            or prev_close is None
            or not math.isfinite(float(pre_close))
            or not math.isfinite(float(prev_close))
        ):
            return "missing_pre_close_for_check"
        if abs(pre_close - prev_close) > BREAK_ABS_TOL:
            return "raw_preclose_break_or_action_uncertain"
    return None


def _load_technical_score(
    symbol: str, window: list[dict[str, Any]]
) -> tuple[float | None, str | None]:
    if len(window) < MIN_BARS:
        return None, "insufficient_warmup_bars"
    if any(row.get("invalid_reason") for row in window):
        reasons = sorted(
            {str(row["invalid_reason"]) for row in window if row.get("invalid_reason")}
        )
        return None, "invalid_ohlcv_in_warmup:" + ",".join(reasons)
    frame = pd.DataFrame(
        [{k: row[k] for k in ("date", "open", "high", "low", "close", "volume")} for row in window]
    )
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d")
    try:
        # Import the existing production technical implementation; no DB/session, network, or model is used.
        from backend.analysis.technical import technical_score

        result = technical_score(frame, market="CN", symbol=symbol)
        score = result.get("score")
        if score is None or not math.isfinite(float(score)):
            return None, "technical_score_nonfinite"
        return float(score), None
    except Exception as exc:  # Preserve bad feature rows in the denominator.
        return None, f"technical_error:{type(exc).__name__}"


def _load_fixed25(path: Path) -> tuple[list[str], dict[str, str]]:
    return _fixed25(path)


def calculate(
    source_root: Path,
    out_dir: Path,
    fixed25_path: Path,
    industry_path: Path,
    protocol: dict[str, Any],
    factor_source: Path | None = None,
) -> dict[str, Any]:
    days, by_day = _load_rows(source_root, protocol)
    factor_map: dict[tuple[str, str], float] | None = None
    if factor_source is not None:
        factor_map, factor_manifest = _load_factor_source(factor_source, days)
        if protocol["source"].get("factor_source") != factor_manifest:
            raise ValueError("factor source changed since protocol freeze")
    elif protocol["source"].get("factor_source") is not None:
        raise ValueError("frozen protocol requires factor-source directory")
    decision_dates = protocol["decisions"]
    industry = _industry_map(industry_path)
    fixed_symbols, fixed_sectors = _load_fixed25(fixed25_path)
    date_index = {day: i for i, day in enumerate(days)}
    all_features: list[dict[str, Any]] = []
    daily_universe: dict[str, dict[str, Any]] = {}

    # At each date, scores use only that symbol's history/factors through the decision date.
    for decision in decision_dates:
        i = date_index[decision]
        candidates = by_day[decision]
        scores = []
        score_failures: Counter[str] = Counter()
        for symbol in sorted(candidates):
            start_i = max(0, i - MIN_BARS + 1)
            window_days = days[start_i : i + 1]
            rows = [by_day[d].get(symbol) for d in window_days]
            if any(row is None for row in rows):
                score_failures["missing_bar_in_61_session_window"] += 1
                continue
            typed_rows = [row for row in rows if row is not None]
            code = str(typed_rows[-1]["ts_code"])
            if factor_map is not None:
                try:
                    typed_rows = _factor_adjusted_window(typed_rows, factor_map)
                except ValueError as exc:
                    score_failures[f"factor_adjustment_error:{str(exc).split(':', 1)[0]}"] += 1
                    continue
                preclose_status = _adjusted_preclose_status(
                    symbol, code, days, by_day, factor_map, start_i, i
                )
            else:
                preclose_status = _preclose_status(symbol, days, by_day, start_i, i)
            if preclose_status:
                score_failures[f"{preclose_status}_in_lookback"] += 1
                continue
            score, reason = _load_technical_score(symbol, typed_rows)
            if reason:
                score_failures[reason] += 1
                continue
            scores.append(
                {
                    "date": decision,
                    "symbol": symbol,
                    "technical_score": score,
                    "industry_current": industry.get(symbol, "unknown"),
                }
            )
        scores.sort(key=lambda x: (-x["technical_score"], x["symbol"]))
        for rank, row in enumerate(scores, 1):
            row["rank_all"] = rank
            row["universe"] = "all_market_observed"
            all_features.append(row)
        fixed_present = sum(1 for symbol in fixed_symbols if symbol in candidates)
        fixed_scored = [row for row in scores if row["symbol"] in set(fixed_symbols)]
        daily_universe[decision] = {
            "observed_symbols": len(candidates),
            "technical_scored_symbols": len(scores),
            "technical_missing_or_excluded": len(candidates) - len(scores),
            "fixed25_expected": len(fixed_symbols),
            "fixed25_observed": fixed_present,
            "fixed25_technical_scored": len(fixed_scored),
            "current_industry_count_scored": len(
                {row["industry_current"] for row in scores if row["industry_current"] != "unknown"}
            ),
            "current_industry_unknown_scored": sum(
                1 for row in scores if row["industry_current"] == "unknown"
            ),
            "feature_exclusions": dict(sorted(score_failures.items())),
        }

    feature_lookup = {(row["date"], row["symbol"]): row for row in all_features}
    selected_by_case: dict[str, dict[str, list[str]]] = {"all_market_observed": {}, "fixed25": {}}
    for decision in decision_dates:
        all_scored = [row for row in all_features if row["date"] == decision]
        fixed_scored = [row for row in all_scored if row["symbol"] in set(fixed_symbols)]
        scored_sets: tuple[tuple[str, list[dict[str, Any]]], ...] = (
            ("all_market_observed", all_scored),
            ("fixed25", fixed_scored),
        )
        for name, scored_rows in scored_sets:
            selected_by_case[name][decision] = _freeze_top_decile(scored_rows)

    selection_manifest = {
        "selection_frozen_before_label_calculation": True,
        "rule": "ceil(10%) of feature-scored names, descending canonical technical_score, ties by normalized symbol ascending; no replacement for missing labels",
        "by_universe_and_decision": selected_by_case,
    }

    label_rows: list[dict[str, Any]] = []
    label_denoms: dict[str, dict[str, Any]] = {}
    selected_failures: dict[str, dict[str, dict[str, Counter[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(Counter))
    )
    returns_by_case: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for decision in decision_dates:
        start_i = date_index[decision]
        observed = by_day[decision]
        cases = {
            "all_market_observed": set(observed),
            "fixed25": set(fixed_symbols),
        }
        for universe_name, symbols in cases.items():
            label_denoms.setdefault(universe_name, {})[decision] = {
                "candidate_symbols": len(symbols),
                "decision_bar_observed": sum(symbol in observed for symbol in symbols),
            }
            for horizon in (3, 5):
                label_key = f"h{horizon}"
                counts: Counter[str] = Counter()
                selected_symbols = set(selected_by_case[universe_name][decision])
                for symbol in sorted(symbols):

                    def fail(
                        reason: str,
                        *,
                        _counts: Counter[str] = counts,
                        _symbol: str = symbol,
                        _selected: set[str] = selected_symbols,
                        _universe: str = universe_name,
                        _decision: str = decision,
                        _label_key: str = label_key,
                    ) -> None:
                        _counts[reason] += 1
                        if _symbol in _selected:
                            selected_failures[_universe][_decision][_label_key][reason] += 1

                    if symbol not in observed:
                        fail("decision_day_bar_missing")
                        continue
                    feat = feature_lookup.get((decision, symbol))
                    if feat is None:
                        fail("feature_missing_or_excluded")
                        continue
                    if observed[symbol].get("close") is None:
                        fail("decision_close_missing")
                        continue
                    target_i = start_i + horizon
                    if target_i >= len(days):
                        fail("horizon_out_of_scope")
                        continue
                    step_rows = [by_day[days[j]].get(symbol) for j in range(start_i, target_i + 1)]
                    if any(row is None or row.get("close") is None for row in step_rows):
                        fail("missing_bar_in_horizon")
                        continue
                    typed_step_rows = [row for row in step_rows if row is not None]
                    invalid_reasons = sorted(
                        {
                            str(row["invalid_reason"])
                            for row in typed_step_rows
                            if row.get("invalid_reason")
                        }
                    )
                    if invalid_reasons:
                        fail("invalid_ohlcv_in_horizon:" + ",".join(invalid_reasons))
                        continue
                    code = str(typed_step_rows[-1]["ts_code"])
                    preclose_status = (
                        _adjusted_preclose_status(
                            symbol, code, days, by_day, factor_map, start_i + 1, target_i
                        )
                        if factor_map is not None
                        else _preclose_status(symbol, days, by_day, start_i + 1, target_i)
                    )
                    if preclose_status:
                        fail(preclose_status)
                        continue
                    entry = float(typed_step_rows[0]["close"])
                    exit_ = float(typed_step_rows[-1]["close"])
                    if entry <= 0 or exit_ <= 0:
                        fail("nonpositive_close")
                        continue
                    if factor_map is not None:
                        entry_factor = factor_map.get((code, days[start_i]))
                        exit_factor = factor_map.get((code, days[target_i]))
                        if entry_factor is None or exit_factor is None:
                            fail("missing_adj_factor_for_label")
                            continue
                        ret = (exit_ * exit_factor) / (entry * entry_factor) - 1.0
                    else:
                        ret = exit_ / entry - 1.0
                    row = {
                        "date": decision,
                        "symbol": symbol,
                        "technical_score": feat["technical_score"],
                        "return": ret,
                        "horizon": horizon,
                        "universe": universe_name,
                        "return_basis": "adj_factor_diagnostic"
                        if factor_map is not None
                        else "raw_price_diagnostic",
                    }
                    label_rows.append(row)
                    returns_by_case[universe_name][decision][label_key].append(row)
                    counts["valid_price_direction_labels"] += 1
                label_denoms[universe_name][decision][label_key] = dict(counts)

    from backend.backtest.statistics.cross_sectional import cross_sectional_ic, summarize_ic

    labels_df = pd.DataFrame(label_rows)
    stats: dict[str, Any] = {}
    for universe_name in ("all_market_observed", "fixed25"):
        subset = (
            labels_df[labels_df["universe"] == universe_name]
            if not labels_df.empty
            else pd.DataFrame()
        )
        per_horizon = {}
        for horizon in (3, 5):
            label_col = "return"
            hdf = subset[subset["horizon"] == horizon] if not subset.empty else pd.DataFrame()
            ic = (
                cross_sectional_ic(hdf, "technical_score", label_col, min_names=5)
                if not hdf.empty
                else pd.Series(dtype="float64")
            )
            daily = []
            for decision in decision_dates:
                label_rows_for_day = returns_by_case[universe_name][decision][f"h{horizon}"]
                selected_symbols = set(selected_by_case[universe_name][decision])
                selected_valid = [
                    row for row in label_rows_for_day if row["symbol"] in selected_symbols
                ]
                selected_n = len(selected_symbols)
                selected_excluded = selected_n - len(selected_valid)
                ordered = sorted(
                    label_rows_for_day, key=lambda x: (-x["technical_score"], x["symbol"])
                )
                daily.append(
                    {
                        "date": decision,
                        "feature_scored_candidates": sum(
                            1 for row in all_features if row["date"] == decision
                        )
                        if universe_name == "all_market_observed"
                        else sum(
                            1
                            for row in all_features
                            if row["date"] == decision and row["symbol"] in set(fixed_symbols)
                        ),
                        "valid_label_names": len(ordered),
                        "selected_top_decile_candidates_frozen_pre_label": selected_n,
                        "selected_top_decile_valid_labels": len(selected_valid),
                        "selected_top_decile_excluded_labels_no_replacement": selected_excluded,
                        "selected_top_decile_excluded_reasons": dict(
                            sorted(
                                selected_failures[universe_name][decision][f"h{horizon}"].items()
                            )
                        ),
                        "selected_top_decile_mean_return_pct_conditional_on_valid_label": round(
                            100 * sum(x["return"] for x in selected_valid) / len(selected_valid), 6
                        )
                        if selected_valid
                        else None,
                        "selected_top_decile_median_return_pct_conditional_on_valid_label": round(
                            100 * float(pd.Series([x["return"] for x in selected_valid]).median()),
                            6,
                        )
                        if selected_valid
                        else None,
                        "all_valid_mean_return_pct": round(
                            100 * sum(x["return"] for x in ordered) / len(ordered), 6
                        )
                        if ordered
                        else None,
                    }
                )
            per_horizon[f"h{horizon}"] = {
                "ic": summarize_ic(ic),
                "daily": daily,
                "candidate_denominators": {
                    date: label_denoms[universe_name][date].get(f"h{horizon}", {})
                    for date in decision_dates
                },
                "warning": "factor-adjusted" if factor_map is not None else "raw",
            }
        stats[universe_name] = per_horizon

    # Current metadata only; do not present it as historical sector membership.
    industry_counts = Counter(row["industry_current"] for row in all_features)
    payload = {
        "schema_version": "technical-only-historical-baseline.v4",
        "protocol_sha256": sha256(out_dir / "protocol.json"),
        "source_root": str(source_root),
        "source_data_verified_against_frozen_protocol": True,
        "source_sha256_by_day": {
            d: protocol["source"]["daily_receipts"][d]["sha256"] for d in days
        },
        "raw_trade_dates": days,
        "decision_dates": decision_dates,
        "market_day_coverage": {
            "days_expected": len(days),
            "days_loaded": len(by_day),
            "rows_by_day": {d: len(by_day[d]) for d in days},
            "unique_symbols_across_window": len({s for d in days for s in by_day[d]}),
            "distinct_current_industry_labels_in_scored_rows": len(industry_counts),
            "current_industry_counts_scored_rows": dict(sorted(industry_counts.items())),
            "industry_caveat": "current stock_basic metadata only; no historical industry classification claim",
        },
        "feature_coverage_by_decision": daily_universe,
        "label_denominators_by_decision": label_denoms,
        "direction_statistics": stats,
        "production_writes": False,
        "network_or_external_model_calls": False,
        "historical_gpt_or_news_arms_run": False,
        "cash_nav_certified": False,
        "economic_claim": "blocked: adj_factor-adjusted diagnostics do not supply complete authoritative cash-action/tradability ledger or point-in-time universe proof"
        if factor_map is not None
        else "blocked: raw/unadjusted prices and no complete authoritative corporate-action ledger or point-in-time tradability/universe proof",
        "price_basis": "Tushare adj_factor QFQ OHLC with each feature window anchored at that decision and separate factor-adjusted labels"
        if factor_map is not None
        else "raw unadjusted OHLC; price-direction labels screened for raw preclose breaks",
        "price_break_screen": {
            "threshold_abs_cny": BREAK_ABS_TOL,
            "formula": "raw preclose vs prior raw close * previous adj_factor/current adj_factor"
            if factor_map is not None
            else "raw preclose vs prior raw close",
            "interpretation": "unexplained discontinuity is excluded; this does not identify or fill missing actions",
        },
    }
    features_path = out_dir / "feature-scores.jsonl"
    features_bytes = "".join(
        json.dumps(
            {**row, "fixed25_member": row["symbol"] in set(fixed_symbols)},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for row in all_features
    ).encode("utf-8")
    features_path.write_bytes(features_bytes)
    manifest_path = out_dir / "selection-manifest.json"
    manifest_path.write_text(
        json.dumps(selection_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    payload["auditable_artifacts"] = {
        "feature_scores_path": str(features_path),
        "feature_scores_rows": len(all_features),
        "feature_scores_sha256": sha256(features_path),
        "selection_manifest_path": str(manifest_path),
        "selection_manifest_sha256": sha256(manifest_path),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--fixed25-universe", type=Path, default=DEFAULT_FIXED25)
    parser.add_argument("--industry-metadata", type=Path, required=True)
    parser.add_argument(
        "--factor-source",
        type=Path,
        help="saved Tushare adj_factor daily JSON and receipt directory; omitted means raw-price v4 baseline",
    )
    parser.add_argument(
        "--freeze-only",
        action="store_true",
        help="write frozen protocol and stop before calculation",
    )
    args = parser.parse_args()
    source_root = args.source_root.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    factor_source = args.factor_source.expanduser().resolve() if args.factor_source else None
    protocol_path = out_dir / "protocol.json"
    if args.freeze_only:
        if protocol_path.exists():
            raise SystemExit(f"refusing to overwrite frozen protocol: {protocol_path}")
        protocol = freeze_protocol(
            source_root,
            out_dir,
            args.fixed25_universe.resolve(),
            args.industry_metadata.resolve(),
            factor_source,
        )
        protocol_path.write_text(
            json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "protocol": str(protocol_path),
                    "sha256": sha256(protocol_path),
                    "days": protocol["source"]["day_count"],
                    "decisions": protocol["decisions"],
                    "frozen_before_results": True,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not protocol_path.is_file():
        raise SystemExit(f"missing frozen protocol; first run with --freeze-only: {protocol_path}")
    protocol = load_json(protocol_path)
    if protocol.get("protocol_version") != "technical-only-market-baseline.v4":
        raise SystemExit(
            "only v4 protocols are admissible; preserve earlier versions as superseded evidence"
        )
    scope_path = source_root / "scope.json"
    if sha256(scope_path) != protocol["source"]["scope_sha256"]:
        raise SystemExit("source scope changed since protocol freeze")
    calendar = protocol["source"].get("calendar_source")
    if calendar and sha256(Path(calendar["path"])) != calendar["sha256"]:
        raise SystemExit("scope-pinned calendar source changed since protocol freeze")
    for name, path_value in protocol["source"]["method_code_paths"].items():
        path = Path(path_value)
        if not path.is_file() or sha256(path) != protocol["source"]["method_code_sha256"][name]:
            raise SystemExit(f"method source changed since protocol freeze: {name}")
    if _technical_runtime_config() != protocol["source"]["runtime_technical_config"]:
        raise SystemExit(
            "effective technical rule/runtime configuration changed since protocol freeze"
        )
    if factor_source is not None:
        expected_factor_root = protocol["source"].get("factor_source", {}).get("root")
        if str(factor_source) != expected_factor_root:
            raise SystemExit("factor-source directory changed since protocol freeze")
    elif protocol["source"].get("factor_source") is not None:
        raise SystemExit("frozen protocol requires --factor-source")
    # Reconstruct expected source manifests and reject changed source files and fixed universe.
    for day, receipt in protocol["source"]["daily_receipts"].items():
        if sha256(Path(receipt["data_path"])) != receipt["sha256"]:
            raise SystemExit(f"source changed since protocol freeze: {day}")
        if sha256(Path(receipt["receipt_path"])) != receipt["receipt_sha256"]:
            raise SystemExit(f"source receipt changed since protocol freeze: {day}")
    if sha256(args.fixed25_universe.resolve()) != protocol["universe"]["fixed25_sha256"]:
        raise SystemExit("fixed-25 universe changed since protocol freeze")
    if (
        sha256(args.industry_metadata.resolve())
        != protocol["universe"]["current_industry_metadata_sha256"]
    ):
        raise SystemExit("industry metadata changed since protocol freeze")
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "technical-baseline.json"
    if result_path.exists():
        raise SystemExit(f"refusing to overwrite existing result: {result_path}")
    report = calculate(
        source_root,
        out_dir,
        args.fixed25_universe.resolve(),
        args.industry_metadata.resolve(),
        protocol,
        factor_source,
    )
    result_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": str(result_path),
                "protocol_sha256": report["protocol_sha256"],
                "days": report["market_day_coverage"]["days_loaded"],
                "decisions": len(report["decision_dates"]),
                "observed_symbols": report["market_day_coverage"]["unique_symbols_across_window"],
                "all_market_ic_days": {
                    u: {h: v["ic"]["ic_days"] for h, v in hs.items()}
                    for u, hs in report["direction_statistics"].items()
                },
                "cash_nav_certified": report["cash_nav_certified"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
