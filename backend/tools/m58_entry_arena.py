"""M58 D7 entry arena: point-in-time entry replay with outcome-side isolation.

This harness evaluates historical entry trigger points by separating:
- inputs: data visible on or before ``as_of`` only;
- outcome: post-``as_of`` returns, drawdown, and ATR stop realization.

No LLM is called. SQLite is opened in ``mode=ro``. The only writes are JSON/MD
artifacts and the append-only trial ledger under ``paper_trading/m58_out/arena``.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.config import default_sqlite_path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "paper_trading" / "m58_out" / "arena"
DEFAULT_TRIGGER_HISTORY_PATH = Path.home() / ".mingcang" / "m63_trigger_history.json"
DEFAULT_M60_LEDGER_PATH = REPO_ROOT / "paper_trading" / "m60_out" / "second_entry_ledger.json"
SCHEMA_VERSION = "m58_entry_arena.v1"
DEFAULT_HORIZONS = (5, 10, 20)
ATR_STOP_MULT = 1.5


@dataclass(frozen=True)
class TriggerPoint:
    symbol: str
    as_of: str
    trigger_source: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArenaCase:
    symbol: str
    as_of: str
    trigger_source: str
    inputs: dict[str, Any]
    outcome: dict[str, Any]
    arm: str = "entry"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    resolved = Path(db_path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"database does not exist: {resolved}")
    con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _price_rows(con: sqlite3.Connection, symbol: str) -> list[dict[str, Any]]:
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    if not _table_exists(con, "prices") or not required <= _columns(con, "prices"):
        return []
    cols = ["date", "open", "high", "low", "close", "volume"]
    if "atr14" in _columns(con, "prices"):
        cols.append("atr14")
    rows = con.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM prices
        WHERE symbol = ?
        ORDER BY date ASC
        """,
        (symbol,),
    ).fetchall()
    return [dict(row) for row in rows]


def _price_rows_cached(
    con: sqlite3.Connection,
    symbol: str,
    price_cache: dict[str, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    if price_cache is None:
        return _price_rows(con, symbol)
    if symbol not in price_cache:
        price_cache[symbol] = _price_rows(con, symbol)
    return price_cache[symbol]


def _index_by_date(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    return {str(row["date"])[:10]: idx for idx, row in enumerate(rows)}


def _price_as_of(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "prices"):
        return None
    row = con.execute(
        """
        SELECT *
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return _row_dict(row)


def _latest_row_pit(
    con: sqlite3.Connection,
    table: str,
    symbol: str,
    date_columns: Sequence[str],
    as_of: str,
) -> dict[str, Any] | None:
    if not _table_exists(con, table):
        return None
    cols = _columns(con, table)
    if "symbol" not in cols:
        return None
    date_col = next((col for col in date_columns if col in cols), None)
    if not date_col:
        return None
    row = con.execute(
        f"""
        SELECT *
        FROM {table}
        WHERE symbol = ? AND substr({date_col}, 1, 10) <= ?
        ORDER BY {date_col} DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return _row_dict(row)


def collect_inputs_pit(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    trigger_source: str,
    trigger_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect structured entry evidence visible at ``as_of`` only."""
    return {
        "pit_as_of": as_of,
        "trigger": {"source": trigger_source, "payload": trigger_payload or {}},
        "price": _price_as_of(con, symbol, as_of),
        "signal": _latest_row_pit(con, "signals", symbol, ("created_at", "date", "signal_date"), as_of),
        "long_term_label": _latest_row_pit(con, "long_term_labels", symbol, ("as_of", "created_at", "date"), as_of),
        "forward_thesis": _latest_row_pit(con, "forward_theses", symbol, ("created_at", "updated_at", "horizon_date"), as_of),
    }


def _computed_atr14(rows: Sequence[dict[str, Any]], idx: int) -> float | None:
    if idx < 14:
        return None
    ranges: list[float] = []
    for current in range(idx - 13, idx + 1):
        high = _to_float(rows[current].get("high"))
        low = _to_float(rows[current].get("low"))
        prev_close = _to_float(rows[current - 1].get("close"))
        if high is None or low is None or prev_close is None:
            return None
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(ranges) / len(ranges)


def _return_at_horizon(rows: Sequence[dict[str, Any]], start_idx: int, horizon: int) -> float | None:
    target_idx = start_idx + horizon
    if target_idx >= len(rows):
        return None
    base = _to_float(rows[start_idx].get("close"))
    target = _to_float(rows[target_idx].get("close"))
    if base is None or not base or target is None:
        return None
    return target / base - 1.0


def _max_drawdown(rows: Sequence[dict[str, Any]], start_idx: int, horizon: int) -> float | None:
    target_idx = min(start_idx + horizon, len(rows) - 1)
    if target_idx <= start_idx:
        return None
    base = _to_float(rows[start_idx].get("close"))
    if base is None or base == 0:
        return None
    closes: list[float] = [
        value
        for row in rows[start_idx + 1 : target_idx + 1]
        if (value := _to_float(row.get("close"))) is not None
    ]
    if not closes:
        return None
    return min(closes) / base - 1.0


def _atr_stop_hit(rows: Sequence[dict[str, Any]], start_idx: int, horizon: int) -> tuple[bool | None, str | None, float | None]:
    base = _to_float(rows[start_idx].get("close"))
    if base is None:
        return None, None, None
    atr = _to_float(rows[start_idx].get("atr14"))
    if atr is None:
        atr = _computed_atr14(rows, start_idx)
    if atr is None:
        return None, None, None
    stop = base - ATR_STOP_MULT * atr
    target_idx = min(start_idx + horizon, len(rows) - 1)
    for row in rows[start_idx + 1 : target_idx + 1]:
        low = _to_float(row.get("low"))
        if low is not None and low <= stop:
            return True, str(row["date"])[:10], stop
    return False, None, stop


def _baseline_return(
    con: sqlite3.Connection,
    *,
    universe: Sequence[str],
    as_of: str,
    horizon: int,
    price_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    returns: list[float] = []
    for member in sorted({str(sym) for sym in universe if sym}):
        rows = _price_rows_cached(con, member, price_cache)
        idx = _index_by_date(rows).get(as_of)
        if idx is None:
            continue
        value = _return_at_horizon(rows, idx, horizon)
        if value is not None:
            returns.append(value)
    return {
        "return": (sum(returns) / len(returns)) if returns else None,
        "n": len(returns),
    }


def compute_outcome(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    universe: Sequence[str],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    price_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = _price_rows_cached(con, symbol, price_cache)
    start_idx = _index_by_date(rows).get(as_of)
    if start_idx is None:
        return {"status": "missing_as_of_price", "horizons": {}, "atr_stop_hit_any": None}

    out: dict[str, Any] = {
        "status": "ok",
        "outcome_side_note": "post-as_of prices are used only here, never in inputs",
        "horizons": {},
        "atr_stop_hit_any": False,
    }
    for horizon in horizons:
        raw_return = _return_at_horizon(rows, start_idx, int(horizon))
        baseline = _baseline_return(
            con,
            universe=universe,
            as_of=as_of,
            horizon=int(horizon),
            price_cache=price_cache,
        )
        drawdown = _max_drawdown(rows, start_idx, int(horizon))
        stop_hit, stop_date, stop_price = _atr_stop_hit(rows, start_idx, int(horizon))
        baseline_ret = baseline["return"]
        out["horizons"][f"d{int(horizon)}"] = {
            "raw_return": _round(raw_return),
            "baseline_return": _round(baseline_ret),
            "baseline_n": baseline["n"],
            "excess_return": _round(raw_return - baseline_ret) if raw_return is not None and baseline_ret is not None else None,
            "max_drawdown": _round(drawdown),
            "atr_stop_hit": stop_hit,
            "atr_stop_date": stop_date,
            "atr_stop_price": _round(stop_price, 4),
        }
        if stop_hit is True:
            out["atr_stop_hit_any"] = True
    return out


def build_arena_case(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    trigger_source: str,
    trigger_payload: dict[str, Any] | None = None,
    universe: Sequence[str],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    arm: str = "entry",
    price_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> ArenaCase:
    inputs = collect_inputs_pit(
        con,
        symbol=symbol,
        as_of=as_of,
        trigger_source=trigger_source,
        trigger_payload=trigger_payload,
    )
    outcome = compute_outcome(
        con,
        symbol=symbol,
        as_of=as_of,
        universe=universe,
        horizons=horizons,
        price_cache=price_cache,
    )
    return ArenaCase(symbol=symbol, as_of=as_of, trigger_source=trigger_source, inputs=inputs, outcome=outcome, arm=arm)


def _available_symbols(con: sqlite3.Connection) -> list[str]:
    if not _table_exists(con, "prices") or "symbol" not in _columns(con, "prices"):
        return []
    rows = con.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol").fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _available_dates(con: sqlite3.Connection, *, start: str | None = None, end: str | None = None) -> list[str]:
    if not _table_exists(con, "prices") or "date" not in _columns(con, "prices"):
        return []
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = con.execute(f"SELECT DISTINCT date FROM prices {where} ORDER BY date", params).fetchall()
    return [str(row[0])[:10] for row in rows if row[0]]


def _random_control_points(
    con: sqlite3.Connection,
    *,
    sample_count: int,
    universe: Sequence[str],
    seed: int,
    start: str | None = None,
    end: str | None = None,
    price_cache: dict[str, list[dict[str, Any]]] | None = None,
) -> list[TriggerPoint]:
    candidates: list[tuple[str, str]] = []
    for symbol in universe:
        rows = _price_rows_cached(con, str(symbol), price_cache)
        for row in rows:
            day = str(row["date"])[:10]
            if start and day < start:
                continue
            if end and day > end:
                continue
            candidates.append((str(symbol), day))
    rng = random.Random(seed)
    if len(candidates) <= sample_count:
        selected = candidates
    else:
        selected = rng.sample(candidates, sample_count)
    return [
        TriggerPoint(symbol=symbol, as_of=day, trigger_source="random_control", payload={"control_seed": seed})
        for symbol, day in selected
    ]


def build_arena_batch(
    *,
    db_path: str | Path,
    triggers: Sequence[TriggerPoint],
    universe: Sequence[str] | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    random_seed: int = 58,
) -> dict[str, Any]:
    with connect_readonly(db_path) as con:
        resolved_universe = list(universe or _available_symbols(con))
        price_cache: dict[str, list[dict[str, Any]]] = {}
        cases = [
            build_arena_case(
                con,
                symbol=trigger.symbol,
                as_of=trigger.as_of,
                trigger_source=trigger.trigger_source,
                trigger_payload=trigger.payload,
                universe=resolved_universe,
                horizons=horizons,
                arm="entry",
                price_cache=price_cache,
            )
            for trigger in triggers
        ]
        start = min((case.as_of for case in cases), default=None)
        end = max((case.as_of for case in cases), default=None)
        control_points = _random_control_points(
            con,
            sample_count=len(cases),
            universe=resolved_universe,
            seed=random_seed,
            start=start,
            end=end,
            price_cache=price_cache,
        )
        controls = [
            build_arena_case(
                con,
                symbol=point.symbol,
                as_of=point.as_of,
                trigger_source=point.trigger_source,
                trigger_payload=point.payload,
                universe=resolved_universe,
                horizons=horizons,
                arm="random_control",
                price_cache=price_cache,
            )
            for point in control_points
        ]

    batch_id = f"m58_entry_arena_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "meta": {
            "db_read_mode": "sqlite_mode_ro",
            "zero_llm": True,
            "baseline": "same_pool_equal_weight",
            "horizons": [int(h) for h in horizons],
            "universe_size": len(resolved_universe),
            "entry_case_count": len(cases),
            "control_case_count": len(controls),
            "trial_count": len(cases) + len(controls),
        },
        "cases": [case.to_dict() for case in cases],
        "control_cases": [case.to_dict() for case in controls],
        "calibration": calibrate(cases, _default_score_fn, bins=[0.0, 0.33, 0.66, 1.0]) if cases else None,
    }


def _readiness_calibration_for_cases(
    cases: Sequence[ArenaCase],
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    from backend.tools.m59_readiness import (
        DEFAULT_BINS,
        evaluate_calibration_gates,
        readiness_score_for_arena_case,
    )

    windows = []
    for name, left, right in (("2024H2", "2024-07-01", "2024-12-31"), ("2025H1", "2025-01-01", "2025-06-30")):
        if right < start or left > end:
            continue
        window_cases = [case for case in cases if max(start, left) <= case.as_of <= min(end, right)]
        calibration = calibrate(window_cases, readiness_score_for_arena_case, bins=DEFAULT_BINS, horizon="d5")
        calibration["name"] = name
        calibration["start"] = max(start, left)
        calibration["end"] = min(end, right)
        calibration["case_count"] = len(window_cases)
        windows.append(calibration)
    gates = evaluate_calibration_gates(windows)
    return {
        "schema_version": "m58_entry_arena.thesis_backscan_readiness.v1",
        "score_fn": "backend.tools.m59_readiness.readiness_score_for_arena_case",
        "gate_status": "pass" if all(gate.get("pass") for gate in gates.values()) else "fail",
        "gates": gates,
        "bin_edges": list(DEFAULT_BINS),
        "windows": windows,
        "assumption": (
            "Historical replay asks when these 2026-authored thesis conditions would have lit up if the thesis "
            "had existed then. Condition evaluation is PIT-clean, but theme membership is selected after the fact; "
            "use this for method validation, not return claims."
        ),
    }


def thesis_backscan_triggers(
    con: sqlite3.Connection,
    *,
    symbols_by_theme: dict[str, Sequence[str]],
    start: str,
    end: str,
) -> tuple[list[TriggerPoint], dict[str, Any]]:
    from backend.tools.m60_thesis_conditions import historical_condition_backscan

    backscan = historical_condition_backscan(
        con,
        symbols_by_theme=symbols_by_theme,
        start=start,
        end=end,
        condition_type="validation",
    )
    points = [
        TriggerPoint(
            symbol=str(hit["symbol"]),
            as_of=str(hit["as_of"])[:10],
            trigger_source="thesis_validation_backscan",
            payload={
                **hit,
                "trigger_type": "thesis_validation",
                "pit_note": "condition evaluation uses data dated on or before as_of only",
            },
        )
        for hit in backscan.get("hits") or []
    ]
    return points, backscan


def _load_watchlist_symbols_by_theme(path: Path | None) -> tuple[dict[str, list[str]], dict[str, Any]]:
    from backend.research.watchlist import WATCHLIST_DIR, load_watchlists, symbols_by_theme

    entries, errors = load_watchlists(path or WATCHLIST_DIR, authoritative_thesis=False)
    mapping = symbols_by_theme(entries)
    return mapping, {
        "watchlist_dir": str(path or WATCHLIST_DIR),
        "theme_count": len(mapping),
        "symbol_count": len({symbol for symbols in mapping.values() for symbol in symbols}),
        "errors": errors,
    }


def _default_score_fn(case: ArenaCase) -> float | None:
    signal = case.inputs.get("signal") or {}
    score = _to_float(signal.get("composite_score") or signal.get("score"))
    if score is None:
        return None
    return max(0.0, min(1.0, score / 100.0))


def _rankdata(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[idx][1]:
            end += 1
        rank = (idx + end + 2) / 2.0
        for pos in range(idx, end + 1):
            ranks[indexed[pos][0]] = rank
        idx = end + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if not denom:
        return None
    return sum(x * y for x, y in zip(dx, dy, strict=False)) / denom


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> dict[str, Any]:
    rho = _pearson(_rankdata(xs), _rankdata(ys)) if len(xs) >= 2 else None
    return {"rho": _round(rho), "n": len(xs), "status": "ok" if rho is not None else "insufficient"}


def calibrate(
    cases: Sequence[ArenaCase],
    score_fn: Callable[[ArenaCase], float | None],
    bins: Sequence[float],
    *,
    horizon: str = "d5",
) -> dict[str, Any]:
    scored: list[tuple[ArenaCase, float, float, float]] = []
    for case in cases:
        score = score_fn(case)
        bucket_outcome = (case.outcome.get("horizons") or {}).get(horizon) or {}
        excess = _to_float(bucket_outcome.get("excess_return"))
        baseline = _to_float(bucket_outcome.get("baseline_return"))
        if score is None or excess is None:
            continue
        scored.append((case, float(score), excess, baseline or 0.0))

    rows: list[dict[str, Any]] = []
    for idx in range(len(bins) - 1):
        left = float(bins[idx])
        right = float(bins[idx + 1])
        include_right = idx == len(bins) - 2
        bucket = [
            item
            for item in scored
            if item[1] >= left and (item[1] <= right if include_right else item[1] < right)
        ]
        excess_values = [item[2] for item in bucket]
        baseline_values = [item[3] for item in bucket]
        rows.append(
            {
                "bin": f"[{left:g},{right:g}{']' if include_right else ')'}",
                "sample_count": len(bucket),
                "sample_status": "ok" if len(bucket) >= 30 else "insufficient",
                "win_rate": _round(sum(1 for value in excess_values if value > 0) / len(excess_values)) if excess_values else None,
                "average_excess": _round(sum(excess_values) / len(excess_values)) if excess_values else None,
                "baseline_win_rate": _round(sum(1 for value in baseline_values if value > 0) / len(baseline_values)) if baseline_values else None,
            }
        )

    return {
        "schema_version": "m58_entry_arena.calibration.v1",
        "horizon": horizon,
        "bins": rows,
        "spearman": _spearman([item[1] for item in scored], [item[2] for item in scored]),
    }


def load_history_triggers(
    *,
    trigger_history_path: Path = DEFAULT_TRIGGER_HISTORY_PATH,
    m60_ledger_path: Path = DEFAULT_M60_LEDGER_PATH,
) -> list[TriggerPoint]:
    points: list[TriggerPoint] = []
    if trigger_history_path.exists():
        payload = json.loads(trigger_history_path.read_text(encoding="utf-8"))
        for item in payload if isinstance(payload, list) else []:
            target = item.get("target") or item.get("symbol")
            day = item.get("date") or item.get("as_of") or item.get("trigger_date")
            if target and day:
                points.append(
                    TriggerPoint(
                        symbol=str(target),
                        as_of=str(day)[:10],
                        trigger_source=str(item.get("trigger_rule") or item.get("trigger_type") or "m63_trigger_history"),
                        payload=dict(item),
                    )
                )
    if m60_ledger_path.exists():
        payload = json.loads(m60_ledger_path.read_text(encoding="utf-8"))
        for item in payload.get("entries", []) if isinstance(payload, dict) else []:
            symbol = item.get("symbol")
            day = item.get("trigger_date")
            if symbol and day:
                points.append(
                    TriggerPoint(
                        symbol=str(symbol),
                        as_of=str(day)[:10],
                        trigger_source=f"m60_second_entry:{item.get('variant') or 'unknown'}",
                        payload=dict(item),
                    )
                )
    dedup: dict[tuple[str, str, str], TriggerPoint] = {}
    for point in points:
        dedup[(point.symbol, point.as_of, point.trigger_source)] = point
    return list(dedup.values())


def synthetic_sweep_triggers(
    con: sqlite3.Connection,
    *,
    universe: Sequence[str],
    start: str,
    end: str,
    sample_rate: float,
    seed: int = 58,
) -> list[TriggerPoint]:
    if sample_rate <= 0 or sample_rate > 1:
        raise ValueError("--sample-rate must be in (0, 1]")
    rng = random.Random(seed)
    points: list[TriggerPoint] = []
    for symbol in universe:
        for row in _price_rows(con, str(symbol)):
            day = str(row["date"])[:10]
            if start <= day <= end and rng.random() <= sample_rate:
                points.append(TriggerPoint(symbol=str(symbol), as_of=day, trigger_source="synthetic_sweep"))
    return points


def _load_universe(path: Path | None, con: sqlite3.Connection) -> list[str]:
    if path is None:
        return _available_symbols(con)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        symbols: list[str] = []
        for item in payload:
            if isinstance(item, str):
                symbols.append(item)
            elif isinstance(item, dict) and item.get("symbol"):
                symbols.append(str(item["symbol"]))
        return sorted(set(symbols))
    if isinstance(payload, dict):
        raw = payload.get("symbols") or payload.get("universe") or payload.get("items") or []
        return sorted({str(item.get("symbol") if isinstance(item, dict) else item) for item in raw if item})
    raise ValueError("universe JSON must be a list or object")


def _write_outputs(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_id = str(report["batch_id"])
    json_path = out_dir / f"{batch_id}.json"
    md_path = out_dir / f"{batch_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    ledger_path = out_dir / "trial_ledger.jsonl"
    ledger_row = {
        "batch_id": batch_id,
        "generated_at": report.get("generated_at"),
        "trial_count": report.get("meta", {}).get("trial_count"),
        "entry_case_count": report.get("meta", {}).get("entry_case_count"),
        "control_case_count": report.get("meta", {}).get("control_case_count"),
    }
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_row, ensure_ascii=False) + "\n")
    return json_path, md_path


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _arm_summary(cases: Sequence[dict[str, Any]], horizon_key: str) -> dict[str, Any]:
    rows = [(case.get("outcome", {}).get("horizons") or {}).get(horizon_key) or {} for case in cases]
    excess = [_to_float(row.get("excess_return")) for row in rows]
    return {
        "n": sum(1 for value in excess if value is not None),
        "win_rate": _round(sum(1 for value in excess if value is not None and value > 0) / sum(1 for value in excess if value is not None))
        if any(value is not None for value in excess)
        else None,
        "avg_excess": _round(_mean(excess)),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    horizons = report.get("meta", {}).get("horizons") or []
    lines = [
        f"# M58 Entry Arena {report.get('batch_id')}",
        "",
        f"- schema: {report.get('schema_version')}",
        f"- db_read_mode: {report.get('meta', {}).get('db_read_mode')}",
        f"- zero_llm: {report.get('meta', {}).get('zero_llm')}",
        f"- trial_count: {report.get('meta', {}).get('trial_count')}",
        f"- entry/control: {report.get('meta', {}).get('entry_case_count')} / {report.get('meta', {}).get('control_case_count')}",
    ]
    if report.get("meta", {}).get("case_source") == "thesis_validation_backscan":
        stats = ((report.get("meta", {}).get("thesis_backscan") or {}).get("stats") or {})
        lines.extend(
            [
                f"- case_source: {report.get('meta', {}).get('case_source')}",
                f"- backscan_window: {report.get('meta', {}).get('backscan_start')} to {report.get('meta', {}).get('backscan_end')}",
                f"- thesis_backscan_hits: {stats.get('hit_count')} / evaluated_points: {stats.get('evaluated_points')}",
                "- assumption: 2026-authored thesis conditions are replayed as if they had existed then; condition inputs are PIT-clean, while theme membership is ex-post and survivor-biased. Results validate method coverage only, not returns.",
            ]
        )
        readiness = report.get("readiness_calibration") or {}
        if readiness:
            lines.extend(["", "## Readiness Calibration Gates", ""])
            lines.append(f"- gate_status: {readiness.get('gate_status')}")
            for name, gate in (readiness.get("gates") or {}).items():
                lines.append(f"- {name}: {gate.get('pass')}")
            for window in readiness.get("windows") or []:
                lines.extend(["", f"### {window.get('name')}", "| bin | n | win_rate | status |", "|---|---:|---:|---|"])
                for row in window.get("bins") or []:
                    lines.append(f"| {row.get('bin')} | {row.get('sample_count')} | {row.get('win_rate')} | {row.get('sample_status')} |")
    lines.extend(
        [
        "",
        "## Arm Summary",
        "",
        "| horizon | arm | n | win_rate | avg_excess |",
        "|---|---|---:|---:|---:|",
        ]
    )
    for horizon in horizons:
        key = f"d{horizon}"
        for arm_name, case_key in (("entry", "cases"), ("random_control", "control_cases")):
            summary = _arm_summary(report.get(case_key) or [], key)
            lines.append(
                f"| {key} | {arm_name} | {summary['n']} | {summary['win_rate']} | {summary['avg_excess']} |"
            )
    lines.extend(["", "## Calibration", ""])
    calibration = report.get("calibration") or {}
    lines.append(f"- spearman: {calibration.get('spearman')}")
    for row in calibration.get("bins") or []:
        lines.append(
            f"- {row['bin']}: n={row['sample_count']}, status={row['sample_status']}, "
            f"win={row['win_rate']}, avg_excess={row['average_excess']}, baseline_win={row['baseline_win_rate']}"
        )
    return "\n".join(lines) + "\n"


def _parse_horizons(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values or any(value <= 0 for value in values):
        raise ValueError("--horizons must contain positive integers")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--from-history", action="store_true")
    mode.add_argument("--synthetic-sweep", action="store_true")
    mode.add_argument("--thesis-backscan", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--sample-rate", type=float, default=0.05)
    parser.add_argument("--horizons", default="5,10,20")
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    parser.add_argument("--universe", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--random-seed", type=int, default=58)
    parser.add_argument("--trigger-history-path", type=Path, default=DEFAULT_TRIGGER_HISTORY_PATH)
    parser.add_argument("--m60-ledger-path", type=Path, default=DEFAULT_M60_LEDGER_PATH)
    args = parser.parse_args(argv)

    horizons = _parse_horizons(args.horizons)
    with connect_readonly(args.db_path) as con:
        thesis_backscan_meta: dict[str, Any] | None = None
        if args.thesis_backscan:
            if not args.start or not args.end:
                parser.error("--thesis-backscan requires --start and --end")
            symbols_by_theme_map, watchlist_meta = _load_watchlist_symbols_by_theme(args.universe)
            universe = sorted({symbol for symbols in symbols_by_theme_map.values() for symbol in symbols})
            triggers, thesis_backscan_meta = thesis_backscan_triggers(
                con,
                symbols_by_theme=cast(dict[str, Sequence[str]], symbols_by_theme_map),
                start=args.start,
                end=args.end,
            )
            thesis_backscan_meta["watchlists"] = watchlist_meta
        else:
            universe = _load_universe(args.universe, con)
        if args.from_history:
            triggers = load_history_triggers(
                trigger_history_path=args.trigger_history_path,
                m60_ledger_path=args.m60_ledger_path,
            )
        elif args.synthetic_sweep:
            if not args.start or not args.end:
                parser.error("--synthetic-sweep requires --start and --end")
            triggers = synthetic_sweep_triggers(
                con,
                universe=universe,
                start=args.start,
                end=args.end,
                sample_rate=args.sample_rate,
                seed=args.random_seed,
            )

    report = build_arena_batch(
        db_path=args.db_path,
        triggers=triggers,
        universe=universe,
        horizons=horizons,
        random_seed=args.random_seed,
    )
    if args.thesis_backscan:
        cases = [ArenaCase(**case) for case in report.get("cases") or []]
        report["meta"].update(
            {
                "case_source": "thesis_validation_backscan",
                "backscan_start": args.start,
                "backscan_end": args.end,
                "thesis_backscan": thesis_backscan_meta,
            }
        )
        report["readiness_calibration"] = _readiness_calibration_for_cases(cases, start=args.start, end=args.end)
    json_path, md_path = _write_outputs(report, args.out_dir)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "meta": report["meta"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
