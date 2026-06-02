# ruff: noqa: S608
"""Read-only readiness guard for the next M29.3 forward-shadow run.

This tool decides whether the local price data has enough complete future
coverage to run the existing M27 top-decile forward-shadow commands as M29
fresh evidence. It does not run the shadow, write the DB, call LLM/API
services, save/train models, or change production configuration.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.tools import m29_evidence_ledger
from backend.tools.m27_alpha_diagnostic import _load_universe_symbols
from backend.tools.m27_test3_production_profile_ab import DEFAULT_UNIVERSE_PATH

DEFAULT_JSON_OUTPUT = Path("/private/tmp/m29_forward_readiness.json")
DEFAULT_MARKDOWN_OUTPUT = Path("/private/tmp/m29_forward_readiness.md")
EXIT_DAYS = (1, 3, 5)


def _sqlite_path_from_url(db_url: str) -> Path:
    if db_url.startswith("sqlite:////"):
        return Path("/" + db_url.removeprefix("sqlite:////"))
    if db_url.startswith("sqlite:///"):
        return Path(db_url.removeprefix("sqlite:///"))
    if db_url.startswith("sqlite://"):
        raise ValueError(f"unsupported sqlite URL: {db_url}")
    return Path(db_url)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_end_key(value: str | None) -> str:
    return value or ""


def latest_forward_artifacts(paths: list[Path]) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    for path in paths:
        payload = _load_json(path)
        if not payload or payload.get("run_mode") != "offline_read_only_forward_shadow_rolling":
            continue
        exit_days = payload.get("exit_days")
        if exit_days not in EXIT_DAYS:
            continue
        entry = {
            "path": str(path.expanduser()),
            "start": payload.get("start"),
            "end": payload.get("end"),
            "exit_days": exit_days,
            "run_mode": payload.get("run_mode"),
            "production_unchanged": payload.get("production_unchanged"),
        }
        current = latest.get(exit_days)
        if current is None or _artifact_end_key(entry["end"]) > _artifact_end_key(current.get("end")):
            latest[int(exit_days)] = entry
    return latest


def _readonly_connect(db_url: str) -> sqlite3.Connection:
    path = _sqlite_path_from_url(db_url).expanduser()
    uri = f"file:{path}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def _price_coverage(db_url: str, universe_symbols: set[str], min_complete_symbols: int) -> dict[str, Any]:
    if not universe_symbols:
        return {
            "mode": "sqlite_readonly",
            "latest_price_date": None,
            "latest_complete_price_date": None,
            "unique_trading_dates": 0,
            "complete_trading_dates": 0,
            "complete_dates": [],
            "coverage_tail": [],
            "error": "empty_universe",
        }

    placeholders = ",".join("?" for _ in universe_symbols)
    query = f"""
        SELECT
          date,
          COUNT(DISTINCT symbol) AS symbol_count,
          COUNT(DISTINCT CASE WHEN source IS NOT NULL AND source != '' THEN symbol END) AS symbols_with_source,
          COUNT(DISTINCT CASE WHEN fetched_at IS NOT NULL AND fetched_at != '' THEN symbol END)
            AS symbols_with_fetched_at,
          COUNT(DISTINCT CASE WHEN adjustment IS NOT NULL AND adjustment != '' THEN symbol END)
            AS symbols_with_adjustment
        FROM prices
        WHERE symbol IN ({placeholders})
        GROUP BY date
        ORDER BY date ASC
    """
    try:
        with _readonly_connect(db_url) as conn:
            rows = conn.execute(query, sorted(universe_symbols)).fetchall()
    except Exception as exc:
        return {
            "mode": "sqlite_readonly",
            "latest_price_date": None,
            "latest_complete_price_date": None,
            "unique_trading_dates": 0,
            "complete_trading_dates": 0,
            "complete_dates": [],
            "coverage_tail": [],
            "error": str(exc),
        }

    coverage: list[dict[str, Any]] = []
    for row in rows:
        symbol_count = int(row[1] or 0)
        symbols_with_source = int(row[2] or 0)
        symbols_with_fetched_at = int(row[3] or 0)
        symbols_with_adjustment = int(row[4] or 0)
        has_required_symbols = symbol_count >= min_complete_symbols
        has_price_provenance = (
            symbols_with_source >= symbol_count
            and symbols_with_fetched_at >= symbol_count
            and symbols_with_adjustment >= symbol_count
        )
        coverage.append(
            {
                "date": str(row[0]),
                "symbol_count": symbol_count,
                "symbols_with_source": symbols_with_source,
                "symbols_with_fetched_at": symbols_with_fetched_at,
                "symbols_with_adjustment": symbols_with_adjustment,
                "price_provenance_complete": has_price_provenance,
                "complete_for_universe": has_required_symbols and has_price_provenance,
            }
        )
    provenance_incomplete_dates: list[str] = [
        str(row["date"])
        for row in coverage
        if row["symbol_count"] >= min_complete_symbols and not row["price_provenance_complete"]
    ]
    complete_dates = [str(row["date"]) for row in coverage if row["complete_for_universe"]]
    return {
        "mode": "sqlite_readonly",
        "latest_price_date": coverage[-1]["date"] if coverage else None,
        "latest_complete_price_date": complete_dates[-1] if complete_dates else None,
        "unique_trading_dates": len(coverage),
        "complete_trading_dates": len(complete_dates),
        "required_complete_symbols": min_complete_symbols,
        "universe_symbols": len(universe_symbols),
        "complete_dates": complete_dates,
        "price_provenance_incomplete_dates": provenance_incomplete_dates,
        "coverage_tail": coverage[-8:],
        "error": None,
    }


def _safe_end_by_exit_days(complete_dates: list[str]) -> dict[str, str | None]:
    safe: dict[str, str | None] = {}
    for exit_days in EXIT_DAYS:
        safe[str(exit_days)] = complete_dates[-(exit_days + 1)] if len(complete_dates) > exit_days else None
    return safe


def _last_common_artifact_end(artifacts: dict[int, dict[str, Any]]) -> str | None:
    if any(exit_days not in artifacts for exit_days in EXIT_DAYS):
        return None
    ends = [artifacts[exit_days].get("end") for exit_days in EXIT_DAYS]
    if any(not end for end in ends):
        return None
    return min(str(end) for end in ends)


def _artifact_end_by_exit_days(artifacts: dict[int, dict[str, Any]]) -> dict[str, str | None]:
    return {
        str(exit_days): str(artifacts[exit_days]["end"])
        if exit_days in artifacts and artifacts[exit_days].get("end")
        else None
        for exit_days in EXIT_DAYS
    }


def _latest_artifact_end(artifact_end_by_exit: dict[str, str | None]) -> str | None:
    ends = [end for end in artifact_end_by_exit.values() if end]
    return max(ends) if ends else None


def _readiness_decision(
    *,
    artifacts: dict[int, dict[str, Any]],
    price_data: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    missing = [exit_days for exit_days in EXIT_DAYS if exit_days not in artifacts]
    if missing:
        blockers.append("missing_existing_forward_artifacts_" + "_".join(str(item) for item in missing))
    if price_data.get("error"):
        blockers.append("price_data_unavailable")

    complete_dates = list(price_data.get("complete_dates") or [])
    safe_by_exit = _safe_end_by_exit_days(complete_dates)
    artifact_end_by_exit = _artifact_end_by_exit_days(artifacts)
    last_common = _last_common_artifact_end(artifacts)
    latest_existing = _latest_artifact_end(artifact_end_by_exit)
    recommended = min((value for value in safe_by_exit.values() if value), default=None)
    ready_exit_days: list[int] = []
    for exit_days in EXIT_DAYS:
        safe_end = safe_by_exit[str(exit_days)]
        artifact_end = artifact_end_by_exit[str(exit_days)]
        if safe_end and artifact_end and safe_end > artifact_end:
            ready_exit_days.append(exit_days)
        else:
            blockers.append(f"no_new_complete_{exit_days}d_forward_coverage")

    provenance_incomplete_dates = [
        date
        for date in (price_data.get("price_provenance_incomplete_dates") or [])
        if not latest_existing or date > latest_existing
    ]
    if provenance_incomplete_dates:
        blockers.append("price_provenance_incomplete_after_existing_artifacts")
    if not last_common:
        blockers.append("no_common_existing_forward_artifact_end")
    if recommended and latest_existing and recommended <= latest_existing:
        blockers.append("recommended_forward_end_not_after_all_existing_artifacts")
    latest_price_date = price_data.get("latest_price_date")
    if not isinstance(latest_price_date, str):
        latest_price_date = None
    latest_complete_price_date = price_data.get("latest_complete_price_date")
    if not isinstance(latest_complete_price_date, str):
        latest_complete_price_date = None
    if (
        latest_price_date
        and latest_existing
        and latest_price_date > latest_existing
        and (not latest_complete_price_date or latest_complete_price_date <= latest_existing)
    ):
        blockers.append("partial_latest_trading_day_after_last_artifact")

    ready = not blockers and recommended is not None and len(ready_exit_days) == len(EXIT_DAYS)
    return {
        "last_common_artifact_end": last_common,
        "latest_artifact_end_by_exit_days": artifact_end_by_exit,
        "latest_existing_forward_end": latest_existing,
        "recommended_forward_end": recommended if ready else None,
        "max_safe_forward_end_by_exit_days": safe_by_exit,
        "ready_to_run_forward_shadow": ready,
        "ready_exit_days": ready_exit_days if ready else [],
        "blockers": list(dict.fromkeys(blockers)),
    }


def build_readiness(
    *,
    db_url: str | None = None,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    universe_symbols: set[str] | None = None,
    artifact_paths: list[Path] | None = None,
    artifact_dir: Path = m29_evidence_ledger.DEFAULT_DYNAMIC_ARTIFACT_DIR,
    min_complete_symbols: int | None = None,
) -> dict[str, Any]:
    if universe_symbols is None:
        try:
            universe_symbols = _load_universe_symbols(universe_path)
            universe_error = None
        except Exception as exc:
            universe_symbols = set()
            universe_error = str(exc)
    else:
        universe_error = None
    required_symbols = min_complete_symbols or len(universe_symbols)
    artifacts = latest_forward_artifacts(
        artifact_paths
        if artifact_paths is not None
        else m29_evidence_ledger.default_artifacts(artifact_dir=artifact_dir)
    )
    if db_url:
        price_data = _price_coverage(db_url, universe_symbols, required_symbols)
    else:
        price_data = {
            "mode": "sqlite_readonly",
            "latest_price_date": None,
            "latest_complete_price_date": None,
            "unique_trading_dates": 0,
            "complete_trading_dates": 0,
            "required_complete_symbols": required_symbols,
            "universe_symbols": len(universe_symbols),
            "complete_dates": [],
            "coverage_tail": [],
            "error": "db_url_not_provided",
        }
    readiness = _readiness_decision(artifacts=artifacts, price_data=price_data)
    if universe_error:
        readiness["blockers"] = list(dict.fromkeys([*readiness["blockers"], "universe_not_loaded"]))
        readiness["ready_to_run_forward_shadow"] = False
        readiness["recommended_forward_end"] = None
        readiness["ready_exit_days"] = []

    commands = (
        m29_evidence_ledger.next_forward_commands(forward_end=readiness["recommended_forward_end"])
        if readiness["ready_to_run_forward_shadow"]
        else []
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m29_forward_readiness.v1",
        "milestone": "M29.3",
        "purpose": "read-only guard for deciding whether to run the next M29 forward shadow",
        "run_mode": "read_only_forward_readiness_guard",
        "production_unchanged": True,
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "trains_model": False,
        "runs_forward_shadow": False,
        "artifact_dir": str(artifact_dir.expanduser()),
        "universe": {
            "path": str(universe_path.expanduser()),
            "symbols": len(universe_symbols),
            "error": universe_error,
        },
        "latest_existing_forward_artifacts": {str(k): v for k, v in sorted(artifacts.items())},
        "price_data": {
            key: value for key, value in price_data.items() if key != "complete_dates"
        },
        "readiness": readiness,
        "next_forward_commands": commands,
        "stop_conditions": [
            "do not run partial forward evidence",
            "do not write DB",
            "do not call LLM/API",
            "do not train or save a model",
            "do not change production config",
            "do not treat readiness as promotion evidence",
        ],
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    readiness = report["readiness"]
    price_data = report["price_data"]
    lines = [
        "# M29 Forward Readiness",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- run_mode: {report['run_mode']}",
        f"- production_unchanged: {report['production_unchanged']}",
        f"- writes_db: {report['writes_db']}",
        f"- calls_llm_or_api: {report['calls_llm_or_api']}",
        f"- saves_model: {report['saves_model']}",
        f"- trains_model: {report['trains_model']}",
        f"- runs_forward_shadow: {report['runs_forward_shadow']}",
        f"- ready_to_run_forward_shadow: {readiness['ready_to_run_forward_shadow']}",
        f"- recommended_forward_end: {readiness['recommended_forward_end']}",
        f"- last_common_artifact_end: {readiness['last_common_artifact_end']}",
        "",
        "## Price Data",
        "",
        f"- latest_price_date: {price_data.get('latest_price_date')}",
        f"- latest_complete_price_date: {price_data.get('latest_complete_price_date')}",
        f"- unique_trading_dates: {price_data.get('unique_trading_dates')}",
        f"- complete_trading_dates: {price_data.get('complete_trading_dates')}",
        f"- required_complete_symbols: {price_data.get('required_complete_symbols')}",
        f"- universe_symbols: {price_data.get('universe_symbols')}",
        "",
        "## Blockers",
        "",
    ]
    lines.extend(f"- {blocker}" for blocker in readiness.get("blockers") or ["none"])
    lines.extend(["", "## Next Forward Commands", ""])
    lines.extend(f"- `{command}`" for command in report["next_forward_commands"])
    if not report["next_forward_commands"]:
        lines.append("- none")
    lines.extend(["", "## Stop Conditions", ""])
    lines.extend(f"- {item}" for item in report["stop_conditions"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", help="SQLite DB URL or path; omitted means readiness is blocked")
    parser.add_argument("--universe-path", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--artifact", action="append", type=Path, help="Forward artifact to inspect; repeatable")
    parser.add_argument("--artifact-dir", type=Path, default=m29_evidence_ledger.DEFAULT_DYNAMIC_ARTIFACT_DIR)
    parser.add_argument("--min-complete-symbols", type=int)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_readiness(
        db_url=args.db_url,
        universe_path=args.universe_path,
        artifact_paths=args.artifact,
        artifact_dir=args.artifact_dir,
        min_complete_symbols=args.min_complete_symbols,
    )
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = report_to_markdown(report)
    args.markdown_output.expanduser().write_text(markdown, encoding="utf-8")
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
