"""Read-only model-trial inventory and explicit-bundle diagnostic replay CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.evidence.model_comparison import (
    assemble_candidate_v3_request,
    build_model_account_context,
    build_model_comparison_report,
    build_model_trial_request_context,
    content_hash,
)

MAX_BYTES = 32 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"requires regular file: {path.name}")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("input exceeds byte limit")
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_object, parse_constant=_reject_constant
    )


def inspect_registered_channel(root: Path, protocol: dict) -> dict | None:
    """Verify the additive v2 registration without running a provider."""
    registration_path = root / "canonical-v2-registration.json"
    if not registration_path.exists():
        return None
    registration = read_json(registration_path)
    if registration.get("parent_protocol_sha256") != content_hash(protocol):
        raise ValueError("v2 parent protocol mismatch")
    authorization = read_json(root / "authorization-20260920.json")
    if (
        registration.get("authorization_sha256") != content_hash(authorization)
        or authorization.get("authorized") is not True
    ):
        raise ValueError("v2 authorization record mismatch")
    scope = authorization["scope"]
    if (
        len(scope["symbols"]) != 25
        or len(set(scope["symbols"])) != 25
        or set(scope["symbols"]) != {s["symbol"] for s in read_json(root / "universe.json")["stocks"]}
        or "real account" not in scope["excluded"]
        or "real holdings" not in scope["excluded"]
        or registration.get("same_budget_and_ledger_root") is not True
        or registration.get("counts_existing_20260920_failure") is not True
        or registration.get("maximum_total_sessions") != protocol["maximum_sessions"]
    ):
        raise ValueError("v2 authorization scope or shared budget mismatch")
    hashes = registration.get("code_hashes")
    expected = {"trial_canonical_v2.py", "candidates/codex_transport_canonical.py"}
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise ValueError("v2 registered code inventory mismatch")
    for name, expected_hash in hashes.items():
        path = root / name
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
        ):
            raise ValueError(f"v2 registered code changed: {name}")
    return {
        "version": "canonical_v2",
        "registration_sha256": content_hash(registration),
        "authorization_record_sha256": content_hash(authorization),
        "registered_code_verified": sorted(hashes),
        "authorized_symbol_count": 25,
        "maximum_sessions": protocol["maximum_sessions"],
        "expires_at": protocol["expires_at"],
        "provider_identity_validated": False,
        "billing_validated": False,
        "economic_trial_activated": False,
    }


def inspect_candidate_v3_registration(candidate_root: Path) -> tuple[dict, dict, dict, dict]:
    """Verify only the prepared v3 candidate; never import trial transports."""
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise ValueError("v3 candidate root must be a regular directory")
    registration = read_json(candidate_root / "registration.json")
    trial_root = Path(registration["ledger_root"])
    if trial_root.is_symlink() or not trial_root.is_dir() or not trial_root.is_absolute():
        raise ValueError("v3 ledger root must be an absolute regular directory")
    inventory = inspect_trial(trial_root)
    protocol = read_json(trial_root / "protocol.json")
    authorization = read_json(trial_root / "authorization-20260920.json")
    v2_registration = read_json(trial_root / "canonical-v2-registration.json")
    if (
        registration.get("schema_version") != "matched_model_candidate_registration.v3"
        or registration.get("status") != "prepared_not_activated"
        or registration.get("execution_mode") != "injected_fake_only"
        or registration.get("parent_protocol_sha256") != content_hash(protocol)
        or registration.get("authorization_sha256") != content_hash(authorization)
        or registration.get("v2_registration_sha256") != content_hash(v2_registration)
        or registration.get("ledger_root") != str(trial_root.resolve())
        or registration.get("same_budget_and_ledger_root") is not True
        or registration.get("maximum_total_sessions") != protocol["maximum_sessions"]
        or registration.get("account_ids") != {
            arm: arm + "-synthetic" for arm in protocol["models"]
        }
        or inventory["registered_channel"] is None
    ):
        raise ValueError("v3 registration, authorization or ledger linkage mismatch")
    source = Path(__file__).resolve().parents[2]
    expected = {
        "backend/evidence/model_comparison.py",
        "backend/tools/model_comparison.py",
    }
    hashes = registration.get("code_hashes")
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise ValueError("v3 candidate code inventory mismatch")
    for name, digest in hashes.items():
        path = source / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"v3 candidate code changed: {name}")
    return registration, protocol, authorization, inventory


def inspect_trial(root: Path) -> dict:
    """Inventory existing local receipts without importing or invoking trial code."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("trial root must be a regular directory")
    root = root.resolve()
    protocol = read_json(root / "protocol.json")
    digest_file = root / "protocol.sha256"
    if digest_file.is_symlink() or not digest_file.is_file():
        raise ValueError("protocol digest missing")
    if content_hash(protocol) != digest_file.read_text().strip():
        raise ValueError("frozen protocol changed")
    universe = read_json(root / "universe.json")
    if content_hash(universe) != protocol["universe_sha256"]:
        raise ValueError("frozen universe changed")
    repo = Path(__file__).resolve().parents[2]
    core_files = {
        "backend/backtest/nav_replay.py",
        "backend/evidence/decision_desk_session.py",
        "backend/evidence/decision_desk_recording.py",
        "backend/evidence/decision_desk_process.py",
        "scripts/run_decision_desk_checks.py",
    }
    verified = []
    for name, expected in protocol["code_hashes"].items():
        if name in ("trial.py", "codex_transport.py"):
            path = root / name
        else:
            matches = [p for p in core_files if name.endswith("/" + p)]
            if len(matches) != 1:
                raise ValueError("unrecognized frozen code dependency")
            path = repo / matches[0]
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"frozen code changed: {path.name}")
        verified.append(path.name)
    if set(verified) != {"trial.py", "codex_transport.py", *(Path(p).name for p in core_files)}:
        raise ValueError("frozen code dependency inventory incomplete")
    registered_channel = inspect_registered_channel(root, protocol)
    records = []
    runs = root / "runs"
    if runs.is_symlink():
        raise ValueError("runs directory must not be symlink")
    for day in sorted(runs.iterdir()) if runs.exists() else []:
        if day.is_symlink() or not day.is_dir():
            raise ValueError("invalid run directory")
        reservation = read_json(day / "reservation.json")
        summary = read_json(day / "summary.json") if (day / "summary.json").exists() else None
        record = {
            "day": day.name,
            "reservation": reservation,
            "summary_status": summary.get("status") if summary else "interrupted_unknown",
            "arms": {},
        }
        for arm in protocol["models"]:
            location = day / arm
            if location.is_symlink():
                raise ValueError("arm directory must not be symlink")
            execution = (
                read_json(location / "execution.json")
                if (location / "execution.json").exists()
                else None
            )
            decision_exists = (location / "decision.json").is_file()
            record["arms"][arm] = {
                "execution_receipt_present": execution is not None,
                "decision_file_present": decision_exists,
                "execution_returncode": execution.get("returncode") if execution else None,
                "validated_decision": False,
            }
        records.append(record)
    return {
        "schema_version": "model_trial_inventory.v1",
        "status": "prepared_not_activated" if not records else "receipts_require_validation",
        "protocol_sha256": content_hash(protocol),
        "frozen_code_verified": verified,
        "models": protocol["models"],
        "reserved_sessions": len(records),
        "remaining_session_capacity": max(0, protocol["maximum_sessions"] - len(records)),
        "registered_channel": registered_channel,
        "sessions": records,
        "execution_receipts": sum(
            a["execution_receipt_present"] for r in records for a in r["arms"].values()
        ),
        "validated_paired_decisions": 0,
        "certifies_returns": False,
        "economic_trial_activated": False,
        "blockers": [
            *([] if registered_channel else ["outbound_authorization_not_assessed_by_inventory"]),
            "actual_model_identity_and_responses_not_validated",
            "raw_execution_prices_calendar_actions_units_not_validated",
            "billed_model_cost_unknown",
            "prospective_account_feedback_and_execution_activation_not_reviewed",
        ],
        "limits": [
            "File presence is not a successful model call or a validated decision.",
            "A verified authorization record does not prove provider identity, billing or automation state.",
            "The frozen runner remains unchanged; failed dates are never retried.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="explicit matched_model_replay.v1 bundle")
    source.add_argument("--trial-root", type=Path, help="inventory a frozen local decision trial")
    parser.add_argument(
        "--output", required=True, type=Path, help="new JSON file; existing files never overwritten"
    )
    parser.add_argument(
        "--account-at", help="aware closed-session account cutoff (requires --input and --arm)"
    )
    parser.add_argument("--arm", help="the sole arm included in the account context")
    parser.add_argument(
        "--request-context", action="store_true",
        help="emit blocked, one-arm account fields for a separately registered runner",
    )
    parser.add_argument(
        "--candidate-v3-root", type=Path,
        help="opt-in read-only v3 preflight using a prepared candidate registration",
    )
    parser.add_argument("--session-id", help="prospective candidate session date")
    parser.add_argument("--shared-input", type=Path, help="reviewed public 25-stock shared input")
    parser.add_argument("--source-review", type=Path, help="separate source/context hash review record")
    args = parser.parse_args(argv)
    if bool(args.account_at) != bool(args.arm) or (args.account_at and not args.input):
        parser.error("--account-at and --arm must be used together with --input")
    if args.request_context and not args.account_at:
        parser.error("--request-context requires --input, --account-at and --arm")
    if args.candidate_v3_root and (
        not args.input or not args.account_at or not args.session_id
        or not args.shared_input or not args.source_review or args.request_context
    ):
        parser.error("v3 preflight requires --input, --account-at, --arm, --session-id, --shared-input and --source-review")
    if not args.candidate_v3_root and (args.session_id or args.shared_input or args.source_review):
        parser.error("v3 input flags require --candidate-v3-root")
    try:
        if args.candidate_v3_root:
            registration, protocol, authorization, inventory = inspect_candidate_v3_registration(
                args.candidate_v3_root
            )
            ledger = {
                "root": registration["ledger_root"],
                "maximum_sessions": inventory["registered_channel"]["maximum_sessions"],
                "reserved_session_ids": [s["day"] for s in inventory["sessions"]],
            }
            request = assemble_candidate_v3_request(
                read_json(args.input), arm=args.arm, session_id=args.session_id,
                cutoff=args.account_at, shared_input=read_json(args.shared_input),
                protocol=protocol, authorization=authorization, registration=registration,
                ledger=ledger, source_review=read_json(args.source_review),
            )
            report = {
                "schema_version": "matched_model_candidate_preflight.v3",
                "status": "prepared_not_activated",
                "request_sha256": content_hash(request),
                "account_context_sha256": request["account_context_sha256"],
                "candidate_registration_sha256": content_hash(registration),
                "reserved_sessions": inventory["reserved_sessions"],
                "remaining_session_capacity": inventory["remaining_session_capacity"],
                "reservations_created": 0,
                "model_calls": 0,
                "source_authenticity_independently_verified": False,
                "provider_identity_validated": False,
                "billing_validated": False,
                "economic_trial_activated": False,
            }
        elif args.request_context:
            report = build_model_trial_request_context(
                read_json(args.input), arm=args.arm, cutoff=args.account_at
            )
        elif args.account_at:
            report = build_model_account_context(
                read_json(args.input), arm=args.arm, cutoff=args.account_at
            )
        elif args.input:
            report = build_model_comparison_report(read_json(args.input))
        else:
            report = inspect_trial(args.trial_root)
        # Exclusive creation also rejects existing symlinks and preserves old reports.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
