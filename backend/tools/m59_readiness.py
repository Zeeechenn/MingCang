"""D0 entry readiness score: transparent evidence checklist aggregation, not prediction.

The score is a hard-coded, non-trained point ledger over visible evidence. It is
not a predictive model and must not be used as a full-universe ranking signal.
It is calculated only for candidate/trigger moments. Threshold wording must pass
the historical calibration gate first; when calibration fails or is missing, UI
surfaces only the evidence checklist and hides probability language.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import default_sqlite_path
from backend.data.fundamentals import compute_piotroski_factors

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CALIBRATION_PATH = REPO_ROOT / "paper_trading" / "m58_out" / "arena" / "readiness_calibration.json"
DEFAULT_TRIGGER_HISTORY_PATH = Path.home() / ".mingcang" / "m63_trigger_history.json"
DEFAULT_BINS = (0.0, 25.0, 50.0, 70.0, 100.0)

POSITIVE_LONG_TERM_LABELS = {"值得持有", "观望"}
LONG_TERM_VETO_LABELS = {"规避", "估值偏高"}
NEGATIVE_COPILOT_STANCES = {"谨慎", "反对", "负向", "看空", "不支持"}


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None and hasattr(row, "keys") else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)[:10]
    return text if text else None


def _days_between(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None
    try:
        return (datetime.fromisoformat(right[:10]) - datetime.fromisoformat(left[:10])).days
    except ValueError:
        return None


def _latest_long_term_label(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "long_term_labels"):
        return None
    cols = _columns(con, "long_term_labels")
    if "symbol" not in cols:
        return None
    date_col = next((col for col in ("date", "as_of", "created_at") if col in cols), None)
    if date_col is None:
        return None
    select_cols = list(cols)
    # 过期标签不参与打分/否决——与 m59_panel/m63_daily 的 expires_at 口径对齐(跨模块审计 P1)
    expiry_clause = (
        " AND (expires_at IS NULL OR substr(expires_at, 1, 10) >= ?)" if "expires_at" in cols else ""
    )
    params: tuple[Any, ...] = (symbol, as_of, as_of) if expiry_clause else (symbol, as_of)
    row = con.execute(
        f"""
        SELECT {', '.join(select_cols)}
        FROM long_term_labels
        WHERE symbol = ? AND substr({date_col}, 1, 10) <= ?{expiry_clause}
        ORDER BY {date_col} DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(select_cols, row, strict=False))


def _latest_copilot(con: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
    if not _table_exists(con, "research_states") or not {"symbol", "copilot_json"} <= _columns(con, "research_states"):
        return None
    row = con.execute(
        "SELECT copilot_json FROM research_states WHERE symbol = ? AND copilot_json IS NOT NULL ORDER BY rowid DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    try:
        raw = row["copilot_json"] if hasattr(row, "keys") else row[0]
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _piotroski_norm(piotroski: dict[str, Any] | None) -> float | None:
    if not piotroski or not piotroski.get("available"):
        return None
    score = _to_float(piotroski.get("score"))
    denom = _to_float(piotroski.get("score_denominator"))
    if score is None or denom is None or denom == 0:
        return None
    return score / denom


def _compute_piotroski(symbol: str, db_session: Any | None, explicit: dict[str, Any] | None) -> dict[str, Any] | None:
    if explicit is not None:
        return explicit
    if db_session is None:
        return None
    try:
        return compute_piotroski_factors(symbol, db_session)
    except Exception:
        return None


def _theme_key(statement: str | None) -> str | None:
    if not statement or not statement.startswith("[theme:"):
        return None
    end = statement.find("]")
    if end <= len("[theme:"):
        return None
    return statement[len("[theme:") : end]


def _active_forward_theses(con: sqlite3.Connection, symbol: str, themes: Sequence[str] = ()) -> list[dict[str, Any]]:
    if not _table_exists(con, "forward_theses"):
        return []
    cols = _columns(con, "forward_theses")
    if "status" not in cols or "statement" not in cols:
        return []
    select_cols = list(cols)
    rows = con.execute(f"SELECT {', '.join(select_cols)} FROM forward_theses WHERE status = 'active'").fetchall()
    theme_set = {str(item) for item in themes if item}
    matched = []
    for row in rows:
        data = dict(row) if hasattr(row, "keys") else dict(zip(select_cols, row, strict=False))
        row_symbol = data.get("symbol") if "symbol" in cols else None
        key = _theme_key(str(data.get("statement") or ""))
        if row_symbol == symbol or (key and key in theme_set):
            matched.append(data)
    return matched


def _recent_trigger_counts(con: sqlite3.Connection, symbol: str, as_of: str, themes: Sequence[str] = ()) -> dict[str, int]:
    counts = {"any": 0, "thesis_validation": 0, "thesis_invalidation": 0}
    if not _table_exists(con, "m60_watchtower_trigger_history"):
        return counts
    cols = _columns(con, "m60_watchtower_trigger_history")
    if not {"date", "target", "trigger_type"} <= cols:
        return counts
    targets = {symbol, *[str(item) for item in themes if item]}
    rows = con.execute(
        """
        SELECT date, target, trigger_type
        FROM m60_watchtower_trigger_history
        WHERE date(date) >= date(?, '-30 day') AND date(date) <= date(?)
        """,
        (as_of, as_of),
    ).fetchall()
    for row in rows:
        data = dict(row) if hasattr(row, "keys") else {"date": row[0], "target": row[1], "trigger_type": row[2]}
        target = str(data["target"])
        if target not in targets:
            continue
        trigger_type = str(data["trigger_type"] or "")
        days_between = _days_between(str(data["date"])[:10], as_of)
        if days_between is not None and days_between <= 5:
            counts["any"] += 1
        if trigger_type == "thesis_validation":
            counts["thesis_validation"] += 1
        elif trigger_type == "thesis_invalidation":
            counts["thesis_invalidation"] += 1
    return counts


def _regime_value(market_regime: dict[str, Any] | None) -> str | None:
    value = (market_regime or {}).get("value") or (market_regime or {}).get("regime")
    return str(value) if value is not None else None


def _band(score: int, calibration: dict[str, Any]) -> dict[str, Any]:
    if score < 25:
        rng, label = "<25", "观望"
    elif score < 50:
        rng, label = "25-50", "可小仓试错"
    elif score < 70:
        rng, label = "50-70", "加强关注"
    else:
        rng, label = ">=70", "高准备度"
    return {"range": rng, "label": label, "calibration_status": calibration.get("status", "not_loaded")}


def load_calibration(path: Path | None = None) -> dict[str, Any]:
    resolved = path or DEFAULT_CALIBRATION_PATH
    if not resolved.exists():
        return {"status": "not_loaded", "path": str(resolved)}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "path": str(resolved), "error": exc.__class__.__name__}
    status = "pass" if payload.get("gate_status") == "pass" else "fail"
    return {"status": status, "path": str(resolved), "payload": payload}


def build_readiness(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    entry_card: dict[str, Any] | None = None,
    db_session: Any | None = None,
    piotroski: dict[str, Any] | None = None,
    market_regime: dict[str, Any] | None = None,
    themes: Sequence[str] = (),
    calibration_path: Path | None = None,
) -> dict[str, Any]:
    evidence: list[str] = []
    missing: list[str] = []
    vetoes: list[str] = []
    dims = {"research": 0, "thesis": 0, "environment": 0, "execution": 0}

    label = _latest_long_term_label(con, symbol, as_of)
    label_text = str((label or {}).get("label") or "")
    if label_text in LONG_TERM_VETO_LABELS:
        vetoes.append("长期标签否决")
    elif label_text in POSITIVE_LONG_TERM_LABELS:
        dims["research"] += 10
        evidence.append(f"研究维+10:长期标签={label_text}")
        label_day = _date_text((label or {}).get("date") or (label or {}).get("as_of") or (label or {}).get("created_at"))
        age = _days_between(label_day, as_of)
        if age is not None and age <= 14:
            dims["research"] += 5
            evidence.append(f"研究维+5:长期标签新鲜({label_day})")
        else:
            missing.append("长期标签新鲜度")
    else:
        missing.append("长期标签")

    p = _compute_piotroski(symbol, db_session, piotroski)
    p_norm = _piotroski_norm(p)
    if p_norm is not None and p_norm >= 0.55 and not vetoes:
        dims["research"] += 10
        evidence.append(f"研究维+10:Piotroski归一分={p_norm:.2f}")
    elif p_norm is None:
        missing.append("Piotroski")

    copilot = _latest_copilot(con, symbol)
    stance = str((copilot or {}).get("stance") or "")
    if copilot is None:
        missing.append("copilot")
    elif stance not in NEGATIVE_COPILOT_STANCES and not vetoes:
        dims["research"] += 10
        evidence.append(f"研究维+10:copilot stance={stance or '非负向'}")
    if "长期标签否决" in vetoes:
        dims["research"] = 0

    thesis_rows = _active_forward_theses(con, symbol, themes)
    thesis_themes = [_theme_key(str(row.get("statement") or "")) for row in thesis_rows]
    all_themes = sorted({*themes, *[theme for theme in thesis_themes if theme]})
    triggers = _recent_trigger_counts(con, symbol, as_of, all_themes)
    if triggers["thesis_invalidation"] > 0:
        vetoes.append("论点证伪警报")
        dims["thesis"] = 0
    else:
        if thesis_rows:
            dims["thesis"] += 10
            evidence.append("论点维+10:active forward_thesis命中")
        else:
            missing.append("active forward_thesis")
        if triggers["thesis_validation"] >= 1:
            dims["thesis"] += 15
            evidence.append(f"论点维+15:近30日thesis_validation={triggers['thesis_validation']}")
        else:
            missing.append("论点触发")
        dims["thesis"] += 5
        evidence.append("论点维+5:近30日thesis_invalidation=0")

    regime = _regime_value(market_regime)
    if regime == "up":
        dims["environment"] = 15
        evidence.append("环境维+15:regime=up")
    elif regime == "flat":
        dims["environment"] = 8
        evidence.append("环境维+8:regime=flat")
    elif regime == "down":
        evidence.append("环境维+0:regime=down")
    else:
        missing.append("regime")

    if triggers["any"] >= 1:
        dims["execution"] += 8
        evidence.append("执行维+8:近5交易日触发器命中")
    else:
        missing.append("近5交易日触发器")
    if (entry_card or {}).get("status") == "ok":
        dims["execution"] += 6
        evidence.append("执行维+6:entry_card status=ok")
        if _to_float((entry_card or {}).get("atr14")) is not None:
            dims["execution"] += 6
            evidence.append("执行维+6:ATR可算风险预算")
        else:
            missing.append("ATR风险预算")
    else:
        missing.append("entry_card")
        missing.append("ATR风险预算")

    score = min(100, int(sum(dims.values())))
    calibration = load_calibration(calibration_path)
    return {
        "score": score,
        "band": _band(score, calibration),
        "dims": dims,
        "evidence": evidence,
        "missing": sorted(set(missing)),
        "vetoes": vetoes,
        "calibration": calibration,
    }


def _bin_for_score(score: float, rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        label = str(row.get("bin") or "")
        if not label.startswith("["):
            continue
        left_text, right_text = label.strip("[]()").split(",", 1)
        left = float(left_text)
        right = float(right_text)
        include_right = label.endswith("]")
        if score >= left and (score <= right if include_right else score < right):
            return row
    return None


def render_readiness_line(report: dict[str, Any]) -> str:
    band = report.get("band") or {}
    missing = report.get("missing") or []
    calibration = report.get("calibration") or {}
    if band.get("calibration_status") == "pass":
        if not (calibration.get("payload") or {}).get("bins"):
            calibration = load_calibration()
        payload = calibration.get("payload") or {}
        row = _bin_for_score(float(report.get("score") or 0), payload.get("bins") or [])
        if row:
            pct = round(float(row.get("win_rate") or 0) * 100, 1)
            cal_text = f"历史频率:该分段{row.get('sample_count')}笔胜率{pct}%"
        else:
            cal_text = "校准:已通过"
    else:
        cal_text = "校准:未通过,仅清单"
    missing_text = ",".join(str(item) for item in missing[:4]) if missing else "-"
    return (
        f"入场准备度 {report.get('score')}/100 "
        f"[{band.get('range')}:{band.get('label')}|{cal_text}] 缺:{missing_text}"
    )


def readiness_score_for_arena_case(case: Any) -> float | None:
    inputs = case.inputs if hasattr(case, "inputs") else (case.get("inputs") or {})
    score = 0
    label = inputs.get("long_term_label") or {}
    label_text = str(label.get("label") or "")
    if label_text in LONG_TERM_VETO_LABELS:
        research = 0
    else:
        research = 10 if label_text in POSITIVE_LONG_TERM_LABELS else 0
        label_age_days = _days_between(
            _date_text(label.get("date") or label.get("as_of") or label.get("created_at")),
            str(inputs.get("pit_as_of") or ""),
        )
        if research and label_age_days is not None:
            if label_age_days <= 14:
                research += 5
    score += research
    thesis = inputs.get("forward_thesis") or {}
    if str(thesis.get("status") or "") == "active":
        score += 15
    trigger = inputs.get("trigger") or {}
    trigger_type = str((trigger.get("payload") or {}).get("trigger_type") or trigger.get("source") or "")
    if trigger_type == "thesis_validation":
        score += 15
    elif trigger_type == "thesis_invalidation":
        score -= 15
    price = inputs.get("price") or {}
    if price:
        score += 6
        if _to_float(price.get("atr14")) is not None:
            score += 6
    if trigger:
        score += 8
    return float(max(0, min(100, score)))


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    from backend.tools.m58_entry_arena import _spearman as arena_spearman

    result = arena_spearman(xs, ys)
    return result.get("rho")


def evaluate_calibration_gates(window_reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    per_window = []
    for report in window_reports:
        rows = report.get("bins") or []
        usable = [(idx, row) for idx, row in enumerate(rows) if row.get("win_rate") is not None]
        rates = [float(row["win_rate"]) for _, row in usable]
        mono = all(rates[idx] <= rates[idx + 1] for idx in range(len(rates) - 1)) if rates else False
        rho = _spearman([float(idx) for idx, _ in usable], rates) if len(usable) >= 2 else None
        sample_ok = all(int(row.get("sample_count") or 0) >= 30 for row in rows)
        per_window.append({"monotonic": mono and rho is not None and rho > 0, "rho": rho, "sample_ok": sample_ok})
    cross_ok = False
    if len(window_reports) >= 2:
        left = window_reports[0].get("bins") or []
        right = window_reports[1].get("bins") or []
        diffs: list[float | None] = []
        for lrow, rrow in zip(left, right, strict=False):
            if lrow.get("win_rate") is None or rrow.get("win_rate") is None:
                diffs.append(None)
            else:
                diffs.append(abs(float(lrow["win_rate"]) - float(rrow["win_rate"])))
        cross_ok = bool(diffs) and all(diff is not None and diff < 0.15 for diff in diffs)
    monotonic_ok = all(item["monotonic"] for item in per_window)
    sample_ok = all(item["sample_ok"] for item in per_window)
    return {
        "monotonic": {"pass": monotonic_ok, "windows": per_window},
        "sample": {"pass": sample_ok},
        "cross_period": {"pass": cross_ok},
    }


def _render_calibration_md(report: dict[str, Any]) -> str:
    lines = [
        "# D0 Readiness Calibration",
        "",
        f"- gate_status: {report.get('gate_status')}",
        f"- generated_at: {report.get('generated_at')}",
        f"- bins: {report.get('bin_edges')}",
        "",
        "## Gates",
    ]
    for name, gate in (report.get("gates") or {}).items():
        lines.append(f"- {name}: {gate.get('pass')}")
    for window in report.get("windows") or []:
        lines.extend(["", f"## {window.get('name')}", "| bin | n | win_rate | status |", "|---|---:|---:|---|"])
        for row in window.get("bins") or []:
            lines.append(f"| {row.get('bin')} | {row.get('sample_count')} | {row.get('win_rate')} | {row.get('sample_status')} |")
    return "\n".join(lines) + "\n"


def run_readiness_calibration(
    *,
    db_path: str | Path,
    out_dir: Path = DEFAULT_CALIBRATION_PATH.parent,
    universe: Sequence[str] | None = None,
    sample_rate: float = 0.35,
    random_seed: int = 58,
    windows: Sequence[tuple[str, str, str]] = (("2024H2", "2024-07-01", "2024-12-31"), ("2025H1", "2025-01-01", "2025-06-30")),
) -> dict[str, Any]:
    from backend.tools import m58_entry_arena as arena

    reports = []
    with arena.connect_readonly(db_path) as con:
        resolved_universe = list(universe or arena._available_symbols(con))
        for idx, (name, start, end) in enumerate(windows):
            triggers = arena.synthetic_sweep_triggers(
                con,
                universe=resolved_universe,
                start=start,
                end=end,
                sample_rate=sample_rate,
                seed=random_seed + idx,
            )
            history = arena.load_history_triggers()
            history = [point for point in history if start <= point.as_of <= end]
            triggers = [*triggers, *history]
            batch = arena.build_arena_batch(
                db_path=db_path,
                triggers=triggers,
                universe=resolved_universe,
                horizons=(5,),
                random_seed=random_seed + idx,
            )
            cases = [arena.ArenaCase(**case) for case in batch.get("cases") or []]
            calibration = arena.calibrate(cases, readiness_score_for_arena_case, bins=DEFAULT_BINS, horizon="d5")
            calibration["name"] = name
            calibration["start"] = start
            calibration["end"] = end
            calibration["case_count"] = len(cases)
            reports.append(calibration)
    gates = evaluate_calibration_gates(reports)
    gate_status = "pass" if all(gate.get("pass") for gate in gates.values()) else "fail"
    combined_bins = reports[-1].get("bins") if reports else []
    report = {
        "schema_version": "m59_readiness.calibration.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "score_fn": "backend.tools.m59_readiness.readiness_score_for_arena_case",
        "gate_status": gate_status,
        "gates": gates,
        "bin_edges": list(DEFAULT_BINS),
        "bins": combined_bins,
        "windows": reports,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "readiness_calibration.json"
    md_path = out_dir / "readiness_calibration.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_calibration_md(report), encoding="utf-8")
    report["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    return report


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _open_session(db_path: Path):
    engine = create_engine(f"sqlite:///file:{db_path.resolve()}?mode=ro&uri=true", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    return engine, Session()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build D0 entry readiness score or calibration report.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--symbol")
    mode.add_argument("--calibrate", action="store_true")
    parser.add_argument("--as-of")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "line"), default="json")
    parser.add_argument("--sample-rate", type=float, default=0.35)
    args = parser.parse_args(argv)

    db_path = args.db or default_sqlite_path()
    if args.calibrate:
        report = run_readiness_calibration(db_path=db_path, sample_rate=args.sample_rate)
        print(json.dumps({"gate_status": report["gate_status"], "paths": report["paths"], "gates": report["gates"]}, ensure_ascii=False, indent=2))
        return 0

    if not args.as_of:
        parser.error("--symbol requires --as-of")
    engine, session = _open_session(db_path)
    try:
        with _connect_readonly(db_path) as con:
            from backend.tools.m59_entry_card import build_entry_card

            entry_card = build_entry_card(str(args.symbol), args.as_of, con)
            report = build_readiness(
                con,
                symbol=str(args.symbol),
                as_of=args.as_of,
                db_session=session,
                entry_card=entry_card,
            )
    finally:
        session.close()
        engine.dispose()
    print(render_readiness_line(report) if args.format == "line" else json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
