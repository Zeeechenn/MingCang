"""M63-2 on-demand full-stack research CLI (随时式).

This module owns the manual research command.  It deliberately does not edit
or hook ``backend.tools.m63_daily``: the daily R4 stub remains inert there, and
opinion-triggered R4 queue entries are produced directly by
``backend.tools.m63_opinion``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.data import category_backfill as m61_backfill
from backend.research.watchlist import (
    WATCHLIST_DIR,
    load_watchlists,
    validate_watchlist_entry,
)
from backend.workflows.m63_daily import DEFAULT_QUEUE_PATH, load_queue, save_queue
from backend.workflows.render import enforce_language_guard, render_report, strip_raw_json

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "paper_trading" / "m63_out"
DEFAULT_UNIVERSE_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "paper_trading" / "biaodi1_universe.json",
    REPO_ROOT / "paper_trading" / "test2_universe.json",
)
BACKFILL_CATEGORIES = ("announcements", "corporate_events", "research_reports", "holders", "lhb", "fund_flow")


class TargetResolutionError(RuntimeError):
    """Raised when a theme cannot be mapped to symbols without guessing."""


def _today() -> str:
    return date.today().isoformat()


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", text, flags=re.UNICODE).strip("_")
    return cleaned[:48] or "research"


def _symbols_arg(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_universe_entries(paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in payload.get("stocks", []):
            symbol = str(item.get("symbol") or "").strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            entries.append(
                {
                    "symbol": symbol,
                    "name": str(item.get("name") or symbol).strip(),
                    "sector": str(item.get("sector") or "").strip(),
                }
            )
    return entries


def _name_by_symbol(symbols: list[str]) -> dict[str, str]:
    universe = {item["symbol"]: item["name"] for item in _load_universe_entries()}
    return {symbol: universe.get(symbol, symbol) for symbol in symbols}


def resolve_target(
    target: str,
    *,
    symbols: list[str] | None = None,
    watchlist_dir: Path | str | None = None,
    universe_paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS,
) -> dict[str, Any]:
    clean_target = target.strip()
    explicit_symbols = [s.strip() for s in (symbols or []) if s.strip()]
    resolved_watchlist_dir = Path(watchlist_dir) if watchlist_dir is not None else WATCHLIST_DIR
    if re.fullmatch(r"\d{6}", clean_target):
        return {
            "target": clean_target,
            "target_type": "symbol",
            "theme_key": clean_target,
            "title": clean_target,
            "symbols": [clean_target],
            "source": "symbol",
            "coverage": {"scope": "single_symbol", "listed_count": 1, "full_market": False},
        }
    if explicit_symbols:
        return {
            "target": clean_target,
            "target_type": "theme",
            "theme_key": _slug(clean_target),
            "title": clean_target,
            "symbols": explicit_symbols,
            "source": "--symbols",
            "coverage": {"scope": "explicit_user_list", "listed_count": len(set(explicit_symbols)), "full_market": False},
        }

    entries, _errors = load_watchlists(resolved_watchlist_dir, authoritative_thesis=False)
    target_norm = clean_target.lower()
    for entry in entries:
        theme_key = str(entry.get("theme_key") or "")
        title = str(entry.get("title") or "")
        if target_norm in {theme_key.lower(), title.lower()} or clean_target in title:
            return {
                "target": clean_target,
                "target_type": "theme",
                "theme_key": theme_key,
                "title": title,
                "symbols": list(entry["symbols"]),
                "source": "watchlist",
                "watchlist_entry": entry,
                "coverage": {
                    "scope": "watchlist_membership",
                    "listed_count": len(set(entry["symbols"])),
                    "full_market": False,
                    "watchlist_file": str(_watchlist_path(theme_key, resolved_watchlist_dir)),
                },
            }

    universe_entries = _load_universe_entries(universe_paths)
    matched: list[str] = []
    for item in universe_entries:
        if clean_target in item.get("sector", ""):
            matched.append(item["symbol"])
    if matched:
        return {
            "target": clean_target,
            "target_type": "theme",
            "theme_key": _slug(clean_target),
            "title": clean_target,
            "symbols": matched,
            "source": "universe_sector",
            "coverage": {
                "scope": "local_universe_sector_substring",
                "listed_count": len(set(matched)),
                "classified_local_universe_count": len(universe_entries),
                "source_files": [str(path) for path in universe_paths if path.exists()],
                "full_market": False,
            },
        }

    raise TargetResolutionError(
        f"无法解析主题“{clean_target}”: 观察哨主题和 biaodi1/test2 sector 均未匹配。请显式提供 --symbols。"
    )


def _resolve_from_local_stock_industry(target: str) -> dict[str, Any] | None:
    """Fallback to tracked Stock.industry metadata; this is not a full universe."""
    topic = str(target).strip()
    if len(topic) < 2:
        return None
    try:
        with _connect() as con:
            required = {"symbol", "name", "industry", "market", "active"}
            if not _table_exists(con, "stocks") or not required <= _columns(con, "stocks"):
                return None
            rows = con.execute(
                "SELECT symbol, name, industry FROM stocks "
                "WHERE market='CN' AND active=1 AND industry LIKE ? ORDER BY symbol",
                (f"%{topic}%",),
            ).fetchall()
    except sqlite3.Error:
        return None
    members = [dict(row) for row in rows if str(row["symbol"] or "").isdigit()]
    symbols = list(dict.fromkeys(str(row["symbol"]) for row in members))
    if not symbols:
        return None
    return {
        "target": topic,
        "target_type": "theme",
        "theme_key": _slug(topic),
        "title": topic,
        "symbols": symbols,
        "source": "local_stock_industry_unversioned",
        "coverage": {
            "scope": "tracked_stock_industry_subset",
            "listed_count": len(symbols),
            "full_market": False,
            "membership_as_of": "current local metadata; historical membership unverified",
            "source_files": ["stocks.industry"],
        },
    }


def build_research_preflight(
    target: dict[str, Any], *, no_llm: bool = False, auto: bool = False
) -> dict[str, Any]:
    """Describe the existing manual stages without starting any of them."""
    submitted = list(target["symbols"])
    normalized = list(dict.fromkeys(submitted))
    counts = Counter(submitted)
    duplicates = [symbol for symbol in normalized if counts[symbol] > 1]
    invalid = [symbol for symbol in normalized if not re.fullmatch(r"\d{6}", symbol)]
    copilot_slots = submitted[:8]
    warnings = []
    if duplicates:
        warnings.append("duplicate_symbols_default_run_repeats_stage_work")
    if len(submitted) > 8:
        warnings.append("copilot_default_run_covers_only_first_eight_occurrences")
    if invalid:
        warnings.append("invalid_symbol_format")
    if len(normalized) > 8:
        warnings.append("full_market_or_large_batch_requires_separate_capacity_contract")
    return {
        "schema_version": "m63_research_preflight.v1",
        "status": "preflight_only_no_execution",
        "scope": "manual_target_not_full_market_scan",
        "target": target["target"],
        "target_type": target["target_type"],
        "source": target["source"],
        "default_run_behavior_changed": False,
        "submitted_symbols": submitted,
        "normalized_unique_symbols": normalized,
        "submitted_count": len(submitted),
        "unique_count": len(normalized),
        "duplicate_symbols": duplicates,
        "invalid_symbols": invalid,
        "stages_on_default_run": {
            "backfill": {
                "category_invocations": len(BACKFILL_CATEGORIES),
                "submitted_symbol_occurrences": len(submitted),
                "external_request_upper_bound": None,
            },
            "labels": {
                "skipped": no_llm,
                "per_symbol_attempts_at_most": 0 if no_llm else len(submitted),
                "existing_label_coverage": "unknown_without_database_read",
                "model_call_upper_bound": 0 if no_llm else None,
            },
            "deep_research": {
                "skipped": no_llm,
                "stage_invocations_at_most": 0 if no_llm else 1,
                "requires_confirmation_unless_auto": not no_llm and not auto,
                "model_call_upper_bound": 0 if no_llm else None,
            },
            "copilot": {
                "skipped": no_llm,
                "per_symbol_attempts_at_most": 0 if no_llm else len(copilot_slots),
                "first_eight_occurrences": copilot_slots,
                "omitted_occurrences": max(0, len(submitted) - 8),
                "model_call_upper_bound": 0 if no_llm else None,
            },
            "watchlist": {"writes_on_default_run": True, "writes_on_preflight": False},
        },
        "budget": {
            "external_request_upper_bound": None,
            "model_call_upper_bound": 0 if no_llm else None,
            "billed_cost_upper_bound": None,
            "billing_status": "unknown",
            "reason": "Stage attempt counts do not cap provider calls or subscription billing.",
        },
        "warnings": warnings,
    }


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(Path(db_path) if db_path is not None else default_sqlite_path())
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _latest_labels(
    symbols: list[str], *, db_path: str | Path | None = None, as_of: str | None = None,
) -> dict[str, str]:
    if not symbols:
        return {}
    with _connect(db_path) as con:
        if not _table_exists(con, "long_term_labels") or not {"symbol", "label", "date"} <= _columns(con, "long_term_labels"):
            return {}
        placeholders = ",".join("?" for _ in symbols)
        where = f"symbol IN ({placeholders})"
        params = list(symbols)
        cols = _columns(con, "long_term_labels")
        if as_of:
            where += " AND date <= ?"
            params.append(as_of)
            if "expires_at" in cols:
                where += " AND expires_at >= ?"
                params.append(as_of)
            if "created_at" in cols:
                where += " AND created_at IS NOT NULL AND date(created_at) <= ?"
                params.append(as_of)
        rows = con.execute(
            f"SELECT symbol, label, date FROM long_term_labels WHERE {where} ORDER BY date DESC, id DESC",
            params,
        ).fetchall()
    labels: dict[str, str] = {}
    for row in rows:
        labels.setdefault(str(row["symbol"]), f"{row['label']}({row['date']})")
    return labels


def _stage_line(message: str) -> None:
    print(message, flush=True)


@contextmanager
def _temporary_env(updates: dict[str, str]):
    old = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_backfill(symbols: list[str], *, as_of: str, offline: bool = False) -> dict[str, Any]:
    if offline:
        return {
            category: {"skipped": True, "reason": "--offline:只读已存数据，不发起外部数据请求"}
            for category in (*BACKFILL_CATEGORIES, "news")
        }
    from backend.data.database import SessionLocal
    from backend.data.orm import Base

    end = date.fromisoformat(as_of)
    start = end - timedelta(days=183)
    names = _name_by_symbol(symbols)
    stocks = [{"symbol": symbol, "name": names.get(symbol, symbol)} for symbol in symbols]
    results: dict[str, Any] = {}
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
        for category in BACKFILL_CATEGORIES:
            if category == "lhb":
                inserted, degradations = m61_backfill._backfill_lhb(stocks, start, end, db)
            elif category == "corporate_events":
                inserted, degradations = m61_backfill._backfill_corporate_events(stocks, start, end, db)
            else:
                inserted, degradations = m61_backfill._backfill_stock_category(category, stocks, start, end, db)
            results[category] = {"inserted": inserted, "degradations": degradations[:5]}
        results["news"] = {
            "skipped": True,
            "reason": "新闻仅走既有每日 accrual 便宜路径; 当前随时式未确认 iFinD 覆盖流,跳过主动回补",
        }
        return results
    finally:
        db.close()


def _run_label_builder(symbols: list[str], *, no_llm: bool, as_of: str | None = None) -> dict[str, Any]:
    from backend.agents.long_term.storage import bulk_get_labels, save_label
    from backend.agents.long_term.team import LongTermTeam
    from backend.data.database import SessionLocal

    def serialize(labels: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            symbol: {
                "date": label.date,
                "label": label.label,
                "quality": label.quality,
                "quality_notes": list(label.quality_notes),
                "votes": dict(label.votes),
                "findings": list(label.key_findings),
                "expires_at": label.expires_at,
            }
            for symbol, label in labels.items()
        }

    if no_llm:
        db = SessionLocal()
        try:
            if as_of:
                from backend.data.database import LongTermLabel as LabelORM

                rows = (
                    db.query(LabelORM)
                    .filter(
                        LabelORM.symbol.in_(symbols),
                        LabelORM.date <= as_of,
                        LabelORM.expires_at >= as_of,
                        LabelORM.created_at.is_not(None),
                        LabelORM.created_at <= datetime.fromisoformat(as_of).replace(hour=23, minute=59, second=59),
                    )
                    .order_by(LabelORM.date.desc(), LabelORM.id.desc())
                    .all()
                ) if symbols else []
                labels: dict[str, dict[str, Any]] = {}
                for row in rows:
                    labels.setdefault(row.symbol, {
                        "date": row.date,
                        "label": row.label,
                        "quality": getattr(row, "quality", "degraded") or "degraded",
                        "quality_notes": json.loads(row.quality_notes_json or "[]"),
                        "votes": json.loads(row.votes_json or "{}"),
                        "findings": json.loads(row.key_findings_json or "[]"),
                        "expires_at": row.expires_at,
                    })
                return {"skipped": True, "reason": f"--no-llm:仅读取截至 {as_of} 有效的已有标签", "details": labels}
            return {
                "skipped": True,
                "reason": "--no-llm:跳过长期标签模型，仅读取已有有效标签",
                "details": serialize(bulk_get_labels(symbols, db)),
            }
        finally:
            db.close()

    names = _name_by_symbol(symbols)
    success: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    with _temporary_env({"LOCAL_CLI_PREFER_CODEX": "false", "LOCAL_CLI_NO_CODEX_FALLBACK": "true"}):
        db = SessionLocal()
        try:
            existing = bulk_get_labels(symbols, db)
            team = LongTermTeam()
            for symbol in symbols:
                if symbol in existing:
                    skipped.append(symbol)
                    continue
                try:
                    label = team.run(symbol, names.get(symbol, symbol), db)
                    save_label(label, db)
                    success.append(symbol)
                except Exception as exc:  # noqa: BLE001 - per-symbol label degradation.
                    failed.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            db.close()
    db = SessionLocal()
    try:
        details = serialize(bulk_get_labels(symbols, db))
    finally:
        db.close()
    return {"success": success, "skipped": skipped, "failed": failed, "details": details}


def _confirm_deep_research(auto: bool) -> bool:
    if auto:
        return True
    print("深研是本命令最贵的 LLM 步骤。继续运行? [y/N] ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _run_deep_research_stage(
    target: dict[str, Any],
    *,
    as_of: str,
    auto: bool,
    no_llm: bool,
    offline: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    if no_llm and not offline:
        return {"skipped": True, "reason": "--no-llm:跳过深研"}
    if not offline and not _confirm_deep_research(auto):
        return {"skipped": True, "reason": "未确认昂贵 LLM 深研"}
    from backend.data.database import SessionLocal
    from backend.research.deep_research import run_deep_research

    db = SessionLocal()
    try:
        report = run_deep_research(
            topic=str(target["title"]),
            symbols=list(target["symbols"]),
            db=db,
            output_dir=output_dir or OUTPUT_DIR,
            as_of=as_of,
            persist=not offline,
            long_term_theme=target.get("target_type") == "theme",
            allow_external_retrieval=not offline,
        )
        return {
            "skipped": False,
            "summary": report.summary,
            "path": str(report.path) if report.path else None,
            "gate_status": report.gate_status,
            "source_count": report.source_count,
            "quality_status": report.quality_status,
            "source_relevance": report.source_relevance,
            "long_term_framework": report.long_term_framework,
            "offline": offline,
            "model_calls": 0 if offline else None,
        }
    finally:
        db.close()


def _run_copilot_stage(symbols: list[str], *, no_llm: bool) -> dict[str, Any]:
    if no_llm:
        return {"skipped": True, "reason": "--no-llm:跳过 copilot"}
    from backend.data.database import SessionLocal
    from backend.research.copilot import generate_symbol_copilot

    truncated = symbols[:8]
    cards: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        for symbol in truncated:
            cards.append(generate_symbol_copilot(symbol, db))
    finally:
        db.close()
    return {
        "skipped": False,
        "truncated": len(symbols) > len(truncated),
        "cards": cards,
    }


def _watchlist_path(theme_key: str, watchlist_dir: Path | str = WATCHLIST_DIR) -> Path:
    return Path(watchlist_dir) / f"{_slug(theme_key)}.json"


def _upsert_watchlist(
    target: dict[str, Any],
    *,
    as_of: str,
    deep_research: dict[str, Any] | None,
    watchlist_dir: Path | str | None = None,
) -> dict[str, Any]:
    theme_key = str(target.get("theme_key") or _slug(str(target["target"])))
    path = _watchlist_path(theme_key, watchlist_dir if watchlist_dir is not None else WATCHLIST_DIR)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except (OSError, json.JSONDecodeError):
            existing = {}
    thesis = str((deep_research or {}).get("summary") or "").strip() or "研究进行中"
    entry = {
        "theme_key": theme_key,
        "title": str(target.get("title") or target["target"]),
        "thesis": thesis,
        "symbols": list(target["symbols"]),
        "validation_conditions": existing.get("validation_conditions") if isinstance(existing.get("validation_conditions"), list) else [],
        "invalidation_conditions": existing.get("invalidation_conditions") if isinstance(existing.get("invalidation_conditions"), list) else [],
        "created_at": str(existing.get("created_at") or as_of),
        "source_ref": f"m63_research_{as_of.replace('-', '')}",
    }
    errors = validate_watchlist_entry(entry)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path), "entry": entry, "updated": bool(existing)}


def _stage(name: str, func) -> dict[str, Any]:
    _stage_line(f"▶ {name}...")
    try:
        result = func()
        _stage_line(f"✓ {name}")
        return {"name": name, "ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - M63-2 is explicitly degradable.
        message = f"⚠️ {name} 失败:{type(exc).__name__}: {exc}"
        _stage_line(message)
        return {"name": name, "ok": False, "error": message}


def _stage_payload_has_failure(value: Any) -> bool:
    if isinstance(value, dict):
        if any(value.get(key) for key in ("failed", "errors", "error", "blocked")):
            return True
        if value.get("gate_status") == "blocked":
            return True
        return any(_stage_payload_has_failure(item) for item in value.values())
    if isinstance(value, list):
        return any(_stage_payload_has_failure(item) for item in value)
    return False


def _stage_health_line(stage: dict[str, Any]) -> str:
    if not stage.get("ok"):
        return f"{stage['name']}:失败 ({stage.get('error') or '未提供错误详情'})"
    result = stage.get("result")
    if isinstance(result, dict):
        if result.get("gate_status") == "blocked":
            return f"{stage['name']}:失败 (报告门禁阻止写出)"
        if result.get("skipped"):
            return f"{stage['name']}:跳过 ({result.get('reason') or '按配置跳过'})"
        if result and all(
            isinstance(item, dict) and item.get("skipped")
            for item in result.values()
        ):
            return f"{stage['name']}:跳过 (全部子项按配置跳过)"
        if _stage_payload_has_failure(result):
            return f"{stage['name']}:部分失败 (结果中含 failed/errors)"
        if result.get("quality_status") == "partial":
            return f"{stage['name']}:partial (研究证据未达充分门槛)"
        if result.get("quality_status") == "blocked":
            return f"{stage['name']}:失败 (质量门阻止)"
    return f"{stage['name']}:OK"


def _stage_result(stages: list[dict[str, Any]], name: str) -> Any:
    for stage in stages:
        if stage["name"] == name and stage.get("ok"):
            return stage.get("result")
    return None


def _format_data_lines(backfill: dict[str, Any] | None) -> list[str]:
    if not backfill:
        return ["数据补齐未完成"]
    lines = []
    for category in [*BACKFILL_CATEGORIES, "news"]:
        item = backfill.get(category, {})
        if item.get("skipped"):
            lines.append(f"{category}:跳过({item.get('reason')})")
        else:
            lines.append(f"{category}:落库{item.get('inserted', 0)}条; 降级{len(item.get('degradations') or [])}项")
    return lines


def _format_label_lines(symbols: list[str], before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [f"{symbol}: {before.get(symbol, '无')} -> {after.get(symbol, '无')}" for symbol in symbols]


def _format_copilot_lines(copilot: dict[str, Any] | None) -> list[str]:
    if not copilot:
        return ["copilot 未完成"]
    if copilot.get("skipped"):
        return [str(copilot.get("reason"))]
    lines = []
    if copilot.get("truncated"):
        lines.append("copilot:标的超过8只,仅刷新前8只")
    for card in copilot.get("cards", []):
        lines.append(
            f"{card.get('symbol')} {card.get('stance', '-')}: {card.get('summary_opinion') or card.get('position_note') or '-'}"
        )
    return lines or ["copilot 无卡片"]


def _format_long_term_role_lines(symbols: list[str], details: dict[str, dict[str, Any]]) -> list[str]:
    role_names = {"track": "赛道/供应链", "boom": "景气", "quality": "Piotroski质量", "flow": "QFII资金流"}
    lines: list[str] = []
    for symbol in symbols:
        detail = details.get(symbol)
        if not detail:
            lines.append(f"{symbol}: 当前没有有效的已存长期标签；本次没有可展示的分析师角色结果。")
            continue
        lines.append(
            f"{symbol}: {detail['label']}，日期 {detail['date']}，质量 {detail['quality']}，到期 {detail['expires_at']}。"
        )
        lines.append("  - 注意：quality/投票是生成该标签时保存的历史元数据，不代表本次财务输入已重新验证。")
        votes = detail.get("votes") or {}
        findings = detail.get("findings") or []
        for role, display in role_names.items():
            prefix = {"track": "[赛道]", "boom": "[景气]", "quality": "[质量]", "flow": "[外资流向]"}[role]
            role_findings = [text[len(prefix):].strip() for text in findings if str(text).startswith(prefix)]
            lines.append(
                f"  - {display}: 投票={votes.get(role, '无结果')}；"
                f"已存发现={'；'.join(role_findings) if role_findings else '没有保存该角色的发现'}"
            )
        if detail.get("quality_notes"):
            lines.append("  - 质量说明：" + "；".join(detail["quality_notes"]))
    return lines or ["本次没有可展示的长期分析师角色结果。"]


def _format_theme_framework(target: dict[str, Any], deep: dict[str, Any] | None) -> list[str]:
    coverage = target.get("coverage") or {}
    lines = [
        f"解析方式={coverage.get('scope', target.get('source'))}；名单={coverage.get('listed_count', len(target['symbols']))}只；"
        f"全行业完整覆盖={coverage.get('full_market', False)}。",
    ]
    if coverage.get("classified_local_universe_count") is not None:
        lines.append(
            f"本地已分类 universe 共 {coverage['classified_local_universe_count']} 只，"
            f"匹配 {coverage.get('listed_count', 0)} 只；来源文件={','.join(coverage.get('source_files', [])) or '无'}。"
        )
    if target.get("source") == "local_stock_industry_unversioned":
        lines.append(
            "名单来源=当前本地 stocks.industry 元数据；只代表已跟踪股票子集，不是全市场成分；"
            "历史 as-of 成分归属无版本快照，不能回溯确认。"
        )
    framework = (deep or {}).get("long_term_framework")
    if not framework:
        lines.append("长期研究框架未生成：深研被跳过或失败。")
        return lines
    lines.append("长期维度状态：")
    for item in framework.get("framework", []):
        evidence = "；".join(item.get("evidence", [])) or "暂无直接证据"
        missing = "；".join(item.get("missing", [])) or "暂无额外缺项"
        lines.append(f"- {item['dimension']} [{item['status']}]: 证据={evidence}；缺失={missing}")
    return lines


def _render_research_report(
    *,
    target: dict[str, Any],
    as_of: str,
    stages: list[dict[str, Any]],
    labels_before: dict[str, str],
    labels_after: dict[str, str],
    long_term_details: dict[str, dict[str, Any]] | None = None,
) -> str:
    backfill = _stage_result(stages, "数据补齐")
    deep = _stage_result(stages, "深研")
    copilot = _stage_result(stages, "copilot")
    watchlist = _stage_result(stages, "观察哨")
    health = [_stage_health_line(stage) for stage in stages]
    sections = [
        ("随时式研究", [f"日期:{as_of}", f"目标:{target['target']}", f"标的:{','.join(target['symbols'])}", f"解析来源:{target['source']}"]),
        ("名单覆盖范围", [str(line) for line in _format_theme_framework(target, deep)[:2]]),
        ("数据面", _format_data_lines(backfill)),
        ("标签面", _format_label_lines(list(target["symbols"]), labels_before, labels_after)),
        ("长期分析师角色", _format_long_term_role_lines(list(target["symbols"]), long_term_details or {})),
        ("研究结论", [
            f"质量状态={(deep or {}).get('quality_status', 'unknown')}",
            f"文本直相关公司={(deep or {}).get('source_relevance', {}).get('direct_company_count', 0)}；"
            f"文本直相关主题={(deep or {}).get('source_relevance', {}).get('direct_theme_count', 0)}",
            str((deep or {}).get("summary") or (deep or {}).get("reason") or "深研未完成"),
        ]),
        ("财务复核边界", [
            "M63 随时研究默认补齐列表不含 financial_metrics；已有季度财务行不代表已刷新到最新季。",
            "标签生成时保存的质量元数据需与本次严格财务输入覆盖分别阅读。",
        ]),
        ("板块长期研究", _format_theme_framework(target, deep) if target.get("target_type") == "theme" else ["单股目标；主题长期框架不适用。"]),
        ("逐股要点", _format_copilot_lines(copilot)),
        ("观察哨", [f"{'更新' if (watchlist or {}).get('updated') else '创建'}:{(watchlist or {}).get('path', '未写入')}"]),
        ("数据健康", health),
    ]
    return enforce_language_guard(strip_raw_json(render_report(sections)), mode="sanitize")


def _write_report(
    target: dict[str, Any], as_of: str, text: str, *, output_dir: Path | str | None = None,
) -> Path:
    destination = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"research_{_slug(str(target['target']))}_{as_of.replace('-', '')}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _queue_entry_by_id(queue: list[dict[str, Any]], queue_id: str) -> dict[str, Any] | None:
    for item in queue:
        if str(item.get("id")) == queue_id:
            return item
    return None


def _mark_queue_done(queue_id: str, *, queue_path: Path = DEFAULT_QUEUE_PATH) -> bool:
    queue = load_queue(queue_path)
    item = _queue_entry_by_id(queue, queue_id)
    if item is None:
        return False
    item["status"] = "done"
    item["done_at"] = _today()
    save_queue(queue, queue_path)
    return True


def run_research(
    *,
    target: str,
    symbols: list[str] | None = None,
    auto: bool = False,
    no_llm: bool = False,
    from_queue: str | None = None,
    queue_path: Path = DEFAULT_QUEUE_PATH,
    as_of: str | None = None,
    watchlist_dir: Path | str | None = None,
    universe_paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS,
    offline: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    day = as_of or _today()
    if offline and output_dir is None:
        raise ValueError("--offline 必须指定 --output-dir，确保报告只写入隔离目录")
    if from_queue:
        queue = load_queue(queue_path)
        entry = _queue_entry_by_id(queue, from_queue)
        if entry is None:
            raise SystemExit(f"未找到队列条目:{from_queue}")
        target = str(entry.get("target") or target)
    try:
        resolved = resolve_target(
            target,
            symbols=symbols,
            watchlist_dir=watchlist_dir,
            universe_paths=universe_paths,
        )
    except TargetResolutionError:
        industry_resolved = _resolve_from_local_stock_industry(target) if not symbols else None
        if industry_resolved is None:
            raise
        resolved = industry_resolved
    labels_before = (
        _latest_labels(list(resolved["symbols"]), as_of=day)
        if offline else _latest_labels(list(resolved["symbols"]))
    )
    if offline:
        def backfill_call():
            return _run_backfill(list(resolved["symbols"]), as_of=day, offline=True)

        def deep_call():
            return _run_deep_research_stage(
                resolved, as_of=day, auto=auto, no_llm=True, offline=True, output_dir=output_dir,
            )
    else:
        def backfill_call():
            return _run_backfill(list(resolved["symbols"]), as_of=day)

        def deep_call():
            return _run_deep_research_stage(resolved, as_of=day, auto=auto, no_llm=no_llm)
    stages = [
        _stage("数据补齐", backfill_call),
        _stage("标签", lambda: (
            _run_label_builder(list(resolved["symbols"]), no_llm=True, as_of=day)
            if offline else _run_label_builder(list(resolved["symbols"]), no_llm=no_llm)
        )),
        _stage("深研", deep_call),
        _stage("copilot", lambda: _run_copilot_stage(list(resolved["symbols"]), no_llm=(no_llm or offline))),
    ]
    labels_after = (
        _latest_labels(list(resolved["symbols"]), as_of=day)
        if offline else _latest_labels(list(resolved["symbols"]))
    )
    label_result = _stage_result(stages, "标签") or {}
    deep_result = _stage_result(stages, "深研")
    if offline:
        stages.append(_stage("观察哨", lambda: {"skipped": True, "reason": "--offline:不写观察哨"}))
    elif watchlist_dir is None:
        stages.append(_stage(
            "观察哨",
            lambda: _upsert_watchlist(resolved, as_of=day, deep_research=deep_result),
        ))
    else:
        stages.append(_stage(
            "观察哨",
            lambda: _upsert_watchlist(
                resolved, as_of=day, deep_research=deep_result, watchlist_dir=watchlist_dir,
            ),
        ))
    text = _render_research_report(
        target=resolved,
        as_of=day,
        stages=stages,
        labels_before=labels_before,
        labels_after=labels_after,
        long_term_details=label_result.get("details") or {},
    )
    report_path = _write_report(resolved, day, text, output_dir=output_dir)
    print(f"wrote {report_path}")
    print(text)
    deep_quality = (deep_result or {}).get("quality_status")
    payloads_clean = all(not _stage_payload_has_failure(stage.get("result")) for stage in stages)
    if from_queue and not offline and all(stage.get("ok") for stage in stages) and payloads_clean and deep_quality == "sufficient":
        _mark_queue_done(from_queue, queue_path=queue_path)
    return {"target": resolved, "stages": stages, "report_path": str(report_path), "text": text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run M63-2 on-demand full-stack research")
    parser.add_argument("--target", required=True, help="6位股票代码或主题名")
    parser.add_argument("--symbols", default="", help="主题成分股,逗号分隔")
    parser.add_argument("--auto", action="store_true", help="直接运行昂贵 LLM 深研,不再二次确认")
    parser.add_argument("--no-llm", action="store_true", help="跳过标签/深研/copilot LLM")
    parser.add_argument("--offline", action="store_true", help="仅用本地快照生成深研与板块框架；不联网、不调用模型、不回补、不改watchlist/队列")
    parser.add_argument("--as-of", default=None, help="研究截止日 YYYY-MM-DD")
    parser.add_argument("--output-dir", default=None, help="报告输出目录（--offline建议指定隔离目录）")
    parser.add_argument(
        "--preflight", action="store_true",
        help="只读预检标的去重建议与阶段容量；不访问 DB、网络、LLM 或写报告",
    )
    parser.add_argument("--from-queue", default=None, help="从 ~/.mingcang/m63_research_queue.json 读取队列条目")
    args = parser.parse_args(argv)
    try:
        if args.preflight:
            target = args.target
            if args.from_queue:
                entry = _queue_entry_by_id(load_queue(DEFAULT_QUEUE_PATH), args.from_queue)
                if entry is None:
                    raise TargetResolutionError(f"未找到队列条目:{args.from_queue}")
                target = str(entry.get("target") or target)
            resolved = resolve_target(target, symbols=_symbols_arg(args.symbols))
            print(json.dumps(
                build_research_preflight(resolved, no_llm=args.no_llm, auto=args.auto),
                ensure_ascii=False, indent=2,
            ))
            return 0
        run_research(
            target=args.target,
            symbols=_symbols_arg(args.symbols),
            auto=args.auto,
            no_llm=args.no_llm,
            from_queue=args.from_queue,
            as_of=args.as_of,
            offline=args.offline,
            output_dir=args.output_dir,
        )
    except TargetResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
