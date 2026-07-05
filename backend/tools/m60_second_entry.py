"""M60 Phase 2b second-entry shadow ledger (observe-only).

Reads M60 watchtower trigger artifacts and local price data, then records
deterministic hypothetical entry variants. This tool never writes MingCang DB
tables and never changes official signals, positions, or panels.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path, settings

DEFAULT_OUTPUT_DIR = Path("paper_trading/m60_out")
DEFAULT_LEDGER_PATH = DEFAULT_OUTPUT_DIR / "second_entry_ledger.json"
WATCHTOWER_PREFIX = "m60_watchtower_"
HORIZONS = (5, 10, 20)
VARIANTS = ("v1_immediate", "v2_pullback", "v3_confirm")
HYPOTHESIS_ID = "m60_2b_second_entry_rules"
REGISTRY_PATH = Path.home() / ".mingcang" / "m29_hypothesis_registry.json"


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _latest_price_date(con: sqlite3.Connection) -> str | None:
    if not _table_exists(con, "prices") or "date" not in _columns(con, "prices"):
        return None
    row = con.execute("SELECT MAX(date) FROM prices").fetchone()
    return str(row[0]) if row and row[0] else None


def _price_rows(con: sqlite3.Connection, symbol: str, through_date: str) -> list[dict[str, Any]]:
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    if not _table_exists(con, "prices") or not required <= _columns(con, "prices"):
        return []
    rows = con.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date ASC
        """,
        (symbol, through_date),
    ).fetchall()
    return [dict(row) for row in rows]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _index_by_date(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {str(row["date"]): idx for idx, row in enumerate(rows)}


def _ma5(rows: list[dict[str, Any]], idx: int) -> float | None:
    if idx < 4:
        return None
    closes = [_to_float(row.get("close")) for row in rows[idx - 4 : idx + 1]]
    if any(close is None for close in closes):
        return None
    return sum(close for close in closes if close is not None) / 5


def _atr14(rows: list[dict[str, Any]], idx: int) -> float | None:
    if idx < 14:
        return None
    true_ranges: list[float] = []
    for current_idx in range(idx - 13, idx + 1):
        high = _to_float(rows[current_idx].get("high"))
        low = _to_float(rows[current_idx].get("low"))
        prev_close = _to_float(rows[current_idx - 1].get("close"))
        if high is None or low is None or prev_close is None:
            return None
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(true_ranges) / len(true_ranges)


def _entry_for_variant(
    rows: list[dict[str, Any]],
    trigger_idx: int,
    variant: str,
) -> dict[str, Any]:
    start_idx = trigger_idx + 1
    end_idx = min(trigger_idx + 5, len(rows) - 1)
    if start_idx >= len(rows):
        return {"entry_status": "pending"}

    if variant == "v1_immediate":
        entry_open = _to_float(rows[start_idx].get("open"))
        if entry_open is None:
            return {"entry_status": "no_fill", "no_fill_reason": "missing_t_plus_1_open"}
        return {"entry_status": "filled", "entry_date": rows[start_idx]["date"], "entry_price": entry_open}

    if variant == "v2_pullback":
        for idx in range(start_idx, end_idx + 1):
            ma5 = _ma5(rows, idx)
            low = _to_float(rows[idx].get("low"))
            if ma5 is None or low is None:
                continue
            if low <= ma5:
                return {
                    "entry_status": "filled",
                    "entry_date": rows[idx]["date"],
                    "entry_price": ma5,
                    "entry_basis": {"ma5": ma5, "low": low},
                }
        if len(rows) - 1 < trigger_idx + 5:
            return {"entry_status": "pending"}
        return {"entry_status": "no_fill", "no_fill_reason": "no_ma5_touch_within_5d"}

    if variant == "v3_confirm":
        trigger_volume = _to_float(rows[trigger_idx].get("volume"))
        if trigger_volume is None:
            return {"entry_status": "no_fill", "no_fill_reason": "missing_trigger_volume"}
        post_trigger_high_close = _to_float(rows[trigger_idx].get("close"))
        for idx in range(start_idx, end_idx + 1):
            close = _to_float(rows[idx].get("close"))
            volume = _to_float(rows[idx].get("volume"))
            if close is None or volume is None or post_trigger_high_close is None:
                continue
            is_new_high = close > post_trigger_high_close
            volume_ok = volume > trigger_volume * 0.8
            if is_new_high and volume_ok:
                return {
                    "entry_status": "filled",
                    "entry_date": rows[idx]["date"],
                    "entry_price": close,
                    "entry_basis": {
                        "close": close,
                        "volume": volume,
                        "trigger_volume_threshold": trigger_volume * 0.8,
                    },
                }
            if close > post_trigger_high_close:
                post_trigger_high_close = close
        if len(rows) - 1 < trigger_idx + 5:
            return {"entry_status": "pending"}
        return {"entry_status": "no_fill", "no_fill_reason": "no_volume_confirmed_new_high_within_5d"}

    raise ValueError(f"unknown variant: {variant}")


def _update_outcomes(entry: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if entry.get("entry_status") != "filled":
        return
    entry_date = str(entry.get("entry_date"))
    entry_price = _to_float(entry.get("entry_price"))
    if entry_price is None:
        return
    idx_by_date = _index_by_date(rows)
    entry_idx = idx_by_date.get(entry_date)
    if entry_idx is None:
        return

    atr = entry.get("atr14_at_entry")
    if atr is None:
        atr = _atr14(rows, entry_idx)
        entry["atr14_at_entry"] = _round(atr, 4)
    else:
        atr = _to_float(atr)
    if atr is not None and entry.get("initial_stop_price") is None:
        entry["initial_stop_price"] = _round(entry_price - 1.5 * atr, 4)

    stop_price = _to_float(entry.get("initial_stop_price"))
    stop_hit_idx: int | None = None
    if entry.get("stop_hit") is not True and stop_price is not None:
        for idx in range(entry_idx + 1, len(rows)):
            low = _to_float(rows[idx].get("low"))
            if low is not None and low <= stop_price:
                stop_hit_idx = idx
                entry["stop_hit"] = True
                entry["stop_hit_date"] = rows[idx]["date"]
                entry["exit_price"] = _round(stop_price, 4)
                break
    elif entry.get("stop_hit") is True:
        stop_date = entry.get("stop_hit_date")
        stop_hit_idx = idx_by_date.get(str(stop_date)) if stop_date else None

    if entry.get("stop_hit") is not True:
        entry.setdefault("stop_hit", False)

    returns = entry.setdefault("returns", {})
    for horizon in HORIZONS:
        key = f"d{horizon}"
        if returns.get(key) is not None:
            continue
        target_idx = entry_idx + horizon
        if target_idx >= len(rows):
            continue
        exit_price: float | None
        if stop_hit_idx is not None and stop_hit_idx <= target_idx and stop_price is not None:
            exit_price = stop_price
        else:
            exit_price = _to_float(rows[target_idx].get("close"))
        if exit_price is None:
            continue
        returns[key] = _round(exit_price / entry_price - 1.0)


def _entry_key(symbol: str, trigger_date: str, variant: str) -> str:
    return f"{symbol}|{trigger_date}|{variant}"


def _load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "m60_second_entry_ledger.v1",
            "observe_only": True,
            "production_unchanged": True,
            "entries": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ledger must be a JSON object")
    payload.setdefault("entries", [])
    return payload


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_watchtower_path(output_dir: Path) -> Path | None:
    paths = [
        path
        for path in output_dir.glob(f"{WATCHTOWER_PREFIX}*.json")
        if path.name != DEFAULT_LEDGER_PATH.name
    ]
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)


def _load_watchtower_triggers(path: Path | None) -> tuple[str | None, list[dict[str, Any]], str | None]:
    if path is None:
        return None, [], None
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("watchtower report must be a JSON object")
    return report.get("as_of"), list(report.get("triggers") or []), str(path)


def _parse_demo_trigger(raw: str) -> dict[str, Any]:
    if "=" not in raw:
        raise ValueError("--demo-trigger must use symbol=YYYY-MM-DD")
    symbol, trigger_date = raw.split("=", 1)
    symbol = symbol.strip()
    trigger_date = trigger_date.strip()
    if not symbol or not trigger_date:
        raise ValueError("--demo-trigger must use symbol=YYYY-MM-DD")
    return {
        "symbol": symbol,
        "trigger_type": "demo_trigger",
        "demo": True,
        "price": {"date": trigger_date},
        "detail": {"source": "--demo-trigger"},
    }


def _trigger_identity(trigger: dict[str, Any], fallback_date: str | None) -> tuple[str, str]:
    symbol = str(trigger["symbol"])
    raw_price = trigger.get("price")
    price: dict[str, Any] = raw_price if isinstance(raw_price, dict) else {}
    trigger_date = price.get("date") or trigger.get("trigger_date") or fallback_date
    if not trigger_date:
        raise ValueError(f"trigger for {symbol} has no trigger date")
    return symbol, str(trigger_date)


def _new_entry(trigger: dict[str, Any], trigger_date: str, variant: str, source_path: str | None) -> dict[str, Any]:
    symbol = str(trigger["symbol"])
    return {
        "key": _entry_key(symbol, trigger_date, variant),
        "hypothesis_id": HYPOTHESIS_ID,
        "symbol": symbol,
        "trigger_date": trigger_date,
        "variant": variant,
        "trigger_type": trigger.get("trigger_type"),
        "watchtower_source": source_path,
        "demo": bool(trigger.get("demo")),
        "entry_status": "pending",
        "entry_date": None,
        "entry_price": None,
        "atr14_at_entry": None,
        "initial_stop_price": None,
        "stop_hit": False,
        "stop_hit_date": None,
        "exit_price": None,
        "returns": {"d5": None, "d10": None, "d20": None},
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "updated_at": None,
    }


def build_second_entry_ledger(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    watchtower_path: str | Path | None = None,
    watchtower_output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    demo_trigger: str | None = None,
) -> dict[str, Any]:
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    resolved_ledger_path = Path(ledger_path)
    output_dir = Path(watchtower_output_dir)
    resolved_watchtower = Path(watchtower_path) if watchtower_path is not None else _latest_watchtower_path(output_dir)

    watchtower_as_of, triggers, source_path = _load_watchtower_triggers(resolved_watchtower)
    if demo_trigger:
        triggers.append(_parse_demo_trigger(demo_trigger))

    with _connect_readonly(resolved_db) as con:
        resolved_as_of = as_of or _latest_price_date(con) or watchtower_as_of or datetime.now(UTC).date().isoformat()
        ledger = _load_ledger(resolved_ledger_path)
        existing = {entry.get("key"): entry for entry in ledger["entries"]}
        added = 0

        for trigger in triggers:
            if not trigger.get("symbol"):
                continue
            symbol, trigger_date = _trigger_identity(trigger, watchtower_as_of)
            for variant in VARIANTS:
                key = _entry_key(symbol, trigger_date, variant)
                if key in existing:
                    continue
                entry = _new_entry(trigger, trigger_date, variant, source_path)
                ledger["entries"].append(entry)
                existing[key] = entry
                added += 1

        updated = 0
        touched_symbols = sorted({str(entry.get("symbol")) for entry in ledger["entries"] if entry.get("symbol")})
        rows_by_symbol = {symbol: _price_rows(con, symbol, resolved_as_of) for symbol in touched_symbols}
        for entry in ledger["entries"]:
            symbol = str(entry.get("symbol"))
            rows = rows_by_symbol.get(symbol) or []
            trigger_idx = _index_by_date(rows).get(str(entry.get("trigger_date")))
            before = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            if trigger_idx is not None and entry.get("entry_status") == "pending":
                fill = _entry_for_variant(rows, trigger_idx, str(entry.get("variant")))
                entry.update({key: _round(value, 6) if isinstance(value, float) else value for key, value in fill.items()})
            _update_outcomes(entry, rows)
            after = json.dumps(entry, ensure_ascii=False, sort_keys=True)
            if after != before:
                entry["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                updated += 1

        entries = ledger["entries"]
        baselines = {
            "no_entry": {"return": 0.0, "description": "same-day watchtower trigger but no hypothetical entry"},
            "equal_weight_v1_pool": _equal_weight_v1_pool(entries),
        }
        ledger.update(
            {
                "schema_version": "m60_second_entry_ledger.v1",
                "hypothesis_id": HYPOTHESIS_ID,
                "observe_only": True,
                "production_unchanged": True,
                "db_read_mode": "sqlite_mode_ro",
                "as_of": resolved_as_of,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "watchtower_source": source_path,
                "baselines": baselines,
                "summary": {
                    "entries": len(entries),
                    "new_entries_added": added,
                    "entries_updated": updated,
                    "filled_entries": sum(1 for entry in entries if entry.get("entry_status") == "filled"),
                    "no_fill_entries": sum(1 for entry in entries if entry.get("entry_status") == "no_fill"),
                    "pending_entries": sum(1 for entry in entries if entry.get("entry_status") == "pending"),
                    "demo_entries": sum(1 for entry in entries if entry.get("demo")),
                },
            }
        )

    _write_ledger(resolved_ledger_path, ledger)
    return ledger


def _equal_weight_v1_pool(entries: list[dict[str, Any]]) -> dict[str, Any]:
    v1_entries = [entry for entry in entries if entry.get("variant") == "v1_immediate"]
    result: dict[str, Any] = {"description": "equal-weight pool of all V1 immediate shadow entries"}
    for horizon in HORIZONS:
        key = f"d{horizon}"
        values: list[float] = [
            value
            for entry in v1_entries
            if (entry.get("returns") or {}).get(key) is not None
            if (value := _to_float((entry.get("returns") or {}).get(key))) is not None
        ]
        result[key] = _round(sum(values) / len(values)) if values else None
        result[f"{key}_n"] = len(values)
    return result


def preregister_hypothesis(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    hypotheses = payload.setdefault("hypotheses", [])
    if any(item.get("hypothesis_id") == HYPOTHESIS_ID for item in hypotheses):
        return {"status": "skipped", "reason": "existing_hypothesis_id", "path": str(path)}
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    hypotheses.append(_second_entry_hypothesis())
    payload["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload["validation"] = {
        "passed": True,
        "errors": [],
        "note": "appended observe-only M60 Phase 2b preregistration",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "registered", "path": str(path), "backup": str(backup)}


def _second_entry_hypothesis() -> dict[str, Any]:
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "status": "data_accumulation",
        "motivation": (
            "M60 Phase 2b preregistration: watchlist trigger names may be missed when both systems "
            "only wait for deep pullbacks after high-momentum moves; compare deterministic second-entry "
            "variants against immediate-entry and no-entry baselines without affecting production."
        ),
        "source_m27_clues": [
            "m60_watchtower_forward_triggers",
            "blind_adjudication_changfei_february_case_shared_wait_for_pullback_blind_spot",
        ],
        "candidate_family": "m60_second_entry_rules",
        "candidate_type": "shadow_research_candidate",
        "forbidden_interpretation": (
            "not a production candidate and not financial advice; observe-only ledger, forbidden to "
            "change official signals, positions, panels, or live trading behavior"
        ),
        "sample_scope": {
            "universe": "M60 watchtower forward triggers from observation watchlists only",
            "min_trigger_samples_for_conclusion": 20,
            "historical_backfill_allowed": False,
            "reason": "avoid selection bias because historical trigger records lack same-time confirmation-card context",
        },
        "features": ["v1_immediate", "v2_pullback_ma5_touch_5d", "v3_volume_confirmed_new_high_5d"],
        "segments": [{"column": "variant", "values": ["v1_immediate", "v2_pullback", "v3_confirm"]}],
        "horizons": [5, 10, 20],
        "split": {
            "requires_fresh_oos_forward": True,
            "forward_only": True,
            "trigger_date_point_in_time": True,
            "no_historical_trigger_backfill": True,
        },
        "sample_gates": {
            "min_trigger_samples": 20,
            "min_validation_rows": 50,
            "min_filled_trades": 20,
            "min_filtered_trades": 20,
            "min_symbols": 4,
            "min_ic_days": 20,
            "min_quantile_buckets": 1,
            "forbid_conclusion_before_min_trigger_samples": True,
        },
        "promotion_gate": {
            "ic_min": settings.qlib_train_ic_floor,
            "icir_min": settings.qlib_train_icir_floor,
            "require_monotonic": settings.qlib_train_require_monotonic,
            "stride_icir_min": settings.qlib_train_icir_floor,
            "requires_fresh_oos_forward": True,
            "requires_no_data_quality_blockers": True,
            "requires_human_confirmation": True,
            "median_20d_return_diff_vs_v1_min_pp": 2.0,
            "max_drawdown_not_worse_than_v1": True,
        },
        "overfit_guard": {
            "requires_deflated_sharpe": True,
            "deflated_sharpe_min": 0.95,
            "requires_pbo": True,
            "pbo_max": 0.5,
            "must_report_trial_count": True,
            "trial_count_source": "declared_candidate_family_and_parameter_grid",
            "statistics_modules": [
                "backend.backtest.statistics.deflated_sharpe.deflated_sharpe",
                "backend.backtest.statistics.probability_overfitting.pbo",
            ],
            "second_entry_trial_count_source": "declared_three_entry_variants_only",
            "no_parameter_search_before_adjudication": True,
        },
        "multiple_comparison": {
            "method": "declared_family_v1_v2_v3_with_explicit_warning",
            "n_candidates_declared": 3,
            "must_report_candidate_count": True,
        },
        "stop_conditions": [
            "stop if sample has fewer than 20 forward triggers; no conclusion allowed",
            "stop if V2/V3 20-day median return advantage over V1 is <= 2pp",
            "stop if V2/V3 maximum drawdown is worse than V1",
            "stop if the ledger is used to alter official signals, positions, or panels",
        ],
        "allowed_next_action": "run observe-only ledger accrual and append forward evidence",
        "forbidden_actions": ["write_db", "change_official_signal", "change_position", "change_panel_buy_advice"],
        "planned_artifacts": ["paper_trading/m60_out/second_entry_ledger.json"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--watchtower-output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--watchtower-path", type=Path, default=None)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--demo-trigger", help="Optional symbol=YYYY-MM-DD trigger when no real trigger exists")
    parser.add_argument("--preregister", action="store_true", help="Append the M60 Phase 2b preregistration")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.preregister:
        result = preregister_hypothesis(args.registry)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    ledger = build_second_entry_ledger(
        db_path=args.db,
        as_of=args.as_of,
        watchtower_path=args.watchtower_path,
        watchtower_output_dir=args.watchtower_output_dir,
        ledger_path=args.ledger,
        demo_trigger=args.demo_trigger,
    )
    print(json.dumps({"ledger": str(args.ledger), "summary": ledger["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
