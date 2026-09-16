#!/usr/bin/env python3
"""Collect read-only decision-desk quality evidence into an exclusive external directory.

No model calls, production writes, historical repairs or trading execution. The
generated raw/desk requests are for factual-quality diagnostics, not NAV trials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.evidence.decision_desk_readiness import build_readiness_report  # noqa: E402
from backend.ops.one_loop_continuity import audit_one_loop_continuity  # noqa: E402
from backend.tools.p0r_nav_replay import build_evidence  # noqa: E402
from scripts.sqlite_consistent_snapshot import snapshot_sqlite  # noqa: E402

SH = ZoneInfo("Asia/Shanghai")
PROMPT = """You are assessing evidence quality in a research-only experiment.
Use only the JSON evidence supplied below. Do not use tools, outside knowledge,
other experiments, or private memory. Do not recommend trades or price targets.
Identify important unavailable, stale, future, conflicting or unsupported facts.
Unknown holdings do not mean zero holdings. Scores are not probabilities.
Return one JSON object with keys: gaps (list of {symbol, issue, evidence_ref}),
unsupported_claims (list), can_make_investment_decision (boolean), and rationale.
Cite evidence_ref values supplied in the input. Never invent missing figures.
"""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def visible(value: Any, cutoff: datetime) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
        # MingCang SQLite timestamps without an offset are stored in UTC.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed <= cutoff
    except ValueError:
        return False


def collect_inputs(snapshot: Path, universe: dict[str, Any], as_of: str,
                   cutoff: datetime, batch_id: str | None) -> tuple[dict, dict, dict]:
    common, derived = [], []
    gaps = []
    uri = f"file:{quote(str(snapshot), safe='/')}?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for stock in universe["stocks"]:
            symbol = stock["symbol"]
            prices = [dict(r) for r in connection.execute(
                "SELECT date,open,high,low,close,volume,source,adjustment,fetched_at "
                "FROM prices WHERE symbol=? AND market='CN' AND date<=? ORDER BY date DESC LIMIT 5",
                (symbol, as_of),
            ) if visible(r["fetched_at"], cutoff)]
            rows = connection.execute(
                "SELECT report_date,period_type,revenue,net_profit,operating_cf,roe,"
                "disclosure_date,fetched_at,source FROM financial_metrics "
                "WHERE symbol=? AND report_date<=? ORDER BY report_date DESC,id DESC",
                (symbol, as_of),
            ).fetchall()
            financial = next((dict(r) for r in rows if r["disclosure_date"]
                              and str(r["disclosure_date"])[:10] <= as_of
                              and visible(r["fetched_at"], cutoff)), None)
            item_gaps = []
            if not prices or prices[0]["date"] != as_of:
                item_gaps.append("no_visible_price_on_requested_day")
            if financial is None:
                item_gaps.append("no_visible_financial_report")
            elif (date.fromisoformat(as_of) - date.fromisoformat(financial["report_date"])).days > 120:
                item_gaps.append("financial_report_period_over_120_days_old")
            if item_gaps:
                gaps.append({"symbol": symbol, "gaps": item_gaps})
            common.append({"evidence_ref": f"source:{symbol}", "symbol": symbol,
                           "name": stock.get("name"), "prices": prices,
                           "financial": financial, "data_gaps": item_gaps})
            label_rows = connection.execute(
                "SELECT date,label,score,expires_at,created_at,quality FROM long_term_labels "
                "WHERE symbol=? AND date<=? AND expires_at>=? ORDER BY date DESC,id DESC",
                (symbol, as_of, as_of),
            ).fetchall()
            label = next((dict(r) for r in label_rows if visible(r["created_at"], cutoff)), None)
            signals = [dict(r) for r in connection.execute(
                "SELECT symbol,composite_score,stop_loss,take_profit FROM signals WHERE symbol=? AND date=?",
                (symbol, batch_id),
            )] if batch_id else []
            derived.append({"evidence_ref": f"desk:{symbol}", "symbol": symbol,
                            "label": label, "official_signals": signals})
    return (
        {"as_of": as_of, "cutoff": cutoff.isoformat(), "holdings": "unknown",
         "stocks": common, "memory": [], "purpose": "factual_quality_only"},
        {"stocks": derived, "memory": [], "source": "MingCang explicit snapshot reads"},
        {"symbols": len(common), "gaps": gaps, "cutoff": cutoff.isoformat(),
         "historical_revision_certified": False, "price_history_certified": False},
    )


def collect(*, source_db: Path, repo_root: Path, output_dir: Path,
            universe_path: Path, as_of: str) -> dict[str, Any]:
    target_day = date.fromisoformat(as_of)
    now = datetime.now(UTC)
    if target_day > now.astimezone(SH).date():
        raise ValueError("future as_of rejected")
    root, output = repo_root.resolve(), output_dir.resolve()
    if output == root or root in output.parents:
        raise ValueError("output_dir must be outside the live repository")
    if output == PROJECT_ROOT or PROJECT_ROOT in output.parents:
        raise ValueError("output_dir must be outside the implementation repository")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = snapshot_sqlite(source_db, output / "snapshot.db")
    before = sha(snapshot)
    continuity = audit_one_loop_continuity(db_path=snapshot, repo_root=root)
    write_json(output / "continuity.json", continuity)
    selected = next((d for d in continuity["days"] if d["date"] == as_of), {})
    panel: dict[str, Any] = {}
    for artifact in selected.get("artifacts", []):
        source = Path(artifact).resolve()
        if root not in source.parents:
            raise ValueError("artifact outside repo_root")
        if source.name.endswith(".daily_panel.json"):
            data = source.read_bytes()
            panel = json.loads(data)
            (output / "panel.json").write_bytes(data)
    nav = build_evidence(snapshot, repo_root=root, end=as_of, continuity_result=continuity)
    write_json(output / "nav.json", nav)
    report = build_readiness_report(as_of=as_of, continuity=continuity, panel=panel, nav_evidence=nav)
    universe_bytes = universe_path.read_bytes()
    (output / "universe.json").write_bytes(universe_bytes)
    common, derived, data_quality = collect_inputs(
        snapshot, json.loads(universe_bytes), as_of, now, selected.get("batch_id"),
    )
    write_json(output / "common_evidence.json", common)
    write_json(output / "desk_evidence.json", derived)
    write_json(output / "input_quality.json", data_quality)
    for arm in ("raw", "desk"):
        request = {"instructions": PROMPT, "common_evidence": common}
        if arm == "desk":
            request["mingcang_evidence"] = derived
        write_json(output / f"{arm}_request.json", request)
    report["input_quality"] = data_quality
    report["prospective_collection"] = target_day == now.astimezone(SH).date()
    report["collected_at"] = now.isoformat()
    report["model_calls"] = 0
    report["snapshot_sha256"] = before
    if before != sha(snapshot):
        raise RuntimeError("snapshot changed during collection")
    write_json(output / "readiness.json", report)
    files = {p.name: sha(p) for p in output.iterdir() if p.is_file()}
    write_json(output / "manifest.json", {
        "as_of": as_of, "collected_at": now.isoformat(), "sha256": files,
        "snapshot_unchanged": True, "source_db": str(source_db.resolve()),
        "writes_production": False, "provider_called": False,
        "scope": "quality_collection_not_economic_trial",
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    report = collect(source_db=args.source_db, repo_root=args.repo_root,
                     output_dir=args.output_dir, universe_path=args.universe, as_of=args.as_of)
    print(json.dumps({"as_of": args.as_of, "gates": report["gates"],
                      "output_dir": str(args.output_dir), "model_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
