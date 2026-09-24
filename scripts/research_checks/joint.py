"""Run the two prepared MingCang research checks together, offline only.

This orchestrates existing offline preparation functions. It does not freeze,
activate, or run any forward model/provider trial.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
UNIVERSE_ROOT = ROOT / "universe"
REPO_ROOT = ROOT.parents[1]
REGISTRATION = ROOT / "portable_joint_registration.json"
JOINT_PROTOCOL = ROOT / "portable_joint_protocol.json"
BASELINE_NAMES = {"prepare.py", "protocol.json", "baseline-universe.json"}


class JointError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise JointError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(JointError(f"nonfinite JSON: {value}")),
    )


def write_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        stream.write("\n")


def verify_registrations() -> tuple[dict[str, Any], dict[str, Any]]:
    registration = read_json(UNIVERSE_ROOT / "registration.json")
    if set(registration.get("files", {})) != BASELINE_NAMES:
        raise JointError("original registration file set changed")
    for name, expected in registration["files"].items():
        path = UNIVERSE_ROOT / name
        if path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise JointError(f"original frozen file hash mismatch: {name}")

    protocol = read_json(JOINT_PROTOCOL)
    joint_registration = read_json(REGISTRATION)
    expected_files = {"joint.py", "portable_joint_protocol.json", "news_event_readiness.py"}
    if set(joint_registration.get("files", {})) != expected_files:
        raise JointError("portable joint registration file set changed")
    news_source = REPO_ROOT / protocol["news_auditor_relative_path"]
    actual = {
        "joint.py": sha256(ROOT / "joint.py"),
        "portable_joint_protocol.json": sha256(JOINT_PROTOCOL),
        "news_event_readiness.py": sha256(news_source),
    }
    for name, expected in joint_registration["files"].items():
        if actual[name] != expected:
            raise JointError(f"portable joint registration hash mismatch: {name}")
    if protocol.get("original_registration_sha256") != sha256(UNIVERSE_ROOT / "registration.json"):
        raise JointError("original registration changed since portable preparation")
    if protocol.get("news_auditor_sha256") != actual["news_event_readiness.py"]:
        raise JointError("news readiness source hash mismatch")
    return registration, protocol


def source_file(path: Path, label: str) -> tuple[Path, str]:
    if path.is_symlink():
        raise JointError(f"{label} symlinks are not accepted")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise JointError(f"{label} must be a regular file")
    return resolved, sha256(resolved)


def fresh_output(path: Path, *, forbidden_roots: tuple[Path, ...] = ()) -> Path:
    if path.is_symlink() or path.exists():
        raise JointError("output directory must be a new, non-symlink path")
    resolved = path.expanduser().resolve(strict=False)
    roots = (ROOT, REPO_ROOT, *(root.resolve(strict=True) for root in forbidden_roots))
    if any(resolved == root or root in resolved.parents for root in roots):
        raise JointError("output directory must be outside the package and MingCang repository")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def verify_mingcang_root(root: Path | None, protocol: dict[str, Any]) -> Path:
    resolved = (
        REPO_ROOT.resolve(strict=True) if root is None else root.expanduser().resolve(strict=True)
    )
    expected = REPO_ROOT.resolve(strict=True)
    if resolved != expected:
        raise JointError("provided MingCang root does not match this checkout")
    source = resolved / protocol["news_auditor_relative_path"]
    if not source.is_file():
        raise JointError("registered news readiness source is missing")
    return resolved


def reject_sqlite_sidecars(path: Path) -> None:
    present = [
        suffix for suffix in ("-wal", "-shm", "-journal") if Path(str(path) + suffix).exists()
    ]
    if present:
        raise JointError(
            "news snapshot has SQLite sidecars ("
            + ", ".join(present)
            + "); use a checkpointed standalone snapshot"
        )


def load_market_functions():
    spec = importlib.util.spec_from_file_location(
        "joint_universe_prepare", UNIVERSE_ROOT / "prepare.py"
    )
    if spec is None or spec.loader is None:
        raise JointError("cannot load the registered universe preparation module")
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise JointError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def load_news_module(path: Path):
    spec = importlib.util.spec_from_file_location("joint_news_event_readiness", path)
    if spec is None or spec.loader is None:
        raise JointError("cannot load registered news readiness module")
    module = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def _run(
    market: dict[str, Any],
    market_bytes: bytes,
    market_path: Path | None,
    news_path: Path,
    news_hash: str,
    as_of: str,
    mingcang_root: Path,
    out_path: Path,
    *,
    synthetic: bool = False,
    created_out_dir: Path | None = None,
) -> dict[str, Any]:
    original_registration, protocol = verify_registrations()
    expected_root = verify_mingcang_root(mingcang_root, protocol)
    news_source = expected_root / protocol["news_auditor_relative_path"]
    before_news_source_hash = sha256(news_source)
    if before_news_source_hash != protocol["news_auditor_sha256"]:
        raise JointError("news readiness source hash changed")
    news_path, before_news_hash = source_file(news_path, "news snapshot")
    if before_news_hash != news_hash:
        raise JointError("news snapshot changed before preparation")
    reject_sqlite_sidecars(news_path)
    if market_path is not None:
        market_path, before_market_hash = source_file(market_path, "market input")
        if hashlib.sha256(market_bytes).hexdigest() != before_market_hash:
            raise JointError("market input changed before preparation")
    else:
        before_market_hash = hashlib.sha256(market_bytes).hexdigest()

    out_dir = (
        fresh_output(out_path, forbidden_roots=(expected_root,))
        if created_out_dir is None
        else created_out_dir
    )
    if created_out_dir is not None and (out_dir.is_symlink() or not out_dir.is_dir()):
        raise JointError("precreated output directory is invalid")
    stages: dict[str, Any] = {}
    shared_plan: dict[str, Any] = {
        "status": "unavailable",
        "scope": "market_candidate_and_holding_plan_only",
        "symbols": [],
        "news_forward_universe_included": False,
        "note": "Market preparation did not produce arm payloads; this is not the future news trial universe.",
    }

    market_module = load_market_functions()
    try:
        parsed = market_module.parse(market_bytes.decode("utf-8"))
        baseline = market_module.load(UNIVERSE_ROOT / "baseline-universe.json")
        policy = market_module.load(UNIVERSE_ROOT / "protocol.json")
        market_result = market_module.prepare(parsed, baseline, policy)
        market_result["input_file_sha256"] = before_market_hash
        write_exclusive(out_dir / "market-preflight.json", market_result)
        stages["market_universe"] = {
            "execution": "completed",
            "preparation_status": market_result["status"],
            "blockers": market_result["blockers"],
            "input_sha256": before_market_hash,
            "expected_symbols": market_result["expected"],
            "coverage": market_result["coverage"],
            "provider_calls": 0,
            "model_calls": 0,
        }
        symbol_set = set()
        for arm_name in ("A", "B"):
            arm = market_result["arms"][arm_name]
            symbol_set.update(arm["candidate_symbols"])
            symbol_set.update(arm["holding_symbols"])
        shared_plan = {
            "status": "planned_from_market_preflight",
            "scope": "market_candidate_and_holding_plan_only",
            "session": market_result["session"],
            "symbols": sorted(symbol_set),
            "news_forward_universe_included": False,
            "evidence_queries_executed": False,
            "common_raw_source_window_certified": False,
            "note": "Union of market A/B candidates and holdings only. A future shared-fetch scope must also include separately frozen news targets, reference universe, and negative-event samples. No news lookup or judgment is shared; arm payloads remain separate.",
        }
    except Exception as exc:
        stages["market_universe"] = {
            "execution": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "input_sha256": before_market_hash,
        }
        write_exclusive(out_dir / "market-stage-error.json", stages["market_universe"])

    try:
        news_module = load_news_module(news_source)
        uri = news_path.as_uri() + "?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            news_result = news_module.build_readiness(
                conn,
                as_of=as_of,
                snapshot_sha256=before_news_hash,
                snapshot_path=str(news_path),
                audit_source_sha256=before_news_source_hash,
                command=["python", "joint.py", "prepare", "--as-of", as_of],
            )
        finally:
            conn.close()
        if sha256(news_path) != before_news_hash:
            raise JointError("news snapshot changed during audit")
        if sha256(news_source) != before_news_source_hash:
            raise JointError("news readiness source changed during audit")
        write_exclusive(out_dir / "news-readiness.json", news_result)
        stages["news_readiness"] = {
            "execution": "completed",
            "schema_version": news_result["schema_version"],
            "event_risk_readiness": news_result["gates"]["event_risk"]["readiness"],
            "direction_gate": news_result["gates"]["direction"]["status"],
            "snapshot_sha256": before_news_hash,
            "as_of_metrics_cohort": news_result["news_shadow_runs"].get(
                "as_of_metrics_cohort", "unknown"
            ),
            "actually_available_by_as_of_count": news_result["news_shadow_runs"].get(
                "actually_available_by_as_of_count"
            ),
            "unavailable_eligible_as_of_count": news_result["news_shadow_runs"].get(
                "unavailable_eligible_count"
            ),
            "eligible_historical_as_of_count": news_result["news_shadow_runs"].get(
                "eligible_as_of_count"
            ),
            "all_history_count_informational_only": news_result["news_shadow_runs"][
                "all_history_count"
            ],
            "provider_calls": 0,
            "model_calls": 0,
            "limitation": "This snapshot-wide date-level audit is not candidate-universe coverage, strict intraday cutoff proof, or the frozen three-arm forward trial.",
        }
    except Exception as exc:
        stages["news_readiness"] = {
            "execution": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "snapshot_sha256": before_news_hash,
        }
        write_exclusive(out_dir / "news-stage-error.json", stages["news_readiness"])

    integrity_errors = []
    try:
        post_registration, _ = verify_registrations()
        if post_registration != original_registration:
            integrity_errors.append("original registration changed during preparation")
    except Exception as exc:
        integrity_errors.append(
            f"registration verification failed after preparation: {type(exc).__name__}: {exc}"
        )
    if market_path is not None and sha256(market_path) != before_market_hash:
        integrity_errors.append("market input changed during preparation")
    if sha256(news_path) != before_news_hash:
        integrity_errors.append("news snapshot changed during preparation")
    if integrity_errors:
        stages["integrity"] = {"execution": "failed", "errors": integrity_errors}
        write_exclusive(out_dir / "integrity-stage-error.json", stages["integrity"])

    stage_values = {name: value["execution"] for name, value in stages.items()}
    joint_status = (
        "offline_preparation_completed"
        if all(value == "completed" for value in stage_values.values())
        else "partial_failure"
    )
    manifest = {
        "schema": "mingcang_joint_offline_preparation.v1",
        "status": joint_status,
        "offline_preparation_execution_completed": joint_status == "offline_preparation_completed",
        "as_of": as_of,
        "market_input_path": str(market_path) if market_path is not None else None,
        "market_cutoff": market.get("cutoff") if isinstance(market, dict) else None,
        "market_input_kind": market.get("kind", "unknown")
        if isinstance(market, dict)
        else "unknown",
        "synthetic_demo": synthetic,
        "experiments": {
            "full_market_vs_fixed25": "existing_offline_preflight_only",
            "news_event_risk_and_direction": "historical_snapshot_readiness_audit_only",
            "news_forward_arms": ["v2-full", "legacy-fast", "v2-pyramid"],
            "news_forward_protocol_frozen": False,
            "forward_calls_made": False,
        },
        "stages": stages,
        "shared_raw_evidence_plan": shared_plan,
        "readiness": {
            "forward_ready": False,
            "outbound_ready": False,
            "economic_activation": False,
        },
        "economics": {"token_usage": None, "billed_cost": None, "measured_savings": None},
        "effects": {
            "network_calls": 0,
            "model_calls": 0,
            "provider_calls": 0,
            "business_database_writes": 0,
            "synthetic_fixture_database_created": synthetic,
            "production_writes": 0,
            "scheduling_changes": 0,
        },
        "registration_sha256": sha256(UNIVERSE_ROOT / "registration.json"),
        "joint_registration_sha256": sha256(REGISTRATION),
        "news_source_sha256": before_news_source_hash,
        "limitations": [
            "Market feature/provenance claims remain caller-submitted and are not independently authenticated by the joint wrapper.",
            "News readiness is snapshot-wide and date-level; it does not prove strict intraday availability or full-market/candidate news coverage.",
            "The three-arm news forward comparison has no frozen protocol or execution path here and was not started.",
            "The shared symbol union is a planning artifact only; no source queries ran and no token or billing savings were measured.",
            "Holdings and all decision payloads remain independent by arm; no six-decision cross-product is generated.",
        ],
    }
    write_exclusive(out_dir / "joint-manifest.json", manifest)
    lines = [
        "MingCang joint offline preparation",
        f"Status: {joint_status} (offline preparation execution only)",
        f"Market: {stages.get('market_universe', {}).get('preparation_status', stages.get('market_universe', {}).get('execution'))}",
        f"News audit: {stages.get('news_readiness', {}).get('event_risk_readiness', stages.get('news_readiness', {}).get('execution'))}; direction={stages.get('news_readiness', {}).get('direction_gate', 'unknown')}",
        f"Shared raw-evidence symbols planned: {len(shared_plan.get('symbols', []))}; queries=0; savings=unknown",
        "Forward news trial: not frozen and not run. No network/model calls or production writes.",
        f"Output: {out_dir}",
    ]
    with (out_dir / "joint-report.txt").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return manifest


def prepare_command(args: argparse.Namespace) -> int:
    _, protocol = verify_registrations()
    mingcang_root = verify_mingcang_root(
        Path(args.mingcang_root) if args.mingcang_root else None, protocol
    )
    market_path, market_hash = source_file(Path(args.market_input).expanduser(), "market input")
    news_path, news_hash = source_file(Path(args.news_snapshot).expanduser(), "news snapshot")
    market_bytes = market_path.read_bytes()
    if hashlib.sha256(market_bytes).hexdigest() != market_hash:
        raise JointError("market input changed while reading")
    as_of = args.as_of
    if not isinstance(as_of, str) or len(as_of) != 10:
        raise JointError("--as-of must be YYYY-MM-DD")
    # Reuse the frozen universe parser/contract to validate the market session.
    market_module = load_market_functions()
    market = market_module.parse(market_bytes.decode("utf-8"))
    if market.get("session") != as_of:
        raise JointError("--as-of must match the market snapshot session")
    manifest = _run(
        market,
        market_bytes,
        market_path,
        news_path,
        news_hash,
        as_of,
        mingcang_root,
        Path(args.out_dir).expanduser(),
    )
    summary = {
        "status": manifest["status"],
        "market": stages_status(manifest, "market_universe", "preparation_status"),
        "market_blocker_count": len(
            manifest["stages"].get("market_universe", {}).get("blockers", [])
        ),
        "news_event_risk": stages_status(manifest, "news_readiness", "event_risk_readiness"),
        "news_subgates": news_gate_summary(manifest, Path(args.out_dir).expanduser().resolve()),
        "news_direction": stages_status(manifest, "news_readiness", "direction_gate"),
        "forward_ready": False,
        "outbound_ready": False,
        "economic_activation": False,
        "out_dir": str(Path(args.out_dir).resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if manifest["offline_preparation_execution_completed"] else 2


def stages_status(manifest: dict[str, Any], stage: str, field: str) -> Any:
    info = manifest["stages"].get(stage, {})
    return info.get(field, info.get("execution", "unknown"))


def news_gate_summary(manifest: dict[str, Any], out_dir: Path) -> dict[str, str]:
    result = manifest.get("stages", {}).get("news_readiness", {})
    if result.get("execution") != "completed":
        return {name: "unknown" for name in ("data", "runtime", "review", "cost")}
    report_path = out_dir / "news-readiness.json"
    try:
        gates = read_json(report_path)["gates"]["event_risk"]
        return {name: gates[name]["status"] for name in ("data", "runtime", "review", "cost")}
    except (OSError, KeyError, TypeError, ValueError):
        return {name: "unknown" for name in ("data", "runtime", "review", "cost")}


def demo_command(args: argparse.Namespace) -> int:
    _, protocol = verify_registrations()
    mingcang_root = verify_mingcang_root(
        Path(args.mingcang_root) if args.mingcang_root else None, protocol
    )
    target = Path(args.out_dir).expanduser()
    out_dir = fresh_output(target, forbidden_roots=(mingcang_root,))
    work = out_dir / "synthetic_inputs"
    work.mkdir()
    try:
        fixture = load_file_module("joint_market_fixture", UNIVERSE_ROOT / "make_fixture.py")
        market = fixture.build_fixture()
        market_path = work / "market-synthetic.json"
        market_bytes = json.dumps(market, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        market_path.write_bytes(market_bytes)
        db_path = work / "news-synthetic.sqlite"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE news_shadow_runs (run_id TEXT, symbol TEXT, as_of TEXT, status TEXT, created_at TEXT, updated_at TEXT, attribution_json TEXT, trigger_reasons_json TEXT, tokens_spent INTEGER, provider TEXT, evidence_json TEXT, degradation_flags_json TEXT, error TEXT, profile TEXT)"
            )
            conn.execute("CREATE TABLE news (published_at TEXT, content TEXT, fetched_at TEXT)")
            conn.commit()
        finally:
            conn.close()
        db_hash = sha256(db_path)
        manifest = _run(
            market,
            market_bytes,
            market_path,
            db_path,
            db_hash,
            market["session"],
            mingcang_root,
            target,
            synthetic=True,
            created_out_dir=out_dir,
        )
        summary = {
            "status": manifest["status"],
            "synthetic_demo": True,
            "market": stages_status(manifest, "market_universe", "preparation_status"),
            "market_blocker_count": len(
                manifest["stages"].get("market_universe", {}).get("blockers", [])
            ),
            "news_event_risk": stages_status(manifest, "news_readiness", "event_risk_readiness"),
            "news_subgates": news_gate_summary(manifest, out_dir),
            "news_direction": stages_status(manifest, "news_readiness", "direction_gate"),
            "forward_ready": False,
            "outbound_ready": False,
            "economic_activation": False,
            "out_dir": str(out_dir),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if manifest["offline_preparation_execution_completed"] else 2
    except Exception:
        # Keep synthetic input evidence if an unexpected error occurs; it is isolated beside output.
        raise


def check_command(args: argparse.Namespace) -> int:
    verify_registrations()
    mingcang_root = verify_mingcang_root(
        Path(args.mingcang_root) if args.mingcang_root else None, verify_registrations()[1]
    )
    out_dir = fresh_output(Path(args.out_dir).expanduser(), forbidden_roots=(mingcang_root,))
    env = dict(os.environ)
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": str(mingcang_root),
        }
    )
    commands = [
        ("universe", [sys.executable, "-m", "unittest", "-v", "test_prepare"]),
        (
            "news",
            [
                sys.executable,
                "-m",
                "pytest",
                "--noconftest",
                "-q",
                "-o",
                f"cache_dir={out_dir / 'pytest-cache'}",
                "tests/evidence/test_news_event_readiness.py",
            ],
        ),
        ("joint", [sys.executable, "-m", "unittest", "-v", "test_joint"]),
    ]
    results = []
    for name, command in commands:
        cwd = UNIVERSE_ROOT if name == "universe" else ROOT if name == "joint" else mingcang_root
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        log_path = out_dir / f"{name}.log"
        with log_path.open("x", encoding="utf-8") as stream:
            stream.write("COMMAND: " + " ".join(command) + "\n")
            stream.write("STDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr)
        results.append({"suite": name, "returncode": result.returncode, "log": str(log_path)})
    report = {
        "schema": "mingcang_joint_check.v1",
        "status": "passed" if all(r["returncode"] == 0 for r in results) else "failed",
        "suites": results,
    }
    write_exclusive(out_dir / "check.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "suites": [
                    {"suite": r["suite"], "returncode": r["returncode"], "log": r["log"]}
                    for r in results
                ],
                "out_dir": str(out_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="prepare supplied market and immutable news snapshots")
    prepare.add_argument("--market-input", required=True)
    prepare.add_argument("--news-snapshot", required=True)
    prepare.add_argument("--as-of", required=True)
    prepare.add_argument(
        "--mingcang-root", help="optional checkout root; defaults to this repository"
    )
    prepare.add_argument("--out-dir", help="new external output directory")
    demo = sub.add_parser(
        "demo", help="run both preparations with synthetic market/news-only fixtures"
    )
    demo.add_argument("--mingcang-root", help="optional checkout root; defaults to this repository")
    demo.add_argument("--out-dir", help="new external output directory")
    check = sub.add_parser(
        "check", help="run the frozen universe/news and joint offline test suites"
    )
    check.add_argument(
        "--mingcang-root", help="optional checkout root; defaults to this repository"
    )
    check.add_argument(
        "--out-dir", help="new external directory for concise report and retained logs"
    )
    args = parser.parse_args(argv)
    if getattr(args, "out_dir", None) is None:
        args.out_dir = str(Path(tempfile.gettempdir()) / f"mingcang-joint-check-{uuid.uuid4().hex}")
    if getattr(args, "mingcang_root", None) is None and args.command in {
        "prepare",
        "demo",
        "check",
    }:
        args.mingcang_root = str(REPO_ROOT)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "prepare":
            return prepare_command(args)
        if args.command == "demo":
            return demo_command(args)
        return check_command(args)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"joint offline preparation refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
