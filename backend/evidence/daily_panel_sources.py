"""Row-bound daily evidence after the frozen first One Loop window.

Stored inside the existing JobRun and committed panel, never a second ledger.
Missing inputs cannot become successful zero counts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.ops.run_envelope import select_complete_daily_run

EFFECTIVE_SINCE = "2026-09-16"
CONTRACT_VERSION = "daily_panel_sources.v1"


def _symbols(items: Any) -> set[str]:
    return {str(item["symbol"]) for item in (items or []) if isinstance(item, dict) and item.get("symbol")}


def previous_committed_panel(db, as_of: str) -> tuple[dict | None, str | None]:
    """Read only the previous price day's uniquely selected, committed panel."""
    day = db.execute(text("SELECT MAX(substr(date,1,10)) FROM prices WHERE substr(date,1,10) < :day"),
                     {"day": as_of}).scalar()
    if not day:
        return None, "no_previous_price_day"
    selection = select_complete_daily_run(db, as_of=day)
    if selection.get("status") != "selected":
        return None, f"previous_run_{selection.get('status', 'missing')}"
    row = selection.get("job_run")
    envelope = selection.get("run_envelope") or {}
    ref = getattr(row, "artifact_path", None)
    if not ref or not str(ref).endswith(".daily_panel.json"):
        return None, "previous_committed_panel_missing"
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored = payload.get("run_envelope") or {}
        cards = payload.get("cards") or []
        from backend.evidence.daily_panel import CARD_TYPES

        if (payload.get("schema_version") != "daily_panel.v1"
                or payload.get("ledger_commit_state") != "committed"
                or payload.get("as_of") != day
                or stored.get("run_id") != envelope.get("run_id")
                or stored.get("batch_id") != envelope.get("batch_id")
                or stored.get("status") != "complete"
                or [card.get("card_type") for card in cards] != list(CARD_TYPES)
                or any((card.get("run_ref") or {}).get("run_id") != envelope.get("run_id") for card in cards)):
            return None, "previous_panel_binding_invalid"
        return payload, None
    except (OSError, ValueError, AttributeError, TypeError):
        return None, "previous_panel_unreadable"


def bind_daily_sources(*, envelope: dict, workflow_result: dict | None,
                       postmarket: dict | None, previous: dict | None,
                       no_previous_reason: str | None = None) -> dict | None:
    day, run_id = envelope.get("as_of"), envelope.get("run_id")
    if not day or day < EFFECTIVE_SINCE or not run_id or envelope.get("status") != "complete":
        return None
    workflow = workflow_result or {}
    steps = workflow.get("steps") or []
    scans = [step for step in steps if isinstance(step, dict) and step.get("name") == "m60_watchtower"]
    scan = scans[0] if len(scans) == 1 else {}
    report = scan.get("result") or {}
    watch: dict[str, Any] = {"run_id": run_id, "as_of": day, "items": [], "status": "missing",
                             "reason": "本次运行没有可核对的同日观察哨结果。"}
    if (workflow.get("date") == day and scan.get("ok") is True
            and isinstance(report, dict) and report.get("as_of") == day):
        items = report.get("triggers") or []
        coverage = report.get("coverage") or {}
        complete = (coverage.get("status") == "complete" and not report.get("watchlist_errors")
                    and (report.get("summary") or {}).get("n_symbols_scanned", 0) > 0)
        watch.update(items=items, coverage=coverage, report=report,
                     status=("ready" if items else "ready_zero") if complete else "degraded",
                     reason=("本次清单扫描完成，没有触发；仅覆盖所列规则，不代表没有风险。" if complete and not items
                             else "本次清单扫描完成，触发项可供复核。" if complete
                             else "扫描已保存，但数据或清单覆盖不完整，不能据此判断无触发。"))
    delta: dict[str, Any] = {"current_as_of": day, "previous_as_of": (previous or {}).get("as_of"),
                             "status": "missing", "changes": [],
                             "no_previous_reason": no_previous_reason or "previous_committed_panel_missing",
                             "reason": "缺少上一交易日已提交面板，暂不能比较。"}
    if previous and previous.get("as_of", day) < day and postmarket:
        cards = {card["card_type"]: card for card in previous.get("cards", [])}
        if "candidate" in cards and "position_health" in cards:
            for card, source in (("candidate", "buy_candidates"), ("position", "position_health")):
                prior_key = "candidate" if card == "candidate" else "position_health"
                before = _symbols((cards[prior_key].get("payload") or {}).get("items"))
                after = _symbols((postmarket.get(source) or {}).get("items"))
                delta[f"{card}_added"] = sorted(after - before)
                delta[f"{card}_removed"] = sorted(before - after)
                delta["changes"].append({"field": f"{card}_count", "previous": len(before),
                                         "current": len(after), "delta": len(after) - len(before)})
            changed = any(delta[f"{key}_{action}"] for key in ("candidate", "position") for action in ("added", "removed"))
            delta.update(status="ready" if changed else "ready_zero", no_previous_reason=None,
                         previous_run_id=(previous.get("run_envelope") or {}).get("run_id"),
                         reason="比较已提交面板中的候选与持仓名单；不推断实际成交或收益。",
                         summary=f"候选新增 {len(delta['candidate_added'])}、移出 {len(delta['candidate_removed'])}；"
                                 f"持仓新增 {len(delta['position_added'])}、移出 {len(delta['position_removed'])}")
    coverage = (envelope.get("freshness") or {}).get("input_coverage") or {}
    return {"schema_version": CONTRACT_VERSION, "as_of": day, "run_id": run_id,
            "watchtower": watch, "daily_delta": delta, "llm_explicitly_disabled": coverage.get("llm_enabled") is False}


def apply_daily_sources(postmarket: dict | None, news: dict, source: dict | None,
                        envelope: dict) -> tuple[dict | None, dict]:
    if (not source or source.get("schema_version") != CONTRACT_VERSION
            or source.get("as_of", "") < EFFECTIVE_SINCE
            or source.get("as_of") != envelope.get("as_of")
            or source.get("run_id") != envelope.get("run_id") or envelope.get("status") != "complete"):
        return postmarket, news
    # Do not manufacture candidate/position availability when the base failed.
    panel = {**postmarket, "watchtower_followups": source["watchtower"], "daily_delta": source["daily_delta"]} if postmarket is not None else None
    if source.get("llm_explicitly_disabled") and news.get("status") != "ready":
        news = {**news, "status": "not_applicable",
                "reason": "本次日跑明确关闭 LLM，新闻影子分析未执行；不能解释为没有事件风险。"}
    return panel, news
