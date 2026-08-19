"""Pre-registered Stage4 adjudication contract for M58 exit shadow/holdout."""

from __future__ import annotations

from datetime import UTC, datetime

CURRENT_EXIT_VARIANT = "trailing_2_5__none"
SHADOW_EXIT_VARIANT = "trailing_3_5__drawdown_10"
LOCKED_SHORTLIST = (
    "trailing_2_5__none",
    "trailing_3__none",
    "trailing_3_5__drawdown_10",
    "trailing_2_5__drawdown_10",
)

EXIT_ADJUDICATION_GOVERNANCE = {
    "owner_domain": "backend.portfolio",
    "unique_consumer": "M58 exit shadow/holdout review",
    "input_contract": "m58_exit_shadow.v1 and m58_exit_sweep.holdout_adjudication.v1 reports",
    "output_contract": "m58_exit_preregistered_adjudication.v1",
    "failure_mode": "missing shadow/holdout reports keep production locked",
    "degradation": "contract remains reviewable with insufficient_sample status",
    "baseline": CURRENT_EXIT_VARIANT,
    "success_metric": "shadow candidate beats baseline after locked shortlist/sample gates without safety regression",
    "minimum_sample": "4-6 weeks forward shadow plus leader-approved holdout sample",
    "expiry_or_exit": "expires after 6 weeks or earlier leader rejection",
    "rollback": f"retain {CURRENT_EXIT_VARIANT}; ignore shadow candidate",
    "replacement": "new owner-confirmed exit policy only after explicit promotion",
    "lifecycle": "shadow",
    "signal_impact": "none",
}


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta(report: dict | None) -> dict:
    return (report or {}).get("meta") or {}


def _sample(report: dict | None) -> dict:
    if not report:
        return {"present": False, "sample_count": 0}
    return {
        "present": True,
        "entry_count": int(report.get("entry_count") or 0),
        "open_position_count": int(report.get("open_position_count") or 0),
        "trade_difference_count": len(report.get("trade_differences") or []),
        "trial_count": int(report.get("trial_count") or 0),
    }


def _shortlist_status(holdout_report: dict | None) -> dict:
    shortlist = tuple(_meta(holdout_report).get("shortlist") or LOCKED_SHORTLIST)
    return {
        "locked": set(shortlist) == set(LOCKED_SHORTLIST) and len(shortlist) == len(LOCKED_SHORTLIST),
        "expected": list(LOCKED_SHORTLIST),
        "observed": list(shortlist),
        "allows_new_variants": False,
    }


def _variant_key(row: dict) -> str | None:
    variant = row.get("variant") or {}
    if isinstance(variant, dict):
        return variant.get("key") or variant.get("label")
    return None


def _result_integrity(results: list[dict]) -> dict:
    keys = [_variant_key(row) for row in results]
    counts = {key: keys.count(key) for key in set(keys) if key is not None}
    expected = set(LOCKED_SHORTLIST)
    observed = {key for key in keys if key is not None}
    duplicates = sorted(key for key, count in counts.items() if count != 1)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    ok = not missing and not unexpected and not duplicates and len(keys) == len(LOCKED_SHORTLIST)
    return {
        "ok": ok,
        "expected": list(LOCKED_SHORTLIST),
        "observed": keys,
        "missing": missing,
        "duplicate_or_wrong_count": duplicates,
        "unexpected": unexpected,
    }


def _holdout_verdict(holdout_report: dict | None) -> dict:
    if not holdout_report:
        return {
            "verdict": "insufficient_evidence_no_promotion",
            "shadow_variant_verdict": "not_evaluated",
            "reason": "holdout_report_missing",
            "baseline": None,
            "rejected_shadow_variants": [],
            "result_integrity": _result_integrity([]),
            "fail_closed": True,
        }

    results = [row for row in holdout_report.get("results", []) if isinstance(row, dict)]
    integrity = _result_integrity(results)
    if not integrity["ok"]:
        return {
            "verdict": "insufficient_evidence_no_promotion",
            "shadow_variant_verdict": "not_evaluated",
            "reason": "locked_holdout_results_must_contain_baseline_plus_three_nonbaseline_variants_exactly_once",
            "baseline": None,
            "rejected_shadow_variants": [],
            "result_integrity": integrity,
            "fail_closed": True,
            "promotion_allowed": False,
            "production_change_allowed": False,
        }

    baseline_key = _meta(holdout_report).get("baseline_variant") or CURRENT_EXIT_VARIANT
    baseline = next((row for row in results if _variant_key(row) == baseline_key), None)
    shadow_rows = [row for row in results if _variant_key(row) != baseline_key]
    rejected_shadow_rows = [
        row
        for row in shadow_rows
        if row.get("drawdown_violation")
        or float(row.get("net_return_pct") or 0.0) <= float((baseline or {}).get("net_return_pct") or 0.0)
    ]
    all_shadow_rejected = bool(shadow_rows) and len(rejected_shadow_rows) == len(shadow_rows)
    baseline_drawdown_violation = bool((baseline or {}).get("drawdown_violation"))
    if baseline and all_shadow_rejected:
        verdict = "retain_baseline_no_promotion"
        shadow_verdict = "reject_shadow_variants"
        reason = (
            "baseline remains the current production rule, but holdout drawdown gate prevents promotion; "
            "all non-baseline locked variants are rejected by return/drawdown evidence"
        )
    elif baseline:
        verdict = "pending_leader_real_data_verdict"
        shadow_verdict = "pending"
        reason = "holdout evidence does not produce an automatic promotion or rejection"
    else:
        verdict = "insufficient_evidence_no_promotion"
        shadow_verdict = "not_evaluated"
        reason = "baseline row missing from holdout results"

    return {
        "verdict": verdict,
        "shadow_variant_verdict": shadow_verdict,
        "reason": reason,
        "baseline": {
            "variant": baseline_key,
            "net_return_pct": (baseline or {}).get("net_return_pct"),
            "max_drawdown_pct": (baseline or {}).get("max_drawdown_pct"),
            "drawdown_violation": baseline_drawdown_violation,
        },
        "rejected_shadow_variants": [
            {
                "variant": _variant_key(row),
                "net_return_pct": row.get("net_return_pct"),
                "max_drawdown_pct": row.get("max_drawdown_pct"),
                "drawdown_violation": bool(row.get("drawdown_violation")),
            }
            for row in rejected_shadow_rows
        ],
        "result_integrity": integrity,
        "fail_closed": False,
        "promotion_allowed": False,
        "production_change_allowed": False,
    }


def build_exit_adjudication_contract(
    *,
    shadow_report: dict | None = None,
    holdout_report: dict | None = None,
    min_forward_weeks: int = 4,
) -> dict:
    """Return the locked, no-production-change adjudication contract."""

    shadow_meta = _meta(shadow_report)
    holdout_meta = _meta(holdout_report)
    shortlist = _shortlist_status(holdout_report)
    shadow_sample = _sample(shadow_report)
    holdout_sample = _sample(holdout_report)
    holdout_verdict = _holdout_verdict(holdout_report)
    blockers: list[str] = []
    if not shadow_report:
        blockers.append("missing_shadow_report")
    if not holdout_report:
        blockers.append("missing_holdout_report")
    if not shortlist["locked"]:
        blockers.append("shortlist_not_locked")
    if shadow_meta and shadow_meta.get("current_variant") != CURRENT_EXIT_VARIANT:
        blockers.append("current_variant_drift")
    if shadow_meta and shadow_meta.get("shadow_variant") != SHADOW_EXIT_VARIANT:
        blockers.append("shadow_variant_drift")
    if not holdout_verdict["result_integrity"]["ok"]:
        blockers.append("holdout_result_integrity_failed")
    status = "blocked"
    if not blockers and holdout_verdict["verdict"] == "retain_baseline_no_promotion":
        status = "adjudicated_no_promotion"
    elif not blockers:
        status = "registered_shadow_review"

    return {
        "schema_version": "m58_exit_preregistered_adjudication.v1",
        "status": status,
        "production_change_allowed": False,
        "real_trading_allowed": False,
        "signal_impact": "none",
        "current_variant": CURRENT_EXIT_VARIANT,
        "shadow_candidate": SHADOW_EXIT_VARIANT,
        "locked_shortlist": shortlist,
        "sample_state": {
            "shadow": shadow_sample,
            "holdout": holdout_sample,
            "min_forward_weeks": min_forward_weeks,
            "minimum_sample_policy": EXIT_ADJUDICATION_GOVERNANCE["minimum_sample"],
        },
        "promotion_gate": {
            "status": "blocked",
            "verdict": holdout_verdict["verdict"],
            "shadow_variant_verdict": holdout_verdict["shadow_variant_verdict"],
            "requires": [
                "locked_shortlist_unchanged",
                "forward_shadow_sample_complete",
                "holdout_report_present",
                "no_safety_regression",
                "leader_real_data_verdict",
                "explicit_user_confirmation",
            ],
            "stat_gate_source": "m58_exit_sweep.holdout_adjudication.v1",
            "direction_or_signal_change": "not_allowed_by_this_contract",
        },
        "rollback": {
            "default": f"retain {CURRENT_EXIT_VARIANT}",
            "disable": "stop consuming m58_exit_shadow report; no DB/schema rollback required",
        },
        "blockers": blockers,
        "holdout_verdict": holdout_verdict,
        "shadow_refs": {
            "shadow_schema": shadow_meta.get("schema_version"),
            "holdout_schema": holdout_meta.get("schema_version"),
            "shadow_window": shadow_meta.get("window"),
            "holdout_window": {
                "start": holdout_meta.get("start"),
                "end": holdout_meta.get("end"),
            },
        },
        "read_only": True,
        "write_policy": "no_database_writes",
        "generated_at": _stamp(),
        "governance": dict(EXIT_ADJUDICATION_GOVERNANCE),
    }
