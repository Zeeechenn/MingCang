"""M43.2 single-factor IC diagnostics, sealed to OOS 2021-2024.

Run one factor:
    python3 m43_2_amihud_ic.py --factor amihud_20 --db-path ~/.stock-sage/m43_work.db

Run the full M43.2 factor set:
    python3 m43_2_amihud_ic.py --factor all --db-path ~/.stock-sage/m43_work.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEALED_END_DATE = pd.Timestamp("2024-12-31")
DEFAULT_START_DATE = "2021-01-01"
DEFAULT_END_DATE = "2024-12-31"
DEFAULT_DB_PATH = Path.home() / ".stock-sage" / "m43_work.db"
DEFAULT_HFQ_EXCLUDE = "600519,600601,600602"
LABEL_COL = "label_5d"
T_CRIT_BONFERRONI = 2.50

FACTOR_ORDER = [
    "amihud_20",
    "sector_rel_strength_20_z",
    "rev_mom_12_1_z",
]

FACTOR_SPECS: dict[str, dict[str, Any]] = {
    "amihud_20": {
        "description": "20-day Amihud illiquidity; higher values should predict lower returns.",
        "expected_direction": "negative",
        "expected_spread_sign": -1,
    },
    "sector_rel_strength_20_z": {
        "description": "20-day same-industry relative strength z-score.",
        "expected_direction": "positive",
        "expected_spread_sign": 1,
    },
    "rev_mom_12_1_z": {
        "description": "12-1 reversal z-score; higher values are stronger reversal candidates.",
        "expected_direction": "positive",
        "expected_spread_sign": 1,
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce M43.2 single-factor IC diagnostics on a local SQLite DB. "
            "Default OOS is 2021-2024; 2025 is sealed."
        )
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Existing SQLite DB containing stocks and prices tables.",
    )
    parser.add_argument(
        "--factor",
        choices=[*FACTOR_ORDER, "all"],
        default="amihud_20",
        help="Factor to reproduce. Use 'all' for the full M43.2 set.",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help="OOS start date, inclusive. Default: 2021-01-01.",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help="OOS end date, inclusive. Default keeps sealed 2025 untouched.",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=5,
        help="Date stride used to reduce overlapping labels. Default: 5.",
    )
    parser.add_argument(
        "--min-names",
        type=int,
        default=5,
        help="Minimum names per date for cross-sectional IC. Default: 5.",
    )
    parser.add_argument(
        "--hfq-exclude",
        default=DEFAULT_HFQ_EXCLUDE,
        help="Comma-separated symbols excluded for hfq-scaled price series.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the summary JSON.",
    )
    return parser


def parse_date(value: str, *, label: str, parser: argparse.ArgumentParser) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except ValueError:
        parser.error(f"{label} must be a valid date: {value}")
    if pd.isna(parsed):
        parser.error(f"{label} must be a valid date: {value}")
    return parsed.normalize()


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    start_date = parse_date(args.start_date, label="--start-date", parser=parser)
    end_date = parse_date(args.end_date, label="--end-date", parser=parser)
    if end_date > SEALED_END_DATE:
        parser.error("--end-date must be <= 2024-12-31 so sealed 2025 remains untouched")
    if start_date > end_date:
        parser.error("--start-date must be <= --end-date")
    if args.stride <= 0:
        parser.error("--stride must be > 0")
    if args.min_names < 3:
        parser.error("--min-names must be >= 3")

    db_path = Path(args.db_path).expanduser().resolve()
    if not db_path.exists():
        parser.error(f"--db-path does not exist: {db_path}")
    if not db_path.is_file():
        parser.error(f"--db-path is not a file: {db_path}")


def selected_factors(factor_arg: str) -> list[str]:
    if factor_arg == "all":
        return list(FACTOR_ORDER)
    return [factor_arg]


def parse_hfq_exclude(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def rolling_zscore(
    series: pd.Series,
    window: int = 60,
    *,
    min_periods: int | None = None,
) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    min_periods = min_periods or max(5, window // 3)
    mean = values.rolling(window, min_periods=min_periods).mean()
    std = values.rolling(window, min_periods=min_periods).std()
    z = (values - mean) / std.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _read_sqlite_panel(db_path: Path, end_date: pd.Timestamp, *, verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print("Loading prices from work DB ...", flush=True)
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        stocks_df = pd.read_sql("SELECT symbol, industry FROM stocks", conn)
        prices_df = pd.read_sql(
            "SELECT symbol, date, open, high, low, close, volume FROM prices WHERE date <= ?",
            conn,
            params=(end_date.strftime("%Y-%m-%d"),),
        )

    if verbose:
        print(f"  Stocks in DB: {len(stocks_df)}")
        print(f"  Price rows loaded: {len(prices_df)}")

    prices_df["date"] = pd.to_datetime(prices_df["date"], errors="coerce")
    prices_df["close"] = pd.to_numeric(prices_df["close"], errors="coerce")
    prices_df["volume"] = pd.to_numeric(prices_df["volume"], errors="coerce").fillna(0.0)
    prices_df = prices_df.dropna(subset=["symbol", "date", "close"]).copy()
    stocks_df["industry"] = stocks_df["industry"].fillna("UNKNOWN")
    return prices_df.merge(stocks_df[["symbol", "industry"]], on="symbol", how="left")


def apply_price_exclusions(
    prices_df: pd.DataFrame,
    hfq_exclude: set[str],
    *,
    verbose: bool = True,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    out = prices_df[~prices_df["symbol"].isin(hfq_exclude)].copy()
    if verbose:
        print(f"  After explicit hfq exclusion: {len(out)}")

    max_close = out.groupby("symbol")["close"].max()
    exclude_high_close = set(max_close[max_close > 10000].index)
    if exclude_high_close:
        out = out[~out["symbol"].isin(exclude_high_close)].copy()
        if verbose:
            print(f"  Excluding additional max-close>10000 symbols: {sorted(exclude_high_close)}")

    if verbose:
        print(f"  After all exclusions: {len(out)}")
    return out, {
        "explicit_hfq_exclude": sorted(hfq_exclude),
        "max_close_gt_10000_exclude": sorted(exclude_high_close),
    }


def add_m43_2_factors(prices_df: pd.DataFrame) -> pd.DataFrame:
    out = prices_df.sort_values(["symbol", "date"]).reset_index(drop=True).copy()
    close = out.groupby("symbol", sort=False)["close"]

    out["ret_1d"] = close.pct_change()
    traded_value = out["volume"] * out["close"]
    out["_amihud_raw"] = out["ret_1d"].abs() / (traded_value + 1e-9)
    out["amihud_20"] = out.groupby("symbol", sort=False)["_amihud_raw"].transform(
        lambda s: s.rolling(20).mean()
    )

    out["mom_20"] = close.pct_change(20)
    close_shift_21 = close.shift(21)
    long_12_1 = close_shift_21 / close.shift(252) - 1
    shorter_fallback = close_shift_21 / close.shift(60) - 1
    out["rev_mom_12_1_uses_60d_fallback"] = long_12_1.isna() & shorter_fallback.notna()
    out["rev_mom_12_1"] = -long_12_1.combine_first(shorter_fallback)
    out["rev_mom_12_1_z"] = out.groupby("symbol", sort=False)["rev_mom_12_1"].transform(
        lambda s: rolling_zscore(s, window=120)
    )

    industry = out["industry"].fillna("UNKNOWN")
    peer_mean = out.assign(_industry=industry).groupby(["date", "_industry"])["mom_20"].transform("mean")
    out["sector_rel_strength_20"] = out["mom_20"] - peer_mean
    out["sector_rel_strength_20_z"] = out.groupby(
        "symbol",
        sort=False,
    )["sector_rel_strength_20"].transform(lambda s: rolling_zscore(s, window=60))

    out[LABEL_COL] = close.transform(lambda s: (s.shift(-5) / s - 1).clip(-0.30, 0.30))
    return out.drop(columns=["_amihud_raw"]).sort_values(["date", "symbol"]).reset_index(drop=True)


def restrict_oos(
    panel: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    *,
    verbose: bool = True,
) -> pd.DataFrame:
    mask = (panel["date"] >= start_date) & (panel["date"] <= end_date)
    out = panel[mask].copy()
    if verbose:
        print(f"  OOS rows: {len(out)}")
        print(f"  OOS symbols: {out['symbol'].nunique() if not out.empty else 0}")
        if out.empty:
            print("  OOS date range: <empty>")
        else:
            print(f"  OOS date range: {out['date'].min().date()} .. {out['date'].max().date()}")
    return out


def stride_predictions(df: pd.DataFrame, stride: int = 5) -> pd.DataFrame:
    if stride <= 1 or df.empty:
        return df.copy()
    dates = pd.Series(pd.to_datetime(df["date"]).drop_duplicates().sort_values().values)
    keep_dates = set(dates.iloc[::stride])
    return df[pd.to_datetime(df["date"]).isin(keep_dates)].copy()


def _safe_spearman(left: pd.Series, right: pd.Series) -> float | None:
    data = pd.DataFrame({"left": left, "right": right}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(data) < 3 or data["left"].nunique() < 2 or data["right"].nunique() < 2:
        return None
    corr = data["left"].rank(method="average").corr(data["right"].rank(method="average"))
    if corr is None or not np.isfinite(corr):
        return None
    return float(corr)


def cross_sectional_ic(
    frame: pd.DataFrame,
    factor_col: str,
    label_col: str,
    *,
    min_names: int = 5,
) -> pd.Series:
    rows: list[tuple[pd.Timestamp, float]] = []
    for date, group in frame.groupby("date", sort=True):
        data = group[[factor_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < min_names:
            continue
        corr = _safe_spearman(data[factor_col], data[label_col])
        if corr is not None:
            rows.append((pd.to_datetime(date), corr))
    return pd.Series(dict(rows), name="ic", dtype="float64")


def summarize_ic(ic: pd.Series) -> dict[str, Any]:
    if ic.empty:
        return {"ic_days": 0, "ic_mean": None, "ic_std": None, "icir": None, "ic_positive_rate": None}
    mean = float(ic.mean())
    std_raw = ic.std()
    std = float(std_raw) if std_raw is not None and np.isfinite(std_raw) else None
    return {
        "ic_days": int(len(ic)),
        "ic_mean": round(mean, 6),
        "ic_std": round(std, 6) if std is not None else None,
        "icir": round(mean / std if std is not None and std > 0 else 0.0, 6),
        "ic_positive_rate": round(float((ic > 0).mean()), 6),
    }


def quintile_spread(
    frame: pd.DataFrame,
    factor_col: str,
    label_col: str,
    *,
    min_names: int = 5,
) -> dict[str, Any]:
    rows: list[tuple[pd.Timestamp, int, float]] = []
    for date, group in frame.groupby("date", sort=True):
        data = group[[factor_col, label_col]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < min_names or data[factor_col].nunique() < 2:
            continue
        data = data.copy()
        try:
            data["q"] = pd.qcut(data[factor_col], q=5, labels=False, duplicates="drop")
        except ValueError:
            continue
        q_means = data.groupby("q")[label_col].mean().sort_index()
        if len(q_means) < 2:
            continue
        rows.extend((pd.Timestamp(date), int(q), float(value)) for q, value in q_means.items())

    if not rows:
        return {
            "quintile_means": None,
            "top_minus_bottom": None,
            "monotonic_increasing": None,
            "monotonic_decreasing": None,
            "monotonic_expected_direction": None,
            "n_quintile_dates": 0,
        }

    q_frame = pd.DataFrame(rows, columns=["date", "q", label_col])
    q_means = q_frame.groupby("q")[label_col].mean().sort_index()
    means = [float(value) for value in q_means.values]
    top_minus_bottom = float(q_means.iloc[-1] - q_means.iloc[0])
    monotonic_increasing = all(means[i] <= means[i + 1] for i in range(len(means) - 1))
    monotonic_decreasing = all(means[i] >= means[i + 1] for i in range(len(means) - 1))
    return {
        "quintile_means": [round(value, 6) for value in means],
        "top_minus_bottom": round(top_minus_bottom, 6),
        "monotonic_increasing": bool(monotonic_increasing),
        "monotonic_decreasing": bool(monotonic_decreasing),
        "monotonic_expected_direction": None,
        "n_quintile_dates": int(q_frame["date"].nunique()),
    }


def apply_expected_direction(q_result: dict[str, Any], expected_spread_sign: int) -> dict[str, Any]:
    out = dict(q_result)
    spread = out.get("top_minus_bottom")
    if spread is None:
        out["monotonic_expected_direction"] = False
    elif expected_spread_sign > 0:
        out["monotonic_expected_direction"] = bool(out.get("monotonic_increasing") and spread > 0)
    else:
        out["monotonic_expected_direction"] = bool(out.get("monotonic_decreasing") and spread < 0)
    return out


def factor_verdict(summary: dict[str, Any], t_stat: float | None, q_result: dict[str, Any]) -> str:
    if summary["ic_mean"] is None or summary["icir"] is None or t_stat is None:
        return "REJECT"
    stat_gates_pass = (
        abs(t_stat) > T_CRIT_BONFERRONI
        and abs(float(summary["ic_mean"])) > 0.02
        and abs(float(summary["icir"])) > 0.15
    )
    if stat_gates_pass and q_result.get("monotonic_expected_direction"):
        return "PROMOTE"
    if stat_gates_pass:
        return "INCONCLUSIVE"
    return "REJECT"


def analyze_factor(strided: pd.DataFrame, factor: str, *, min_names: int = 5) -> dict[str, Any]:
    spec = FACTOR_SPECS[factor]
    ic_series = cross_sectional_ic(strided, factor, LABEL_COL, min_names=min_names)
    summary = summarize_ic(ic_series)
    t_stat = None
    if summary["icir"] is not None and summary["ic_days"]:
        t_stat = float(summary["icir"]) * float(np.sqrt(int(summary["ic_days"])))

    q_result = quintile_spread(strided, factor, LABEL_COL, min_names=min_names)
    q_result = apply_expected_direction(q_result, int(spec["expected_spread_sign"]))
    verdict = factor_verdict(summary, t_stat, q_result)
    rounded_t = round(t_stat, 6) if t_stat is not None else None
    return {
        "factor": factor,
        "description": spec["description"],
        "expected_direction": spec["expected_direction"],
        "ic_summary": summary,
        "summary": summary,
        "t_stat": rounded_t,
        "ic_tstat": rounded_t,
        "quintile_spread": q_result,
        "quintile": q_result,
        "verdict": verdict,
    }


def run_analysis(
    db_path: Path,
    factors: list[str],
    *,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    stride: int,
    hfq_exclude: set[str],
    min_names: int = 5,
    verbose: bool = True,
) -> dict[str, Any]:
    prices_df = _read_sqlite_panel(db_path, end_date, verbose=verbose)
    prices_df, exclusions = apply_price_exclusions(prices_df, hfq_exclude, verbose=verbose)

    if verbose:
        print("Computing M43.2 factors ...", flush=True)
    panel = add_m43_2_factors(prices_df)
    if verbose:
        null_counts = {factor: int(panel[factor].isna().sum()) for factor in FACTOR_ORDER}
        print(f"  Factor null counts: {null_counts}")
        print(f"  Panel shape: {panel.shape}")

    oos = restrict_oos(panel, start_date, end_date, verbose=verbose)
    if verbose:
        print(f"Applying stride={stride} ...", flush=True)
    strided = stride_predictions(oos, stride=stride)
    if verbose:
        print(f"  Strided rows: {len(strided)}")
        print(f"  Strided dates: {strided['date'].nunique() if not strided.empty else 0}")

    fallback_rows = 0
    fallback_rate = None
    fallback_col = "rev_mom_12_1_uses_60d_fallback"
    if fallback_col in strided.columns and not strided.empty:
        fallback_rows = int(strided[fallback_col].fillna(False).sum())
        fallback_rate = round(fallback_rows / len(strided), 6)

    results = {factor: analyze_factor(strided, factor, min_names=min_names) for factor in factors}
    return {
        "metadata": {
            "db_path": str(db_path),
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "sealed_2025_guard": True,
            "stride": stride,
            "min_names": min_names,
            "hfq_exclusion": exclusions,
            "requested_factors": factors,
            "all_supported_factors": list(FACTOR_ORDER),
            "factor_notes": {
                "rev_mom_12_1_z": {
                    "definition": "Matches M27: negative 12-1 momentum with a 60-day fallback before 252-day lookback is available.",
                    "fallback_60d_rows": fallback_rows,
                    "fallback_60d_rate": fallback_rate,
                },
            },
        },
        "results": results,
    }


def print_report(report: dict[str, Any]) -> None:
    meta = report["metadata"]
    print("\n=== M43.2 single-factor reproduction ===")
    print(f"  OOS        : {meta['start_date']} .. {meta['end_date']}")
    print(f"  stride     : {meta['stride']}")
    print(f"  min_names  : {meta['min_names']}")
    print(f"  factors    : {', '.join(meta['requested_factors'])}")

    for factor, result in report["results"].items():
        summary = result["ic_summary"]
        q_result = result["quintile_spread"]
        print(f"\n--- {factor} ---")
        print(f"  expected_direction      : {result['expected_direction']}")
        print(f"  ic_days                 : {summary['ic_days']}")
        print(f"  ic_mean                 : {summary['ic_mean']}")
        print(f"  ic_std                  : {summary['ic_std']}")
        print(f"  icir                    : {summary['icir']}")
        print(f"  t_stat                  : {result['t_stat']}")
        print(f"  quintile_means (Q1..Q5) : {q_result['quintile_means']}")
        print(f"  top_minus_bottom        : {q_result['top_minus_bottom']}")
        print(f"  monotonic_expected      : {q_result['monotonic_expected_direction']}")
        print(f"  Bonferroni verdict      : {result['verdict']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args, parser)

    warnings.filterwarnings("ignore")
    db_path = Path(args.db_path).expanduser().resolve()
    start_date = pd.Timestamp(args.start_date).normalize()
    end_date = pd.Timestamp(args.end_date).normalize()
    factors = selected_factors(args.factor)
    report = run_analysis(
        db_path,
        factors,
        start_date=start_date,
        end_date=end_date,
        stride=args.stride,
        hfq_exclude=parse_hfq_exclude(args.hfq_exclude),
        min_names=args.min_names,
        verbose=True,
    )
    print_report(report)

    if args.output_json:
        output_path = Path(args.output_json).expanduser().resolve()
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nWrote summary JSON: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
