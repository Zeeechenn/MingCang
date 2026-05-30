"""Prepare M27.4 Kronos Path A fine-tuning data.

The tool builds an index-backed sliding-window dataset from the local
StockSage SQLite price table. It intentionally does not materialize every
400-bar tensor by default; instead it writes:

- train_data.pkl / valid_data.pkl: per-symbol OHLCV panels for Kronos loaders.
- windows.csv: every valid sliding window and its forward return label.
- coverage_report.json: explicit data coverage, warnings, and pass/fail status.

Usage:
    PYTHONPATH=. python3 -m backend.tools.m27_kronos_finetune_data
    PYTHONPATH=. python3 -m backend.tools.m27_kronos_finetune_data --output-dir ~/.stock-sage/kronos_m27
    PYTHONPATH=. python3 -m backend.tools.m27_kronos_finetune_data --write-complete-universe /private/tmp/reviewed_complete_symbols.json
"""
from __future__ import annotations

import argparse
import json
import pickle
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "stock-sage.db"
DEFAULT_OUTPUT_DIR = Path.home() / ".stock-sage" / "m27_kronos_finetune_data"

DEFAULT_CONTEXT = 400
DEFAULT_PRED_LEN = 5
DEFAULT_TRAIN_START = "2020-01-01"
DEFAULT_TRAIN_END = "2024-12-31"
DEFAULT_VALID_START = "2025-01-01"
DEFAULT_VALID_END = "2025-10-31"
DEFAULT_MIN_SYMBOLS = 707

PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class SplitWindow:
    split: str
    symbol: str
    context_start: str
    anchor_date: str
    label_end: str
    context_start_idx: int
    anchor_idx: int
    label_end_idx: int
    forward_return: float


def _shell_join(parts: list[str]) -> str:
    return " ".join(parts)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def parse_symbol_rows(payload: Any) -> list[str]:
    rows = payload.get("stocks", payload) if isinstance(payload, dict) else payload
    symbols: list[str] = []
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else row
        if symbol:
            symbols.append(str(symbol).zfill(6))
    return sorted(dict.fromkeys(symbols))


def load_symbols(db_path: Path, universe_path: Path | None = None, symbols: list[str] | None = None) -> list[str]:
    if symbols:
        return sorted(dict.fromkeys(str(s).zfill(6) for s in symbols))
    if universe_path is not None:
        return parse_symbol_rows(json.loads(universe_path.read_text(encoding="utf-8")))

    con = _connect_readonly(db_path)
    try:
        rows = con.execute(
            """
            SELECT symbol
            FROM stocks
            WHERE market = 'CN' OR market IS NULL
            ORDER BY symbol
            """
        ).fetchall()
    finally:
        con.close()
    return [str(row[0]).zfill(6) for row in rows]


def load_price_panels(db_path: Path, symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}

    con = _connect_readonly(db_path)
    try:
        placeholders = ",".join("?" * len(symbols))
        df = pd.read_sql_query(
            f"""
            SELECT symbol, date, open, high, low, close, volume
            FROM prices
            WHERE symbol IN ({placeholders})
              AND date >= ?
              AND date <= ?
            ORDER BY symbol, date
            """,
            con,
            params=[*symbols, start, end],
        )
    finally:
        con.close()

    panels: dict[str, pd.DataFrame] = {}
    if df.empty:
        return panels

    for symbol, group in df.groupby("symbol"):
        panel = group.copy()
        panel["datetime"] = pd.to_datetime(panel["date"])
        panel = panel.sort_values("datetime").drop_duplicates("datetime", keep="last")
        for col in PRICE_COLUMNS:
            panel[col] = pd.to_numeric(panel[col], errors="coerce")
        panel = panel.dropna(subset=["open", "high", "low", "close"])
        panel = panel[panel["close"] > 0]
        panel["volume"] = panel["volume"].fillna(0.0)
        panel = panel.set_index("datetime")[PRICE_COLUMNS]
        panels[str(symbol).zfill(6)] = panel
    return panels


def kronos_panel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns={"volume": "vol"}).copy()
    out["amt"] = out["close"] * out["vol"]
    out.index.name = "datetime"
    return out[["open", "high", "low", "close", "vol", "amt"]].astype("float32")


def build_windows_for_symbol(
    symbol: str,
    df: pd.DataFrame,
    *,
    split: str,
    split_start: str,
    split_end: str,
    context: int,
    pred_len: int,
) -> list[SplitWindow]:
    if len(df) < context + pred_len:
        return []

    dates = pd.DatetimeIndex(df.index)
    split_start_ts = pd.Timestamp(split_start)
    split_end_ts = pd.Timestamp(split_end)
    windows: list[SplitWindow] = []

    for anchor_idx in range(context - 1, len(df) - pred_len):
        anchor = dates[anchor_idx]
        label_end = dates[anchor_idx + pred_len]
        if anchor < split_start_ts or label_end > split_end_ts:
            continue

        close_now = float(df["close"].iloc[anchor_idx])
        close_future = float(df["close"].iloc[anchor_idx + pred_len])
        if close_now <= 0 or pd.isna(close_future):
            continue

        context_start_idx = anchor_idx - context + 1
        windows.append(
            SplitWindow(
                split=split,
                symbol=symbol,
                context_start=dates[context_start_idx].strftime("%Y-%m-%d"),
                anchor_date=anchor.strftime("%Y-%m-%d"),
                label_end=label_end.strftime("%Y-%m-%d"),
                context_start_idx=context_start_idx,
                anchor_idx=anchor_idx,
                label_end_idx=anchor_idx + pred_len,
                forward_return=close_future / close_now - 1.0,
            )
        )
    return windows


def build_windows(
    panels: dict[str, pd.DataFrame],
    *,
    context: int,
    pred_len: int,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    per_symbol: dict[str, dict[str, Any]] = {}

    for symbol, df in sorted(panels.items()):
        train_windows = build_windows_for_symbol(
            symbol,
            df,
            split="train",
            split_start=train_start,
            split_end=train_end,
            context=context,
            pred_len=pred_len,
        )
        valid_windows = build_windows_for_symbol(
            symbol,
            df,
            split="valid",
            split_start=valid_start,
            split_end=valid_end,
            context=context,
            pred_len=pred_len,
        )
        rows.extend(asdict(w) for w in [*train_windows, *valid_windows])
        per_symbol[symbol] = {
            "bars": int(len(df)),
            "first_date": df.index.min().strftime("%Y-%m-%d") if not df.empty else None,
            "last_date": df.index.max().strftime("%Y-%m-%d") if not df.empty else None,
            "train_windows": len(train_windows),
            "valid_windows": len(valid_windows),
            "status": "ok" if train_windows and valid_windows else "insufficient_split_windows",
        }

    return pd.DataFrame(rows), per_symbol


def build_coverage_report(
    *,
    requested_symbols: list[str],
    panels: dict[str, pd.DataFrame],
    per_symbol: dict[str, dict[str, Any]],
    windows: pd.DataFrame,
    min_symbols: int,
    context: int,
    pred_len: int,
    train_start: str,
    train_end: str,
    valid_start: str,
    valid_end: str,
    allow_partial: bool,
) -> dict[str, Any]:
    missing_symbols = [s for s in requested_symbols if s not in panels]
    complete_symbols = [
        s
        for s, info in per_symbol.items()
        if info.get("train_windows", 0) > 0 and info.get("valid_windows", 0) > 0
    ]
    incomplete_symbols = [
        {"symbol": s, **info}
        for s, info in per_symbol.items()
        if s not in complete_symbols
    ]
    incomplete_symbol_codes = [str(row["symbol"]) for row in incomplete_symbols]

    train_windows = int((windows["split"] == "train").sum()) if not windows.empty else 0
    valid_windows = int((windows["split"] == "valid").sum()) if not windows.empty else 0
    hard_failures: list[str] = []
    if len(requested_symbols) < min_symbols:
        hard_failures.append(f"requested_symbols {len(requested_symbols)} < min_symbols {min_symbols}")
    if len(complete_symbols) < min_symbols:
        hard_failures.append(f"complete_symbols {len(complete_symbols)} < min_symbols {min_symbols}")
    if missing_symbols:
        hard_failures.append(f"missing price data for {len(missing_symbols)} symbols")
    if train_windows == 0 or valid_windows == 0:
        hard_failures.append("no train or validation windows generated")
    if incomplete_symbols:
        hard_failures.append(f"{len(incomplete_symbols)} symbols lack train or validation windows")

    passed = not hard_failures or allow_partial
    fixed_universe_command = _shell_join(
        [
            "PYTHONPATH=.",
            "python3",
            "-m",
            "backend.tools.m27_kronos_finetune_data",
            "--universe-path",
            "<reviewed_complete_symbols.json>",
            "--min-symbols",
            str(len(complete_symbols)),
            "--output-dir",
            "<new_kronos_data_dir>",
        ]
    )
    allow_partial_command = _shell_join(
        [
            "PYTHONPATH=.",
            "python3",
            "-m",
            "backend.tools.m27_kronos_finetune_data",
            "--min-symbols",
            str(min_symbols),
            "--allow-partial",
            "--output-dir",
            "<exploratory_kronos_data_dir>",
        ]
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "context": context,
        "pred_len": pred_len,
        "splits": {
            "train": {"start": train_start, "end": train_end, "windows": train_windows},
            "valid": {"start": valid_start, "end": valid_end, "windows": valid_windows},
        },
        "requested_symbols": len(requested_symbols),
        "symbols_with_price_data": len(panels),
        "complete_symbols": len(complete_symbols),
        "min_symbols": min_symbols,
        "allow_partial": allow_partial,
        "passed": passed,
        "hard_failures": hard_failures,
        "symbol_summary": {
            "complete_symbols": len(complete_symbols),
            "incomplete_symbols": len(incomplete_symbols),
            "missing_symbols": len(missing_symbols),
            "complete_symbol_sample": complete_symbols[:20],
            "incomplete_symbol_sample": incomplete_symbol_codes[:20],
        },
        "symbol_lists": {
            "complete": complete_symbols,
            "incomplete": incomplete_symbol_codes,
            "missing": missing_symbols,
        },
        "recommended_next_steps": {
            "preferred": (
                "proceed"
                if not hard_failures
                else ("fixed_universe" if complete_symbols else "repair_data")
            ),
            "fixed_universe": {
                "symbol_count": len(complete_symbols),
                "command": fixed_universe_command,
                "note": (
                    "Write symbol_lists.complete to a reviewed universe JSON before training; "
                    "this keeps train/valid coverage explicit and reproducible."
                ),
            },
            "allow_partial": {
                "symbol_count": len(complete_symbols),
                "command": allow_partial_command,
                "note": (
                    "Use only for exploratory data generation; do not treat partial coverage "
                    "as final fine-tuning evidence without an explicit review decision."
                ),
            },
        },
        "missing_symbols": missing_symbols[:50],
        "missing_symbols_truncated": len(missing_symbols) > 50,
        "incomplete_symbols": incomplete_symbols[:50],
        "incomplete_symbols_truncated": len(incomplete_symbols) > 50,
    }


def write_outputs(
    output_dir: Path,
    panels: dict[str, pd.DataFrame],
    windows: pd.DataFrame,
    report: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    def _split_panels(split: str) -> dict[str, pd.DataFrame]:
        if windows.empty:
            return {}
        split_windows = windows[windows["split"] == split]
        data: dict[str, pd.DataFrame] = {}
        for symbol, group in split_windows.groupby("symbol"):
            start = pd.to_datetime(group["context_start"]).min()
            end = pd.to_datetime(group["label_end"]).max()
            panel = panels[str(symbol)].loc[start:end]
            if not panel.empty:
                data[str(symbol)] = kronos_panel(panel)
        return data

    train_data = _split_panels("train")
    valid_data = _split_panels("valid")

    with (output_dir / "train_data.pkl").open("wb") as fh:
        pickle.dump(train_data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    with (output_dir / "valid_data.pkl").open("wb") as fh:
        pickle.dump(valid_data, fh, protocol=pickle.HIGHEST_PROTOCOL)
    windows.to_csv(output_dir / "windows.csv", index=False)
    (output_dir / "coverage_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_complete_universe(
    report: dict[str, Any],
    *,
    coverage_report_path: Path | None = None,
) -> dict[str, Any]:
    complete_symbols = [str(symbol).zfill(6) for symbol in report["symbol_lists"]["complete"]]
    incomplete_symbols = [str(symbol).zfill(6) for symbol in report["symbol_lists"]["incomplete"]]
    missing_symbols = [str(symbol).zfill(6) for symbol in report["symbol_lists"]["missing"]]
    excluded_count = len(incomplete_symbols) + len(missing_symbols)

    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "purpose": "M27.4 reviewed complete universe for Kronos Path A data generation",
            "source": "backend.tools.m27_kronos_finetune_data coverage_report.symbol_lists.complete",
            "coverage_report_path": str(coverage_report_path.expanduser()) if coverage_report_path else None,
            "context": report["context"],
            "pred_len": report["pred_len"],
            "splits": report["splits"],
            "requested_symbols": report["requested_symbols"],
            "symbol_count": len(complete_symbols),
            "excluded_symbol_count": excluded_count,
            "coverage_passed": report["passed"],
            "hard_failures": report["hard_failures"],
        },
        "stocks": [{"symbol": symbol} for symbol in complete_symbols],
        "excluded": {
            "summary": {
                "incomplete_symbols": len(incomplete_symbols),
                "missing_symbols": len(missing_symbols),
                "total": excluded_count,
            },
            "incomplete_symbols": incomplete_symbols,
            "missing_symbols": missing_symbols,
            "incomplete_detail_sample": report["incomplete_symbols"],
            "incomplete_detail_truncated": report["incomplete_symbols_truncated"],
        },
    }


def write_complete_universe(
    path: Path,
    report: dict[str, Any],
    *,
    coverage_report_path: Path | None = None,
) -> dict[str, Any]:
    universe = build_complete_universe(report, coverage_report_path=coverage_report_path)
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(universe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return universe


def run(args: argparse.Namespace) -> dict[str, Any]:
    symbols = load_symbols(args.db_path, args.universe_path, args.symbols)
    start_for_load = min(args.train_start, args.valid_start)
    end_for_load = max(args.train_end, args.valid_end)
    panels = load_price_panels(args.db_path, symbols, start_for_load, end_for_load)
    windows, per_symbol = build_windows(
        panels,
        context=args.context,
        pred_len=args.pred_len,
        train_start=args.train_start,
        train_end=args.train_end,
        valid_start=args.valid_start,
        valid_end=args.valid_end,
    )
    report = build_coverage_report(
        requested_symbols=symbols,
        panels=panels,
        per_symbol=per_symbol,
        windows=windows,
        min_symbols=args.min_symbols,
        context=args.context,
        pred_len=args.pred_len,
        train_start=args.train_start,
        train_end=args.train_end,
        valid_start=args.valid_start,
        valid_end=args.valid_end,
        allow_partial=args.allow_partial,
    )
    write_outputs(args.output_dir, panels, windows, report)
    if args.write_complete_universe:
        write_complete_universe(
            args.write_complete_universe,
            report,
            coverage_report_path=args.output_dir / "coverage_report.json",
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--universe-path", type=Path, default=None)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--write-complete-universe",
        type=Path,
        default=None,
        help="Write a reviewed universe JSON from coverage_report.symbol_lists.complete for later --universe-path use.",
    )
    parser.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
    parser.add_argument("--pred-len", type=int, default=DEFAULT_PRED_LEN)
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--valid-start", default=DEFAULT_VALID_START)
    parser.add_argument("--valid-end", default=DEFAULT_VALID_END)
    parser.add_argument("--min-symbols", type=int, default=DEFAULT_MIN_SYMBOLS)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    print(f"wrote {args.output_dir / 'coverage_report.json'}")
    if args.write_complete_universe:
        print(f"wrote reviewed complete universe {args.write_complete_universe}")
    print(
        "coverage: "
        f"requested={report['requested_symbols']} "
        f"complete={report['complete_symbols']} "
        f"train_windows={report['splits']['train']['windows']} "
        f"valid_windows={report['splits']['valid']['windows']} "
        f"passed={report['passed']}"
    )
    if not report["passed"]:
        print("coverage failures:")
        for failure in report["hard_failures"]:
            print(f"- {failure}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
