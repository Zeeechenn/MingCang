"""Build a read-only M29 alpha evidence ledger from local M27/M29 artifacts.

The ledger is an artifact index, not a promotion engine. It reads existing JSON
reports, normalizes their gate/sample/data-quality fields, and writes a JSON or
Markdown summary. It does not open the StockSage DB, call an LLM/API, save a
model, or change production configuration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings

DEFAULT_ARTIFACTS = [
    Path.home() / ".stock-sage" / "m27_top_decile_forward_shadow_1d.json",
    Path.home() / ".stock-sage" / "m27_top_decile_forward_shadow_3d.json",
    Path.home() / ".stock-sage" / "m27_top_decile_forward_shadow_5d.json",
    Path("/private/tmp/m27_forward_shadow_rolling_20260401_20260529_1d.json"),
    Path("/private/tmp/m27_forward_shadow_rolling_20260401_20260529_3d.json"),
    Path("/private/tmp/m27_forward_shadow_rolling_20260401_20260529_5d.json"),
    Path("/private/tmp/m27_alpha_event_ab_lookback5_after_backfill_20260531_v2.json"),
    Path("/private/tmp/m27_label_objective_eval_stage0_gate.json"),
    Path("/private/tmp/m27_label_objective_eval_m27_1d_multi_exit.json"),
    Path("/private/tmp/m27_label_objective_eval_include_inactive_m27_1d_multi_exit.json"),
    Path.home() / ".stock-sage" / "m26_kronos_report.json",
    Path("/private/tmp/m29_shadow_validation_top_decile_entry_timing_v1.json"),
    Path("/private/tmp/m29_shadow_validation_post_event_drift_pure_polarity_v1.json"),
    Path("/private/tmp/m29_quant_residual_attribution_v1.json"),
]
DEFAULT_JSON_OUTPUT = Path.home() / ".stock-sage" / "m29_evidence_ledger.json"
DEFAULT_MARKDOWN_OUTPUT = Path.home() / ".stock-sage" / "m29_evidence_ledger.md"
DEFAULT_DYNAMIC_ARTIFACT_DIR = Path("/private/tmp")
QUANT_RESIDUAL_NEXT_ACTION = "append_shadow_artifact_to_m29_ledger_and_wait_for_fresh_forward_coverage"
M29_FORWARD_ARTIFACT_RE = re.compile(
    r"^m29_forward_shadow_rolling_(?P<start>\d{8})_(?P<end>\d{8})_(?P<exit_days>[135])d\.json$"
)
PROVENANCE_REQUIRED_FIELDS = [
    "artifact_sha256",
    "source_generated_at",
    "data_source",
    "fetched_at",
    "adjustment",
    "universe_hash",
    "train_label_realized_end",
]
DEFAULT_FORWARD_START = "2026-04-01"
DEFAULT_LAST_FORWARD_END = "2026-05-29"


def next_forward_commands(
    *,
    start: str = DEFAULT_FORWARD_START,
    end_placeholder: str = "<LATEST_TRADING_DAY_AFTER_2026-05-29>",
    forward_end: str | None = None,
) -> list[str]:
    end_value = forward_end or end_placeholder
    start_token = start.replace("-", "")
    end_token = forward_end.replace("-", "") if forward_end else end_placeholder
    return [
        "PYTHONPYCACHEPREFIX=/private/tmp/stocksage_pycache PYTHONPATH=. MULTI_AGENT_ENABLED=false "
        ".venv/bin/python -m backend.tools.m27_top_decile_forward_shadow "
        "--universe-path paper_trading/test3_universe.json --rolling "
        f"--start {start} --end {end_value} --rolling-window-days 7 --rolling-stride-days 7 "
        f"--exit-days {exit_days} --json-output /private/tmp/m29_forward_shadow_rolling_"
        f"{start_token}_{end_token}_{exit_days}d.json "
        f"--markdown-output /private/tmp/m29_forward_shadow_rolling_{start_token}_"
        f"{end_token}_{exit_days}d.md"
        for exit_days in (1, 3, 5)
    ]


def _forward_artifact_sort_key(path: Path) -> tuple[int, str, str]:
    match = M29_FORWARD_ARTIFACT_RE.match(path.name)
    if not match:
        return (0, "", "")
    return (
        int(match.group("exit_days")),
        match.group("end"),
        match.group("start"),
    )


def discover_m29_forward_artifacts(artifact_dir: Path = DEFAULT_DYNAMIC_ARTIFACT_DIR) -> list[Path]:
    latest_by_exit: dict[int, Path] = {}
    for path in artifact_dir.expanduser().glob("m29_forward_shadow_rolling_*d.json"):
        match = M29_FORWARD_ARTIFACT_RE.match(path.name)
        if not match:
            continue
        exit_days = int(match.group("exit_days"))
        current = latest_by_exit.get(exit_days)
        if current is None or _forward_artifact_sort_key(path) > _forward_artifact_sort_key(current):
            latest_by_exit[exit_days] = path
    return [latest_by_exit[exit_days] for exit_days in sorted(latest_by_exit)]


def default_artifacts(
    *,
    static_artifacts: list[Path] | None = None,
    artifact_dir: Path = DEFAULT_DYNAMIC_ARTIFACT_DIR,
) -> list[Path]:
    paths = list(DEFAULT_ARTIFACTS if static_artifacts is None else static_artifacts)
    seen = {str(path.expanduser()) for path in paths}
    for path in discover_m29_forward_artifacts(artifact_dir):
        expanded = str(path.expanduser())
        if expanded not in seen:
            paths.append(path)
            seen.add(expanded)
    return paths


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _read_only_flags(payload: dict[str, Any]) -> dict[str, bool | None]:
    return {
        "writes_db": _bool(payload.get("writes_db")),
        "calls_llm_or_api": _bool(payload.get("calls_llm_or_api")),
        "saves_model": _bool(payload.get("saves_model")),
        "trains_model": _bool(payload.get("trains_model")),
    }


def _add_data_quality_blocker(entry: dict[str, Any], blocker: str) -> None:
    if blocker and blocker not in entry["data_quality_blockers"]:
        entry["data_quality_blockers"].append(blocker)


def _base_entry(path: Path, payload: dict[str, Any], *, candidate: str, variant: str) -> dict[str, Any]:
    production_unchanged = _bool(payload.get("production_unchanged"))
    read_only_flags = _read_only_flags(payload)
    unknown_boundary_flags = [
        name
        for name, value in {
            "production_unchanged": production_unchanged,
            **read_only_flags,
        }.items()
        if value is None
    ]
    entry: dict[str, Any] = {
        "evidence_id": f"{candidate}:{variant}:{path.expanduser().name}",
        "candidate": candidate,
        "variant": variant,
        "source_artifact": str(path.expanduser()),
        "source_generated_at": payload.get("generated_at"),
        "provenance": _artifact_provenance(path, payload),
        "window": {
            "start": payload.get("start"),
            "end": payload.get("end"),
        },
        "sample_size": {},
        "metrics": {},
        "gate": {},
        "gate_pass": False,
        "blockers": [],
        "data_quality_blockers": [],
        "multiple_comparison_warning": None,
        "production_unchanged": production_unchanged,
        "non_promoting": True,
        "read_only_flags": read_only_flags,
        "unknown_boundary_flags": unknown_boundary_flags,
        "decision": "non_promoting",
        "next_action": "keep_collecting_forward_evidence",
    }
    for flag in unknown_boundary_flags:
        _append_blocker(entry, f"unknown_source_{flag}")
        _add_data_quality_blocker(entry, f"unknown_source_{flag}")
    provenance = entry["provenance"]
    missing_provenance_fields = provenance.get("missing_provenance_fields", [])
    if not isinstance(missing_provenance_fields, list):
        missing_provenance_fields = []
    for field in missing_provenance_fields:
        _add_data_quality_blocker(entry, f"missing_provenance_{field}")
    missing_price_provenance_rows = provenance.get("panel_price_provenance_missing_rows")
    if isinstance(missing_price_provenance_rows, (int, float)) and missing_price_provenance_rows > 0:
        _add_data_quality_blocker(entry, "panel_price_provenance_incomplete")
    for flag, value in read_only_flags.items():
        if value is True:
            _append_blocker(entry, f"source_artifact_{flag}")
            _add_data_quality_blocker(entry, f"source_artifact_{flag}")
    if production_unchanged is False:
        _append_blocker(entry, "source_artifact_production_changed")
    return entry


def _artifact_provenance(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    expanded = path.expanduser()
    stat = expanded.stat()
    panel = payload.get("panel") or {}
    price_provenance = panel.get("price_provenance") or {}
    filter_sample = (((payload.get("filter") or {}).get("classifier") or {}).get("sample") or {})
    coverage = ((payload.get("event_ab_5d") or {}).get("coverage") or {})
    provenance = {
        "artifact_path": str(expanded),
        "artifact_sha256": _sha256_file(expanded),
        "artifact_size_bytes": stat.st_size,
        "artifact_mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
        "source_generated_at": payload.get("generated_at"),
        "data_source": payload.get("data_source") or panel.get("data_source"),
        "fetched_at": payload.get("fetched_at") or panel.get("fetched_at"),
        "adjustment": payload.get("adjustment") or panel.get("adjustment"),
        "universe_hash": payload.get("universe_hash") or panel.get("universe_hash"),
        "universe_symbols": payload.get("universe_symbols") or coverage.get("universe_symbols"),
        "panel_start": panel.get("start"),
        "panel_end": panel.get("end"),
        "panel_rows": panel.get("n_rows"),
        "panel_symbols": panel.get("n_symbols"),
        "panel_price_provenance": price_provenance,
        "panel_price_provenance_missing_rows": price_provenance.get("missing_price_provenance_rows"),
        "train_start": filter_sample.get("train_start"),
        "train_end": filter_sample.get("train_end"),
        "train_label_realized_end": payload.get("train_label_realized_end")
        or filter_sample.get("train_label_realized_end"),
        "target_start": filter_sample.get("target_start") or payload.get("start"),
        "target_end": filter_sample.get("target_end") or payload.get("end"),
        "horizon": payload.get("horizon"),
        "exit_days": payload.get("exit_days"),
    }
    provenance["missing_provenance_fields"] = [
        field for field in PROVENANCE_REQUIRED_FIELDS if provenance.get(field) in (None, "")
    ]
    return provenance


def _append_blocker(entry: dict[str, Any], blocker: str) -> None:
    if blocker and blocker not in entry["blockers"]:
        entry["blockers"].append(blocker)


def _entry_from_top_decile(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rolling = "rolling" in payload
    exit_days = payload.get("exit_days")
    variant = f"{'rolling_' if rolling else ''}{exit_days}d"
    entry = _base_entry(path, payload, candidate="top_decile_entry_filter", variant=variant)
    entry["artifact_kind"] = "top_decile_forward_shadow_rolling" if rolling else "top_decile_forward_shadow"
    sample = payload.get("sample_adequacy") or {}
    profile_ab = payload.get("profile_ab") or {}
    profile_summary = payload.get("aggregate_profile_summary") or {}
    delta = profile_ab.get("delta_filtered_minus_baseline") or {}
    filter_payload = payload.get("filter") or {}
    baseline_trades = sample.get("baseline_trades")
    if baseline_trades is None:
        baseline_trades = (profile_ab.get("baseline_arm") or {}).get("metrics", {}).get("trades")
    filtered_trades = sample.get("filtered_trades")
    if filtered_trades is None:
        filtered_trades = (profile_ab.get("filtered_arm") or {}).get("metrics", {}).get("trades")
    min_trades_for_sharpe = sample.get("min_trades_for_sharpe", 50)
    entry["sample_size"] = {
        "baseline_trades": baseline_trades,
        "filtered_trades": filtered_trades,
        "min_trades_for_sharpe": min_trades_for_sharpe,
        "ic_days": None,
    }
    entry["metrics"] = {
        "ic": None,
        "icir": None,
        "stride_ic": None,
        "stride_icir": None,
        "top_bottom": profile_summary.get("trade_weighted_avg_net_return_delta")
        if rolling
        else delta.get("avg_net_return"),
        "positive_windows": profile_summary.get("positive_avg_net_return_delta_windows"),
        "window_count": (payload.get("rolling") or {}).get("window_count"),
        "quantile_monotonic": None,
    }
    entry["gate"] = {
        "sample_gate": "filtered_trades >= 50 before Sharpe can be cited",
        "promotion_gate": "not a continuous quant score; non-promoting by design",
    }
    if sample.get("insufficient_for_sharpe") or (
        isinstance(filtered_trades, (int, float)) and filtered_trades < min_trades_for_sharpe
    ):
        _append_blocker(entry, "insufficient_filtered_trades_for_sharpe")
    if filter_payload.get("status") not in (None, "ok"):
        _append_blocker(entry, f"filter_status_{filter_payload.get('status')}")
        _add_data_quality_blocker(entry, "filter_not_ok")
    _append_blocker(entry, "not_continuous_quant_score")
    _append_blocker(entry, "non_promoting_offline_diagnostic")
    entry["next_action"] = "extend_forward_shadow_after_new_price_data"
    return entry


def _event_variant_entry(
    path: Path,
    payload: dict[str, Any],
    *,
    variant: str,
    metrics_key: str,
    validation_key: str,
) -> dict[str, Any]:
    event_ab = payload["event_ab_5d"]
    metrics = event_ab.get(metrics_key) or {}
    validation = event_ab.get(validation_key) or {}
    gate = event_ab.get("event_ab_gate") or {}
    coverage = event_ab.get("coverage") or {}
    comparison = event_ab.get("variant_comparison") or {}
    entry = _base_entry(path, payload, candidate="sentiment_event_alpha", variant=variant)
    entry["artifact_kind"] = "event_ab_v2_gate"
    entry["sample_size"] = {
        "rows_with_polarity": coverage.get("rows_with_polarity"),
        "rows_with_news": coverage.get("rows_with_news"),
        "rows_with_cache_polarity": coverage.get("rows_with_cache_polarity"),
        "rows_with_fallback_polarity": coverage.get("rows_with_fallback_polarity"),
        "cache_miss_windows": coverage.get("cache_miss_windows"),
        "ic_days": metrics.get("ic_days"),
    }
    entry["metrics"] = {
        "ic": metrics.get("ic_mean"),
        "icir": metrics.get("icir"),
        "stride_ic": None,
        "stride_icir": None,
        "top_bottom": validation.get("top_bottom_oriented"),
        "quantile_monotonic": validation.get("monotonic_oriented"),
    }
    entry["gate"] = gate
    entry["gate_pass"] = bool(validation.get("passes_event_ab_gate"))
    for blocker in validation.get("gate_blockers") or []:
        _append_blocker(entry, blocker)
    for blocker in validation.get("data_quality_blockers") or []:
        _add_data_quality_blocker(entry, blocker)
    if coverage.get("cache_miss_windows") not in (None, 0):
        _append_blocker(entry, "cache_miss_windows_not_zero")
        _add_data_quality_blocker(entry, "cache_miss_windows_not_zero")
    if coverage.get("rows_with_fallback_polarity") not in (None, 0):
        _append_blocker(entry, "rows_with_fallback_polarity_not_zero")
        _add_data_quality_blocker(entry, "rows_with_fallback_polarity_not_zero")
    entry["multiple_comparison_warning"] = gate.get("multiple_comparison_warning")
    comparison_production_unchanged = _bool(comparison.get("production_unchanged"))
    if comparison_production_unchanged is not None:
        entry["production_unchanged"] = comparison_production_unchanged
        if "production_unchanged" in entry["unknown_boundary_flags"]:
            entry["unknown_boundary_flags"].remove("production_unchanged")
            for blocker in ("unknown_source_production_unchanged",):
                if blocker in entry["blockers"]:
                    entry["blockers"].remove(blocker)
                if blocker in entry["data_quality_blockers"]:
                    entry["data_quality_blockers"].remove(blocker)
    if entry["production_unchanged"] is False:
        _append_blocker(entry, "source_artifact_production_changed")
    entry["decision"] = "candidate_passed_needs_manual_review" if entry["gate_pass"] else "non_promoting"
    entry["next_action"] = "rerun_readonly_event_ab_after_new_forward_window"
    return entry


def _candidate_by_name(payload: dict[str, Any], name: str | None) -> dict[str, Any]:
    if not name:
        return {}
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("name") == name:
            return candidate
    return {}


def _label_sub_evidence_summary(payload: dict[str, Any]) -> dict[str, Any]:
    short = payload.get("short_horizon_candidates") or {}
    sector = payload.get("sector_industry_specific_candidates") or {}
    multi_exit = payload.get("multi_exit_summary") or []
    sector_candidates = sector.get("candidates") or [] if isinstance(sector, dict) else []
    return {
        "multi_exit_candidate_count": len(multi_exit) if isinstance(multi_exit, list) else None,
        "short_horizon_candidate_count": len(short.get("candidates") or [])
        if isinstance(short, dict)
        else None,
        "short_horizon_decision": (short.get("decision") or {}).get("decision")
        if isinstance(short, dict)
        else None,
        "short_horizon_non_promoting": short.get("non_promoting") if isinstance(short, dict) else None,
        "sector_segment_candidate_count": len(sector_candidates),
        "sector_segment_cols": sector.get("segment_cols") if isinstance(sector, dict) else None,
        "sector_non_promoting": sector.get("non_promoting") if isinstance(sector, dict) else None,
        "sector_promotion_blocker": sector.get("promotion_blocker") if isinstance(sector, dict) else None,
    }


def _entries_from_event_ab(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _event_variant_entry(
            path,
            payload,
            variant="pure_polarity_lookback5",
            metrics_key="polarity",
            validation_key="pure_polarity_validation",
        ),
        _event_variant_entry(
            path,
            payload,
            variant="polarity_plus_event_lookback5",
            metrics_key="polarity_event",
            validation_key="polarity_event_validation",
        ),
    ]


def _entry_from_label_objective(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    panel = payload.get("panel") or {}
    best_candidate = _candidate_by_name(payload, decision.get("best_raw_candidate"))
    best_raw_validation = best_candidate.get("raw_return_validation") or {}
    best_raw_gates = best_raw_validation.get("gates") or {}
    best_stride_validation = best_candidate.get("raw_return_stride_validation") or {}
    best_stride_metrics = best_stride_validation.get("metrics") or {}
    best_top_decile_metrics = best_candidate.get("top_decile_metrics") or {}
    best_raw_passed = best_raw_gates.get("pass") is True
    best_stride_icir = decision.get("best_raw_stride_icir")
    if best_stride_icir is None:
        best_stride_icir = best_stride_metrics.get("icir")
    best_stride_passed = isinstance(best_stride_icir, (int, float)) and best_stride_icir >= settings.qlib_train_icir_floor
    entry = _base_entry(
        path,
        payload,
        candidate="label_objective_search",
        variant=str(decision.get("best_raw_candidate") or path.expanduser().stem),
    )
    entry["artifact_kind"] = "label_objective_eval"
    entry["sub_evidence_summary"] = _label_sub_evidence_summary(payload)
    entry["window"] = {
        "start": panel.get("start"),
        "end": panel.get("end"),
    }
    entry["sample_size"] = {
        "rows": panel.get("n_rows"),
        "symbols": panel.get("n_symbols"),
        "dates": panel.get("n_dates"),
    }
    entry["metrics"] = {
        "ic": decision.get("best_raw_ic"),
        "icir": decision.get("best_raw_icir"),
        "stride_ic": decision.get("best_raw_stride_ic"),
        "stride_icir": best_stride_icir,
        "top_decile_lift": decision.get("best_raw_top_decile_lift")
        or best_top_decile_metrics.get("lift_vs_base_rate"),
        "top_bottom": best_stride_metrics.get("top_bottom"),
        "quantile_monotonic": best_raw_gates.get("pass_monotonic"),
    }
    entry["gate"] = payload.get("gate") or {}
    entry["gate_pass"] = bool(best_raw_passed and best_stride_passed)
    entry["multiple_comparison_warning"] = decision.get("multiple_comparison_warning")
    if decision.get("decision") == "keep_quant_disabled":
        _append_blocker(entry, "decision_keep_quant_disabled")
    if not best_stride_passed:
        _append_blocker(entry, "stride_icir_gate_not_passed")
    if not best_raw_passed:
        _append_blocker(entry, "best_candidate_raw_gate_not_passed")
    if not best_candidate:
        _append_blocker(entry, "best_candidate_details_missing")
    entry["next_action"] = decision.get("recommended_next_action") or "pre_register_new_objective_before_next_run"
    return entry


def _entry_from_kronos(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    metrics = payload.get("kronos_metrics") or {}
    entry = _base_entry(path, payload, candidate="kronos_path_a_finetuned", variant=str(payload.get("model") or "kronos"))
    entry["artifact_kind"] = "kronos_eval"
    entry["window"] = {"eval_window": payload.get("eval_window")}
    entry["sample_size"] = {
        "symbols": payload.get("n_symbols"),
        "eval_dates": payload.get("n_eval_dates"),
        "ic_days": metrics.get("ic_series_len"),
    }
    entry["metrics"] = {
        "ic": metrics.get("ic"),
        "icir": metrics.get("icir"),
        "ic_positive_rate": metrics.get("ic_pos_ratio"),
        "top_bottom": None,
        "quantile_monotonic": metrics.get("monotonic"),
    }
    entry["gate"] = decision.get("m27_gate") or {}
    entry["gate_pass"] = bool(decision.get("m27_gate_pass"))
    if not decision.get("beats_lgbm_ic", False):
        _append_blocker(entry, "does_not_beat_lgbm_ic")
    if not decision.get("m27_gate_pass", False):
        _append_blocker(entry, "m27_gate_not_passed")
    if metrics.get("monotonic") is False:
        _append_blocker(entry, "not_monotonic")
    entry["next_action"] = "do_not_continue_kronos_without_new_approved_hypothesis"
    return entry


def _entry_from_shadow_validation(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("shadow_validation") or {}
    summary = payload.get("candidate_summary") or {}
    best = summary.get("best_candidate") or {}
    hypothesis_id = str(payload.get("hypothesis_id") or path.expanduser().stem)
    entry = _base_entry(
        path,
        payload,
        candidate=str(payload.get("candidate_family") or "m29_shadow_validation"),
        variant=hypothesis_id,
    )
    entry["artifact_kind"] = "m29_shadow_validation"
    entry["hypothesis_id"] = hypothesis_id
    entry["window"] = {
        "start": (payload.get("panel") or {}).get("start"),
        "end": (payload.get("panel") or {}).get("end"),
    }
    sample = best.get("sample") or {}
    entry["sample_size"] = {
        "rows": sample.get("n_rows"),
        "symbols": sample.get("n_symbols"),
        "validation_rows": sample.get("validation_rows"),
        "baseline_trades": sample.get("baseline_trades"),
        "filtered_trades": sample.get("filtered_trades"),
        "positive_windows": sample.get("positive_windows"),
        "window_count": sample.get("window_count"),
        "ic_days": best.get("raw_ic_days"),
        "candidate_count": summary.get("candidate_count"),
    }
    entry["metrics"] = {
        "ic": best.get("raw_ic"),
        "icir": best.get("raw_icir"),
        "stride_ic": best.get("stride_ic"),
        "stride_icir": best.get("stride_icir"),
        "top_bottom": best.get("raw_top_bottom"),
        "quantile_monotonic": best.get("raw_pass_monotonic"),
        "top_decile_lift": best.get("top_decile_lift"),
    }
    entry["gate"] = payload.get("promotion_gate") or {}
    entry["gate_pass"] = False
    entry["shadow_validation"] = {
        "raw_stride_gate_pass": validation.get("raw_stride_gate_pass"),
        "reported_gate_pass": validation.get("gate_pass"),
        "decision": validation.get("decision"),
    }
    for blocker in validation.get("blockers") or payload.get("blockers") or []:
        _append_blocker(entry, blocker)
    for blocker in payload.get("data_quality_blockers") or []:
        _add_data_quality_blocker(entry, blocker)
    multiple = payload.get("multiple_comparison") or {}
    entry["multiple_comparison_warning"] = multiple.get("warning")
    entry["decision"] = validation.get("decision") or "non_promoting"
    entry["next_action"] = (
        (payload.get("decision") or {}).get("recommended_next_action")
        or validation.get("recommended_next_action")
        or "append_to_ledger_and_collect_fresh_forward_evidence"
    )
    _append_blocker(entry, "shadow_validation_non_promoting")
    return entry


def _entry_from_quant_residual_attribution(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    exit_days = str(payload.get("exit_days") or "5")
    residual = ((payload.get("residual_ic") or {}).get(exit_days) or {}).get(
        "quant_residual_to_technical_sentiment",
        {},
    )
    sample = payload.get("sample") or {}
    trade_attribution = payload.get("trade_attribution") or {}
    decision = payload.get("decision") or {}
    entry = _base_entry(
        path,
        payload,
        candidate="quant_residual_attribution",
        variant="quant_residual_attribution_v1",
    )
    entry["artifact_kind"] = "m29_quant_residual_attribution"
    entry["window"] = {
        "start": payload.get("start"),
        "end": payload.get("end"),
    }
    entry["sample_size"] = {
        "signal_inputs": sample.get("signal_inputs"),
        "scored_rows": sample.get("scored_rows"),
        "rows_with_nonzero_quant": sample.get("rows_with_nonzero_quant"),
        "rows_with_event": sample.get("rows_with_event"),
        "threshold_crossers": trade_attribution.get("crossed_entry_threshold_count"),
        "ic_days": residual.get("ic_days"),
    }
    entry["metrics"] = {
        "ic": residual.get("ic_mean"),
        "icir": residual.get("icir"),
        "stride_ic": None,
        "stride_icir": None,
        "top_bottom": residual.get("top_bottom"),
        "quantile_monotonic": residual.get("monotonic"),
    }
    entry["gate"] = payload.get("promotion_gate") or {}
    entry["gate_pass"] = False
    entry["shadow_validation"] = {
        "reported_gate_pass": residual.get("gate_pass"),
        "decision": decision.get("decision"),
        "promotable": decision.get("promotable"),
    }
    entry["sub_evidence_summary"] = {
        "quant_sweep_profiles": sorted(((payload.get("quant_sweep") or {}).get("arms") or {}).keys()),
        "residual_horizons": sorted((payload.get("residual_ic") or {}).keys()),
        "interaction_bucket_families": sorted((payload.get("interaction_buckets") or {}).keys()),
        "direction_counts": trade_attribution.get("direction_counts"),
    }
    for blocker in payload.get("blockers") or decision.get("blockers") or []:
        _append_blocker(entry, blocker)
    for blocker in payload.get("data_quality_blockers") or []:
        _add_data_quality_blocker(entry, blocker)
    multiple = payload.get("multiple_comparison") or {}
    entry["multiple_comparison_warning"] = multiple.get("warning")
    entry["decision"] = decision.get("decision") or "non_promoting"
    reported_next_action = decision.get("recommended_next_action")
    if reported_next_action and reported_next_action != QUANT_RESIDUAL_NEXT_ACTION:
        _append_blocker(entry, "quant_residual_recommended_next_action_ignored")
        _add_data_quality_blocker(entry, "quant_residual_recommended_next_action_ignored")
    entry["next_action"] = QUANT_RESIDUAL_NEXT_ACTION
    _append_blocker(entry, "shadow_validation_non_promoting")
    return entry


def entry_from_artifact(path: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "event_ab_5d" in payload:
        return _entries_from_event_ab(path, payload)
    if payload.get("run_mode") == "read_only_quant_residual_attribution":
        return [_entry_from_quant_residual_attribution(path, payload)]
    if payload.get("run_mode") == "read_only_shadow_validation":
        return [_entry_from_shadow_validation(path, payload)]
    if payload.get("run_mode") in {"offline_read_only_forward_shadow", "offline_read_only_forward_shadow_rolling"}:
        return [_entry_from_top_decile(path, payload)]
    if "candidates" in payload and "decision" in payload:
        return [_entry_from_label_objective(path, payload)]
    if "kronos_metrics" in payload and "decision" in payload:
        return [_entry_from_kronos(path, payload)]
    return []


def build_ledger(paths: list[Path], *, forward_end: str | None = None) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for raw_path in paths:
        path = raw_path.expanduser()
        if not path.exists():
            skipped.append({"path": str(path), "reason": "missing"})
            continue
        try:
            payload = _load_json(path)
            extracted = entry_from_artifact(path, payload)
        except Exception as exc:
            skipped.append({"path": str(path), "reason": f"load_or_parse_error: {exc}"})
            continue
        if not extracted:
            skipped.append({"path": str(path), "reason": "unsupported_artifact_shape"})
            continue
        entries.extend(extracted)

    gate_pass_count = sum(1 for entry in entries if entry["gate_pass"])
    entries_with_missing_provenance = sum(
        1 for entry in entries if entry["provenance"]["missing_provenance_fields"]
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": "m29_evidence_ledger.v1",
        "purpose": "read-only alpha evidence ledger; no DB writes, no LLM/API calls, no model writes",
        "writes_db": False,
        "calls_llm_or_api": False,
        "saves_model": False,
        "production_unchanged": True,
        "summary": {
            "artifacts_requested": len(paths),
            "artifacts_parsed": len({entry["source_artifact"] for entry in entries}),
            "entries": len(entries),
            "gate_pass_count": gate_pass_count,
            "promotable_count": 0,
            "non_promoting_count": len(entries),
            "entries_with_missing_provenance": entries_with_missing_provenance,
            "skipped_artifacts": len(skipped),
        },
        "provenance_contract": {
            "required_fields": PROVENANCE_REQUIRED_FIELDS,
            "policy": "missing required fields are blockers, not inferred safe defaults",
            "next_m29_3_requirement": (
                "future forward-shadow artifacts should include data_source, fetched_at, "
                "adjustment, universe_hash, and train_label_realized_end before promotion review"
            ),
        },
        "next_forward_commands": next_forward_commands(forward_end=forward_end),
        "promotion_contract": {
            "ic_floor": settings.qlib_train_ic_floor,
            "icir_floor": settings.qlib_train_icir_floor,
            "monotonic_required": settings.qlib_train_require_monotonic,
            "requires_fresh_forward": True,
            "requires_no_data_quality_blockers": True,
            "requires_human_confirmation": True,
        },
        "entries": entries,
        "skipped_artifacts": skipped,
        "stop_conditions": [
            "do not restore weight_quant from this ledger alone",
            "do not change production signal profile from this ledger alone",
            "do not write sentiment_cache or train/attach checkpoints without explicit approval",
            "any gate pass still requires fresh OOS/forward evidence and manual confirmation",
        ],
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# M29 Evidence Ledger",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- schema_version: {report['schema_version']}",
        f"- entries: {summary['entries']}",
        f"- gate_pass_count: {summary['gate_pass_count']}",
        f"- entries_with_missing_provenance: {summary['entries_with_missing_provenance']}",
        f"- skipped_artifacts: {summary['skipped_artifacts']}",
        f"- production_unchanged: {report['production_unchanged']}",
        "",
        "## Promotion Contract",
        "",
        f"- ic_floor: {report['promotion_contract']['ic_floor']}",
        f"- icir_floor: {report['promotion_contract']['icir_floor']}",
        f"- monotonic_required: {report['promotion_contract']['monotonic_required']}",
        f"- requires_fresh_forward: {report['promotion_contract']['requires_fresh_forward']}",
        f"- requires_no_data_quality_blockers: {report['promotion_contract']['requires_no_data_quality_blockers']}",
        f"- requires_human_confirmation: {report['promotion_contract']['requires_human_confirmation']}",
        "",
        "## Entries",
        "",
        "| candidate | variant | gate_pass | missing provenance | blockers | source |",
        "|---|---|---:|---|---|---|",
    ]
    for entry in report["entries"]:
        blockers = ", ".join(entry["blockers"]) if entry["blockers"] else "none"
        missing_provenance = ", ".join(entry["provenance"]["missing_provenance_fields"]) or "none"
        lines.append(
            "| {candidate} | {variant} | {gate_pass} | {missing_provenance} | {blockers} | {source} |".format(
                candidate=entry["candidate"],
                variant=entry["variant"],
                gate_pass=entry["gate_pass"],
                missing_provenance=missing_provenance,
                blockers=blockers,
                source=Path(entry["source_artifact"]).name,
            )
        )
    if report["skipped_artifacts"]:
        lines.extend(["", "## Skipped Artifacts", ""])
        lines.extend(f"- {row['path']}: {row['reason']}" for row in report["skipped_artifacts"])
    lines.extend(["", "## Next Forward Commands", ""])
    lines.extend(f"- `{command}`" for command in report["next_forward_commands"])
    lines.extend(["", "## Stop Conditions", ""])
    lines.extend(f"- {item}" for item in report["stop_conditions"])
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", type=Path, help="JSON artifact to include; repeatable")
    parser.add_argument("--forward-end", help="Render next forward commands with a concrete YYYY-MM-DD end date")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--print", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = args.artifact if args.artifact else default_artifacts()
    report = build_ledger(paths, forward_end=args.forward_end)
    args.json_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    args.json_output.expanduser().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.expanduser().write_text(report_to_markdown(report), encoding="utf-8")
    if args.print:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
