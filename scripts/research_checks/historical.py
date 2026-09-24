#!/usr/bin/env python3
"""Run a bounded real-history technical baseline and prepare shared news inputs.

This entry point never fetches source data or calls a model. It requires an
existing market batch and immutable SQLite snapshot, and deliberately returns
exit status 4 until the three news model arms have a reviewed adapter/budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

EXIT_PARTIAL = 4
BASELINE = Path(__file__).resolve().parents[2]
TECHNICAL_SCRIPT = BASELINE / "backend/backtest/historical_technical.py"
NEWS_SCRIPT = BASELINE / "backend/evidence/historical_news_inputs.py"
UNIVERSE = BASELINE / "scripts/research_checks/universe/baseline-universe.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_decision_dates(value: str) -> list[str]:
    try:
        dates = [
            date.fromisoformat(item.strip()).isoformat()
            for item in value.split(",")
            if item.strip()
        ]
    except ValueError as exc:
        raise ValueError("decision dates must be comma-separated YYYY-MM-DD values") from exc
    if not dates:
        raise ValueError("at least one decision date is required")
    if len(dates) != len(set(dates)):
        raise ValueError("decision dates must not contain duplicates")
    return sorted(dates)


def _scope_date(value: object) -> str:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return date.fromisoformat(text).isoformat()


def validate_inputs(market_source: Path, news_snapshot: Path, decision_dates: list[str]) -> dict:
    scope_path = market_source / "scope.json"
    if market_source.is_symlink() or scope_path.is_symlink():
        raise ValueError("market source and scope.json must not be symlinks")
    if not market_source.is_dir() or not scope_path.is_file():
        raise ValueError(f"market source must contain scope.json: {market_source}")
    if not news_snapshot.is_file():
        raise ValueError(f"news snapshot does not exist: {news_snapshot}")
    try:
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        decision_list = [_scope_date(item) for item in scope["decisions"]]
        day_list = [_scope_date(item).replace("-", "") for item in scope["days"]]
        if len(decision_list) != len(set(decision_list)) or len(day_list) != len(set(day_list)):
            raise ValueError("scope contains duplicate decisions or market dates")
        scope_decisions = sorted(decision_list)
        scope_days = set(day_list)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid market scope {scope_path}: {exc}") from exc
    if decision_dates != scope_decisions:
        raise ValueError(
            "decision dates must exactly match market scope decisions; "
            f"requested={decision_dates}, scope={scope_decisions}"
        )
    for day in decision_dates:
        if day.replace("-", "") not in scope_days:
            raise ValueError(f"decision date {day} is absent from market scope days")
    expected_source_days = sorted(scope_days)
    reuse_day = str(scope.get("reuse_day")) if scope.get("reuse_day") else None
    resolved_source_files: list[Path] = []
    missing = []
    for day in expected_source_days:
        market_pair = (market_source / f"{day}.json", market_source / f"{day}.receipt.json")
        if all(path.is_file() and not path.is_symlink() for path in market_pair):
            resolved_source_files.extend(market_pair)
            continue
        preflight_pair = (
            market_source.parent / "source-preflight" / f"daily-{day}.json",
            market_source.parent / "source-preflight" / f"daily-{day}.receipt.json",
        )
        if reuse_day == day and all(
            path.is_file() and not path.is_symlink() for path in preflight_pair
        ):
            resolved_source_files.extend(preflight_pair)
            continue
        missing.append(day)
    if missing:
        raise ValueError(
            f"market source is incomplete; missing raw/receipt files for {missing[:5]}"
        )
    calendar_source = scope.get("calendar_source")
    calendar_hash = scope.get("calendar_source_sha256")
    if bool(calendar_source) != bool(calendar_hash):
        raise ValueError(
            "market scope must provide both calendar_source and calendar_source_sha256"
        )
    if calendar_source:
        calendar_path = Path(str(calendar_source))
        if not calendar_path.is_absolute():
            calendar_path = market_source / calendar_path
        if (
            calendar_path.is_symlink()
            or not calendar_path.is_file()
            or sha256(calendar_path) != calendar_hash
        ):
            raise ValueError(
                "referenced calendar source is missing or its hash differs from market scope"
            )
    else:
        calendar_path = None
    return {
        "scope": scope,
        "scope_path": scope_path,
        "market_source_sha256": sha256(scope_path),
        "news_snapshot_sha256": sha256(news_snapshot),
        "calendar_path": calendar_path,
        "resolved_source_files": resolved_source_files,
    }


def validate_factor_source(factor_source: Path, market_scope: dict) -> None:
    if not factor_source.is_dir() or not (factor_source / "scope.json").is_file():
        raise ValueError(
            f"factor source must be a directory containing scope.json: {factor_source}"
        )
    try:
        factor_scope = json.loads((factor_source / "scope.json").read_text(encoding="utf-8"))
        expected_days = sorted(str(value).replace("-", "") for value in market_scope["days"])
        actual_days = sorted(str(value).replace("-", "") for value in factor_scope["days"])
        expected_decisions = sorted(
            str(value).replace("-", "") for value in market_scope["decisions"]
        )
        actual_decisions = sorted(
            str(value).replace("-", "") for value in factor_scope["decisions"]
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid factor source scope: {exc}") from exc
    if (
        len(actual_days) != len(set(actual_days))
        or len(actual_decisions) != len(set(actual_decisions))
        or actual_days != expected_days
        or actual_decisions != expected_decisions
    ):
        raise ValueError("factor source dates must exactly match the market source scope")
    missing = [
        day
        for day in expected_days
        if not (factor_source / f"{day}.json").is_file()
        or not (factor_source / f"{day}.receipt.json").is_file()
    ]
    if missing:
        raise ValueError(
            f"factor source is incomplete; missing raw/receipt files for {missing[:5]}"
        )


def fingerprint_tree(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise ValueError(f"input path must not be a symlink: {path}")
    if path.is_file():
        return {str(path): sha256(path)}
    if not path.is_dir():
        raise ValueError(f"input path does not exist: {path}")
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if any(item.is_symlink() for item in path.rglob("*")):
        raise ValueError(f"input directory must not contain symlinks: {path}")
    return {str(item): sha256(item) for item in [path / "scope.json", *files]}


def fingerprint_digest(fingerprints: dict[str, str]) -> str:
    canonical = json.dumps(fingerprints, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run(command: Sequence[str]) -> None:
    subprocess.run(list(command), check=True, cwd=BASELINE)


def run(
    market_source: Path,
    news_snapshot: Path,
    industry_metadata: Path,
    out_dir: Path,
    decision_dates: list[str],
    runner: Callable[[Sequence[str]], None] = _run,
    factor_source: Path | None = None,
) -> int:
    paths = [market_source, news_snapshot, industry_metadata, out_dir]
    if factor_source is not None:
        paths.append(factor_source)
    expanded = [path.expanduser() for path in paths]
    labels = (
        "market source",
        "news snapshot",
        "industry metadata",
        "output directory",
        "factor source",
    )[: len(expanded)]
    for label, path in zip(labels, expanded, strict=True):
        if path.is_symlink():
            raise ValueError(f"{label} must not be a symlink: {path}")
    market_source, news_snapshot, industry_metadata, out_dir = [
        path.resolve() for path in expanded[:4]
    ]
    if factor_source is not None:
        factor_source = expanded[4].resolve()
    if not TECHNICAL_SCRIPT.is_file() or not NEWS_SCRIPT.is_file():
        raise ValueError("historical repo entry modules are not installed in this candidate")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"output directory must be new or empty: {out_dir}")
    if not industry_metadata.is_file():
        raise ValueError(f"industry metadata does not exist: {industry_metadata}")
    evidence = validate_inputs(market_source, news_snapshot, decision_dates)
    if factor_source is not None:
        validate_factor_source(factor_source, evidence["scope"])
        fingerprint_tree(factor_source)
    protected_roots = [
        market_source.resolve(),
        *{path.parent.resolve() for path in evidence["resolved_source_files"]},
    ]
    if factor_source is not None:
        protected_roots.append(factor_source.resolve())
    output_resolved = out_dir.resolve()
    if any(output_resolved == root or root in output_resolved.parents for root in protected_roots):
        raise ValueError("output directory must be outside all immutable source trees")
    out_dir.mkdir(parents=True, exist_ok=True)
    protected_paths = [
        news_snapshot,
        industry_metadata,
        *([evidence["calendar_path"]] if evidence["calendar_path"] else []),
        *evidence["resolved_source_files"],
    ]

    def input_fingerprints() -> dict[str, str]:
        source_paths = sorted(path for path in market_source.rglob("*") if path.is_file())
        fingerprints = {str(path): sha256(path) for path in [*protected_paths, *source_paths]}
        if factor_source is not None:
            fingerprints.update(fingerprint_tree(factor_source))
        return fingerprints

    before = input_fingerprints()
    technical_out = out_dir / "technical"
    news_out = out_dir / "news-inputs"
    tech_args = [
        "--source-root",
        str(market_source),
        "--out-dir",
        str(technical_out),
        "--fixed25-universe",
        str(UNIVERSE),
        "--industry-metadata",
        str(industry_metadata),
    ]
    if factor_source is not None:
        tech_args.extend(["--factor-source", str(factor_source)])
    news_args = ["--db", str(news_snapshot), "--out-dir", str(news_out)]
    for day in decision_dates:
        news_args.extend(["--decision-date", day])
    phase = "technical_freeze"
    failure = None
    try:
        runner(
            [
                sys.executable,
                "-m",
                "backend.backtest.historical_technical",
                *tech_args,
                "--freeze-only",
            ]
        )
        phase = "technical_baseline"
        runner([sys.executable, "-m", "backend.backtest.historical_technical", *tech_args])
        phase = "news_input_export"
        runner([sys.executable, "-m", "backend.evidence.historical_news_inputs", *news_args])
        required_outputs = [
            technical_out / "protocol.json",
            technical_out / "technical-baseline.json",
            technical_out / "feature-scores.jsonl",
            technical_out / "selection-manifest.json",
            news_out / "manifest.json",
            news_out / "raw_inputs.jsonl",
        ]
        missing_outputs = [str(path) for path in required_outputs if not path.is_file()]
        if missing_outputs:
            raise RuntimeError(f"child process omitted required outputs: {missing_outputs}")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        failure = exc
    finally:
        try:
            after = input_fingerprints()
        except (OSError, ValueError) as exc:
            after = {}
            failure = RuntimeError(f"could not recheck read-only inputs: {exc}")
            phase = "input_integrity"
    if before != after:
        failure = RuntimeError("read-only input evidence changed during historical run")
        phase = "input_integrity"
    if failure is not None:
        status = {
            "schema": "mingcang_historical_test_entry.v1",
            "status": "blocked",
            "exit_code": 2,
            "blocked_stage": phase,
            "reason": str(failure),
            "decision_dates": decision_dates,
            "market_source": str(market_source.resolve()),
            "news_snapshot": str(news_snapshot.resolve()),
            "factor_source": str(factor_source.resolve()) if factor_source else None,
            "orchestrator_sha256": sha256(Path(__file__).resolve()),
            "technical_script_sha256": sha256(TECHNICAL_SCRIPT),
            "news_extractor_sha256": sha256(NEWS_SCRIPT),
            "inputs_unchanged": before == after,
            "source_calls": False,
            "production_database_writes": False,
        }
        if isinstance(failure, subprocess.CalledProcessError):
            status["child_returncode"] = failure.returncode
        (out_dir / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    status = {
        "schema": "mingcang_historical_test_entry.v1",
        "status": "partial_news_models_blocked",
        "exit_code": EXIT_PARTIAL,
        "decision_dates": decision_dates,
        "market_source": str(market_source.resolve()),
        "market_scope_sha256": evidence["market_source_sha256"],
        "factor_source": str(factor_source.resolve()) if factor_source else None,
        "factor_source_sha256": (
            fingerprint_digest(fingerprint_tree(factor_source))
            if factor_source is not None
            else None
        ),
        "news_snapshot": str(news_snapshot.resolve()),
        "news_snapshot_sha256": evidence["news_snapshot_sha256"],
        "industry_metadata_sha256": sha256(industry_metadata),
        "orchestrator_sha256": sha256(Path(__file__).resolve()),
        "technical_script_sha256": sha256(TECHNICAL_SCRIPT),
        "news_extractor_sha256": sha256(NEWS_SCRIPT),
        "technical_output": str(technical_out.resolve()),
        "news_inputs_output": str(news_out.resolve()),
        "news_models": {"legacy-fast": "not_run", "v2-full": "not_run", "v2-pyramid": "not_run"},
        "reason": "raw historical news inputs are prepared, but no subscription-only adapters with frozen provider/model/prompt identities are available; no news model arm was run",
        "model_call_policy": "existing subscriptions only; no paid API calls",
        "inputs_unchanged": True,
        "information_cutoff": {
            "technical": "decision-date market close",
            "news": "strictly before decision-date 00:00 Asia/Shanghai",
            "same_information_cutoff": False,
        },
        "source_calls": False,
        "production_database_writes": False,
    }
    (out_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return EXIT_PARTIAL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run technical baseline + prepare news inputs")
    run_parser.add_argument("--market-source", type=Path, required=True)
    run_parser.add_argument("--news-snapshot", type=Path, required=True)
    run_parser.add_argument(
        "--industry-metadata",
        type=Path,
        required=True,
        help="frozen stock_basic metadata used by the technical baseline",
    )
    run_parser.add_argument(
        "--factor-source",
        type=Path,
        help="optional decision-window factor source; omitted means raw-price baseline",
    )
    run_parser.add_argument(
        "--decision-dates",
        required=True,
        help="comma-separated YYYY-MM-DD dates; must equal scope.json decisions",
    )
    run_parser.add_argument(
        "--out-dir", type=Path, required=True, help="new or empty isolated result directory"
    )
    args = parser.parse_args(argv)
    try:
        return run(
            args.market_source,
            args.news_snapshot,
            args.industry_metadata,
            args.out_dir,
            parse_decision_dates(args.decision_dates),
            factor_source=args.factor_source,
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"historical research-test blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
