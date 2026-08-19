"""Outcome-backed memory summaries for live research prompts.

The module deliberately turns many low-level outcome rows into a small,
auditable calibration block.  It never changes a signal or position directly.
"""
from __future__ import annotations

import json
from statistics import mean
from typing import Any

from sqlalchemy import text

from backend.decision.signal_policy import is_entry_signal

_HORIZONS = ("10d", "5d", "3d", "1d")


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _outcome_metric(evidence: dict[str, Any]) -> tuple[str, float, str] | None:
    excess = evidence.get("excess_returns")
    raw = evidence.get("returns")
    values = excess if isinstance(excess, dict) and excess else raw
    if not isinstance(values, dict):
        return None
    basis = "相对沪深300" if values is excess else "绝对收益"
    for horizon in _HORIZONS:
        value = values.get(horizon)
        if isinstance(value, (int, float)):
            return horizon, float(value), basis
    return None


def build_outcome_calibration(db, *, symbol: str, limit: int = 200) -> dict[str, Any]:
    """Return a compact per-symbol calibration summary from validated outcomes.

    Historical reruns can create several judgments for the same symbol-day.
    They are one market observation, not independent evidence, so only the
    newest outcome for each decision day and action class is counted.
    """
    target_limit = max(1, min(500, int(limit)))
    rows = db.execute(text("""
        SELECT id, evidence_json
        FROM stock_memory_items
        WHERE symbol = :symbol
          AND memory_type = 'outcome'
          AND status = 'validated'
        ORDER BY updated_at DESC, id DESC
    """), {"symbol": symbol}).all()

    groups: dict[str, list[tuple[str, float, str]]] = {"entry": [], "non_entry": []}
    used_ids: list[int] = []
    seen_observations: set[tuple[str, str]] = set()
    for row in rows:
        evidence = _json_dict(row.evidence_json)
        metric = _outcome_metric(evidence)
        if metric is None:
            continue
        recommendation = str(evidence.get("recommendation") or "")
        key = "entry" if is_entry_signal(recommendation, include_legacy=True) else "non_entry"
        judgment = evidence.get("judgment_evidence")
        judgment = judgment if isinstance(judgment, dict) else {}
        decision_date = str(judgment.get("date") or "")[:10]
        observation_key = (decision_date, key)
        if decision_date and observation_key in seen_observations:
            continue
        if decision_date:
            seen_observations.add(observation_key)
        groups[key].append(metric)
        used_ids.append(int(row.id))
        if len(used_ids) >= target_limit:
            break

    lines: list[str] = []
    labels = {"entry": "入场类判断", "non_entry": "非入场类判断"}
    for key in ("entry", "non_entry"):
        samples = groups[key]
        if not samples:
            continue
        values = [item[1] for item in samples]
        horizons = {item[0] for item in samples}
        bases = {item[2] for item in samples}
        hit_count = sum(value > 0 for value in values) if key == "entry" else sum(
            value <= 0 for value in values
        )
        horizon = next(iter(horizons)) if len(horizons) == 1 else "最长可用窗口"
        basis = next(iter(bases)) if len(bases) == 1 else "优先相对沪深300"
        sample_note = "；样本不足，仅作提示" if len(values) < 5 else ""
        lines.append(
            f"- {labels[key]}：n={len(values)}，{horizon}{basis}平均{mean(values):+.2f}%，"
            f"兑现率{hit_count / len(values) * 100:.1f}%，最差{min(values):+.2f}%{sample_note}"
        )

    if not lines:
        return {"text": "", "memory_ids": [], "sample_count": 0}
    return {
        "text": (
            "【历史结果校准（只作研究先验，不直接改变信号）】\n"
            + "\n".join(lines)
        ),
        "memory_ids": used_ids,
        "sample_count": len(used_ids),
    }
