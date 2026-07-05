"""M58 Phase 1 grid backtest harness for price-derived signal families.

This module is intentionally deterministic and read-only against MingCang's
SQLite prices table. It implements the Phase 1 harness only: T/M families,
selection and risk-avoidance slots, plus the two rule combinations from the
M58 spec. Exit and LGBM walk-forward channels are left for later phases.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import pandas as pd

from backend.analysis.factors import add_all_factors
from backend.analysis.technical import (
    adx_filter_factor,
    check_limit_status,
    score_macd,
    score_rsi,
    score_trend,
    score_volume,
)
from backend.backtest.costs import net_return
from backend.backtest.statistics import deflated_sharpe, pbo
from backend.config import default_sqlite_path

OUTPUT_DIR = Path("/private/tmp")
DEFAULT_FAMILIES = ("T", "M")
RULE_GRID = ("gate_T_exclude_M_bottom20", "serial_M_top50_then_T")


@dataclass(frozen=True)
class Trial:
    name: str
    kind: str
    weights: dict[str, float]


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"database does not exist: {resolved}")
    con = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _holdout_cutoff(today: date | None = None) -> date:
    today = today or date.today()
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def resolve_effective_end(
    requested_end: str | None,
    *,
    include_holdout: bool = False,
    today: date | None = None,
) -> str:
    if include_holdout:
        raise NotImplementedError("holdout 只能由 leader 显式解锁")
    cutoff = _holdout_cutoff(today)
    if requested_end is None:
        return cutoff.isoformat()
    requested = date.fromisoformat(requested_end)
    return min(requested, cutoff).isoformat()


def compute_technical_scores(df: pd.DataFrame, *, symbol: str | None = None) -> pd.Series:
    """Recompute production technical_score point-in-time for every row."""
    if df.empty:
        return pd.Series(dtype=float)
    factors = add_all_factors(df.reset_index(drop=True))
    scores: list[float] = []
    weights = {"trend": 0.4, "rsi": 0.25, "macd": 0.25, "volume": 0.1}
    for end in range(1, len(factors) + 1):
        window = factors.iloc[:end]
        if len(window) < 2:
            scores.append(0.0)
            continue
        components = {
            "trend": score_trend(window),
            "rsi": score_rsi(window),
            "macd": score_macd(window),
            "volume": score_volume(window),
        }
        raw = sum(components[key] * weights[key] for key in components) * 100
        composite = raw * adx_filter_factor(window)
        # Keep limit-status calculation in the PIT loop to mirror production
        # side effects/guards even though the score does not use its payload.
        check_limit_status(window, symbol=symbol)
        scores.append(round(composite, 1))
    return pd.Series(scores, index=df.index, dtype=float)


def add_family_scores(prices: pd.DataFrame) -> pd.DataFrame:
    out_parts: list[pd.DataFrame] = []
    for symbol, grp in prices.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        local = grp.copy().reset_index(drop=True)
        local["T"] = compute_technical_scores(local, symbol=str(symbol))
        close = pd.to_numeric(local["close"], errors="coerce")
        mom5 = close / close.shift(5) - 1
        mom20 = close / close.shift(20) - 1
        local["M"] = 0.6 * mom5 + 0.4 * mom20
        out_parts.append(local)
    return pd.concat(out_parts, ignore_index=True) if out_parts else pd.DataFrame()


def normalize_families(panel: pd.DataFrame, families: list[str], *, method: str) -> pd.DataFrame:
    out = panel.copy()
    for family in families:
        values = pd.to_numeric(out[family], errors="coerce")
        if method == "zscore":
            grouped = values.groupby(out["date"])
            mu = grouped.transform("mean")
            sigma = grouped.transform(lambda s: s.std(ddof=1))
            out[family] = ((values - mu) / sigma.replace(0, math.nan)).replace([math.inf, -math.inf], math.nan).fillna(0.0)
        elif method == "rank":
            ranks = values.groupby(out["date"]).rank(method="average", pct=True)
            counts = values.groupby(out["date"]).transform("count")
            out[family] = ((ranks * counts - 1) / (counts - 1).replace(0, math.nan)).fillna(0.5)
        else:
            raise ValueError(f"unsupported normalization: {method}")
    return out


def enumerate_weight_grid(families: list[str]) -> list[dict[str, Any]]:
    if families != ["T", "M"]:
        unsupported = ",".join(families)
        raise NotImplementedError(f"Phase 1 supports T,M only; got {unsupported}")
    trials: list[dict[str, Any]] = [
        {"name": "weight:T=1.0", "weights": {"T": 1.0, "M": 0.0}, "kind": "weighted"},
        {"name": "weight:M=1.0", "weights": {"T": 0.0, "M": 1.0}, "kind": "weighted"},
    ]
    for t_step in range(1, 10):
        t_weight = round(t_step / 10, 1)
        m_weight = round(1.0 - t_weight, 1)
        trials.append(
            {
                "name": f"weight:T={t_weight:.1f},M={m_weight:.1f}",
                "weights": {"T": t_weight, "M": m_weight},
                "kind": "weighted",
            }
        )
    return trials


def apply_weight_score(panel: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    out = panel.copy()
    out["score"] = 0.0
    for family, weight in weights.items():
        out["score"] = out["score"] + pd.to_numeric(out[family], errors="coerce").fillna(0.0) * weight
    return out


def apply_rule_score(panel: pd.DataFrame, rule_name: str) -> pd.DataFrame:
    out = panel.copy()
    if rule_name == "gate_T_exclude_M_bottom20":
        m_pct = out.groupby("date")["M"].rank(method="average", pct=True)
        out["score"] = pd.to_numeric(out["T"], errors="coerce").fillna(0.0)
        out.loc[m_pct <= 0.2, "score"] = -1e9
        return out
    if rule_name == "serial_M_top50_then_T":
        m_pct = out.groupby("date")["M"].rank(method="average", pct=True)
        out["score"] = pd.to_numeric(out["T"], errors="coerce").fillna(0.0)
        out.loc[m_pct < 0.5, "score"] = -1e9
        return out
    raise ValueError(f"unsupported rule: {rule_name}")


def attach_forward_returns(prices: pd.DataFrame) -> pd.DataFrame:
    out_parts: list[pd.DataFrame] = []
    for _, grp in prices.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        local = grp.copy().reset_index(drop=True)
        close = pd.to_numeric(local["close"], errors="coerce")
        entry = close.shift(-1)
        exit_ = close.shift(-6)
        gross = exit_ / entry - 1
        local["forward_5d_net_return"] = gross.map(lambda value: net_return(float(value)) if pd.notna(value) else math.nan)
        out_parts.append(local)
    return pd.concat(out_parts, ignore_index=True) if out_parts else pd.DataFrame()


def regime_from_pool_equal_weight(
    panel: pd.DataFrame,
    *,
    short_window: int = 20,
    long_window: int = 60,
    flat_band: float = 0.02,
) -> pd.DataFrame:
    """Classify regimes using a pool equal-weight index when HS300 data is absent.

    The fallback first normalizes each symbol to its first in-sample close, then
    averages those normalized levels by date. A short moving average above the
    long moving average by ``flat_band`` is ``up``; below by the band is ``down``;
    otherwise ``flat``. Early dates without both averages are ``unknown``.
    """
    if panel.empty:
        return pd.DataFrame(columns=["date", "regime"])
    local = panel.sort_values(["symbol", "date"]).copy()
    local["close"] = pd.to_numeric(local["close"], errors="coerce")
    local["_base"] = local.groupby("symbol")["close"].transform("first")
    local["_norm"] = local["close"] / local["_base"]
    index = local.groupby("date")["_norm"].mean().sort_index()
    short = index.rolling(short_window, min_periods=short_window).mean()
    long = index.rolling(long_window, min_periods=long_window).mean()
    ratio = short / long - 1
    regimes = []
    for value in ratio:
        if pd.isna(value):
            regimes.append("unknown")
        elif value > flat_band:
            regimes.append("up")
        elif value < -flat_band:
            regimes.append("down")
        else:
            regimes.append("flat")
    return pd.DataFrame({"date": index.index.astype(str), "regime": regimes})


def _ic(values: pd.DataFrame) -> float:
    if len(values) < 3:
        return 0.0
    corr = values["score"].corr(values["forward_5d_net_return"], method="spearman")
    return 0.0 if pd.isna(corr) else float(corr)


def _evaluate_slot(scored: pd.DataFrame, *, slot: str) -> dict[str, Any]:
    rows = scored.dropna(subset=["score", "forward_5d_net_return", "pool_return"]).copy()
    if rows.empty:
        return {
            "observations": 0,
            "mean_excess": 0.0,
            "hit_rate": 0.0,
            "ic": 0.0,
            "icir": 0.0,
            "regime": {},
            "_daily_ic": {},
        }
    rows["rank_pct"] = rows.groupby("date")["score"].rank(method="average", pct=True)
    if slot == "selection":
        picked = rows[rows["rank_pct"] >= 0.8].copy()
        picked["edge"] = picked["forward_5d_net_return"] - picked["pool_return"]
        picked["hit"] = picked["forward_5d_net_return"] > picked["pool_return"]
    elif slot == "risk_avoidance":
        picked = rows[rows["rank_pct"] <= 0.2].copy()
        picked["edge"] = picked["pool_return"] - picked["forward_5d_net_return"]
        picked["hit"] = picked["forward_5d_net_return"] < picked["pool_return"]
    else:
        raise ValueError(f"unsupported slot: {slot}")
    daily_ic = rows.groupby("date").apply(_ic, include_groups=False)
    ic_values = [float(v) for v in daily_ic if pd.notna(v)]
    ic = mean(ic_values) if ic_values else 0.0
    icir = ic / pstdev(ic_values) if len(ic_values) > 1 and pstdev(ic_values) > 0 else 0.0
    regime: dict[str, Any] = {}
    if "regime" in picked.columns:
        for name, grp in picked.groupby("regime"):
            regime[str(name)] = {
                "observations": int(len(grp)),
                "mean_excess": round(float(grp["edge"].mean()) if len(grp) else 0.0, 6),
                "hit_rate": round(float(grp["hit"].mean()) if len(grp) else 0.0, 6),
            }
    return {
        "observations": int(len(picked)),
        "mean_excess": round(float(picked["edge"].mean()) if len(picked) else 0.0, 6),
        "hit_rate": round(float(picked["hit"].mean()) if len(picked) else 0.0, 6),
        "ic": round(float(ic), 6),
        "icir": round(float(icir), 6),
        "regime": regime,
        "_daily_ic": {str(idx): round(float(value), 6) for idx, value in daily_ic.items() if pd.notna(value)},
    }


def evaluate_trials(panel: pd.DataFrame, trials: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    results: dict[str, list[dict[str, Any]]] = {"selection": [], "risk_avoidance": []}
    for trial in trials:
        if trial["kind"] == "weighted":
            scored = apply_weight_score(panel, trial["weights"])
        else:
            scored = apply_rule_score(panel, trial["name"])
        for slot in results:
            metrics = _evaluate_slot(scored, slot=slot)
            results[slot].append({"trial": trial, **metrics})
    for slot in results:
        results[slot].sort(key=lambda row: (row["mean_excess"], row["icir"], row["hit_rate"]), reverse=True)
    return results


def build_statistical_gate(results: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    gate: dict[str, Any] = {"trial_count": sum(len(rows) for rows in results.values())}
    for slot, rows in results.items():
        if not rows:
            gate[slot] = {"dsr": None, "dsr_reason": "no trials", "pbo": None, "pbo_reason": "no trials"}
            continue

        best = rows[0]
        trial_icirs = [float(row.get("icir", 0.0) or 0.0) for row in rows]
        daily_ic = best.get("_daily_ic") or {}
        if daily_ic:
            dsr = deflated_sharpe(
                [float(value) for _, value in sorted(daily_ic.items())],
                trial_icirs,
                sharpe_observed=float(best.get("icir", 0.0) or 0.0),
                n_trials=len(rows),
                periods_per_year=1,
            ).to_dict()
            dsr_reason = None
        else:
            dsr = None
            dsr_reason = "best trial has no daily IC observations"

        pbo_value: float | None = None
        pbo_reason: str | None = None
        pbo_details: dict[str, Any] | None = None
        common_dates = set(rows[0].get("_daily_ic") or {})
        for row in rows[1:]:
            common_dates &= set(row.get("_daily_ic") or {})
        if len(rows) < 2:
            pbo_reason = "at least 2 trials required"
        elif not common_dates:
            pbo_reason = "no aligned daily IC observations"
        else:
            matrix = [
                [float(row["_daily_ic"][day]) for row in rows]
                for day in sorted(common_dates)
            ]
            pbo_result = pbo(matrix)
            pbo_details = pbo_result.to_dict()
            if pbo_result.n_splits > 0 and not pbo_result.note:
                pbo_value = pbo_details["pbo"]
            else:
                pbo_reason = pbo_result.note or "no effective CSCV split"

        slot_gate = {
            "best_trial": best["trial"]["name"],
            "dsr": dsr,
            "pbo": pbo_value,
        }
        if dsr_reason:
            slot_gate["dsr_reason"] = dsr_reason
        if pbo_reason:
            slot_gate["pbo_reason"] = pbo_reason
        if pbo_details:
            slot_gate["pbo_details"] = pbo_details
        gate[slot] = slot_gate
    return gate


def _strip_internal_metrics(results: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        slot: [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
        for slot, rows in results.items()
    }


def _eligible_symbols(con: sqlite3.Connection, *, min_days: int, limit_symbols: int | None) -> list[str]:
    rows = con.execute(
        """
        SELECT symbol, COUNT(DISTINCT date) AS n
        FROM prices
        GROUP BY symbol
        HAVING n >= ?
        ORDER BY symbol
        """,
        (min_days,),
    ).fetchall()
    symbols = [str(row["symbol"]) for row in rows]
    return symbols[:limit_symbols] if limit_symbols else symbols


def _load_prices(con: sqlite3.Connection, symbols: list[str], *, start: str, end: str) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    placeholders = ",".join("?" for _ in symbols)
    rows = con.execute(
        f"""
        SELECT symbol, date, open, high, low, close, volume
        FROM prices
        WHERE symbol IN ({placeholders})
          AND date <= ?
        ORDER BY symbol, date
        """,
        [*symbols, end],
    ).fetchall()
    df = pd.DataFrame([dict(row) for row in rows])
    if df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Keep pre-start history for PIT factors, but evaluation later filters start.
    return df[df["date"] <= end].copy()


def build_report(
    *,
    db_path: Path,
    start: str,
    end: str | None,
    families: list[str],
    normalize: str,
    limit_symbols: int | None = None,
    include_holdout: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    effective_end = resolve_effective_end(end, include_holdout=include_holdout, today=today)
    if date.fromisoformat(effective_end) < date.fromisoformat(start):
        raise SystemExit(
            "requested window is fully inside the locked holdout period "
            f"(holdout locked to the most recent 1 year); available window upper bound: {effective_end}"
        )
    con = _connect_readonly(db_path)
    try:
        symbols = _eligible_symbols(con, min_days=1000, limit_symbols=limit_symbols)
        raw_prices = _load_prices(con, symbols, start=start, end=effective_end)
    finally:
        con.close()
    if raw_prices.empty:
        raise RuntimeError("no eligible price rows found for M58 grid backtest")

    scored = add_family_scores(raw_prices)
    with_forward = attach_forward_returns(scored)
    eval_panel = with_forward[(with_forward["date"] >= start) & (with_forward["date"] <= effective_end)].copy()
    eval_panel = eval_panel.dropna(subset=[*families, "forward_5d_net_return"])
    normalized = normalize_families(eval_panel, families, method=normalize)
    normalized["pool_return"] = normalized.groupby("date")["forward_5d_net_return"].transform("mean")
    regimes = regime_from_pool_equal_weight(eval_panel[["date", "symbol", "close"]])
    normalized = normalized.merge(regimes, on="date", how="left")

    weight_trials = enumerate_weight_grid(families)
    rule_trials = [{"name": name, "kind": "rule", "weights": {}} for name in RULE_GRID]
    trials = weight_trials + rule_trials
    results = evaluate_trials(normalized, trials)
    trial_count = len(trials) * len(results)
    statistical_gate = build_statistical_gate(results)
    return {
        "meta": {
            "spec": "M58 Phase 1",
            "start": start,
            "requested_end": end,
            "effective_end": effective_end,
            "holdout_locked": True,
            "families": families,
            "normalize": normalize,
            "eligible_symbol_count": len(symbols),
            "evaluated_symbol_count": int(normalized["symbol"].nunique()),
            "date_count": int(normalized["date"].nunique()),
            "statistical_gate": statistical_gate,
        },
        "trial_count": trial_count,
        "results": _strip_internal_metrics(results),
    }


def _write_outputs(report: dict[str, Any]) -> tuple[Path, Path]:
    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"m58_grid_smoke_{stamp}.json"
    md_path = OUTPUT_DIR / f"m58_grid_smoke_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# M58 Grid Smoke Report",
        "",
        f"- start: {report['meta']['start']}",
        f"- effective_end: {report['meta']['effective_end']}",
        f"- families: {','.join(report['meta']['families'])}",
        f"- normalize: {report['meta']['normalize']}",
        f"- trial_count: {report['trial_count']}",
        "",
        "## Statistical Gate",
        "",
        f"- trial_count: {report['meta']['statistical_gate']['trial_count']}",
    ]
    for slot, gate in report["meta"]["statistical_gate"].items():
        if slot == "trial_count":
            continue
        dsr = gate.get("dsr")
        lines.append(f"- {slot} best_trial: {gate.get('best_trial')}")
        if dsr:
            lines.append(
                f"  - DSR: {dsr['dsr']:.4f} "
                f"(p={dsr['p_value']:.4f}, threshold={dsr['sharpe_threshold']:.4f}, n={dsr['n_samples']})"
            )
        else:
            lines.append(f"  - DSR: null ({gate.get('dsr_reason')})")
        if gate.get("pbo") is None:
            lines.append(f"  - PBO: null ({gate.get('pbo_reason')})")
        else:
            lines.append(f"  - PBO: {gate['pbo']:.4f}")
    lines.append("")
    for slot, rows in report["results"].items():
        lines.extend([f"## {slot}", "", "| rank | trial | kind | mean_excess | hit_rate | ic | icir | observations |", "|---:|---|---|---:|---:|---:|---:|---:|"])
        for idx, row in enumerate(rows, 1):
            lines.append(
                f"| {idx} | {row['trial']['name']} | {row['trial']['kind']} | "
                f"{row['mean_excess']:.6f} | {row['hit_rate']:.6f} | {row['ic']:.6f} | "
                f"{row['icir']:.6f} | {row['observations']} |"
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M58 Phase 1 T/M grid backtest harness")
    parser.add_argument("--db-path", type=Path, default=default_sqlite_path())
    parser.add_argument("--start", required=True)
    parser.add_argument("--end")
    parser.add_argument("--families", default="T,M")
    parser.add_argument("--normalize", choices=("zscore", "rank"), default="zscore")
    parser.add_argument("--grid", action="store_true", help="enumerate the M58 Phase 1 grid")
    parser.add_argument("--limit-symbols", type=int)
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args(argv)

    families = [part.strip() for part in args.families.split(",") if part.strip()]
    report = build_report(
        db_path=args.db_path,
        start=args.start,
        end=args.end,
        families=families,
        normalize=args.normalize,
        limit_symbols=args.limit_symbols,
        include_holdout=args.include_holdout,
    )
    json_path, md_path = _write_outputs(report)
    summary = {
        "json": str(json_path),
        "md": str(md_path),
        "trial_count": report["trial_count"],
        "statistical_gate": report["meta"]["statistical_gate"],
        "selection_top": report["results"]["selection"][0] if report["results"]["selection"] else None,
        "risk_avoidance_top": report["results"]["risk_avoidance"][0] if report["results"]["risk_avoidance"] else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
