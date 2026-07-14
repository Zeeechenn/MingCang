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
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.research.watchlist import (
    WATCHLIST_DIR,
    load_watchlists,
    validate_watchlist_entry,
)
from backend.tools import m61_backfill
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
    watchlist_dir: Path | str = WATCHLIST_DIR,
    universe_paths: tuple[Path, ...] = DEFAULT_UNIVERSE_PATHS,
) -> dict[str, Any]:
    clean_target = target.strip()
    explicit_symbols = [s.strip() for s in (symbols or []) if s.strip()]
    if re.fullmatch(r"\d{6}", clean_target):
        return {
            "target": clean_target,
            "target_type": "symbol",
            "theme_key": clean_target,
            "title": clean_target,
            "symbols": [clean_target],
            "source": "symbol",
        }
    if explicit_symbols:
        return {
            "target": clean_target,
            "target_type": "theme",
            "theme_key": _slug(clean_target),
            "title": clean_target,
            "symbols": explicit_symbols,
            "source": "--symbols",
        }

    entries, _errors = load_watchlists(watchlist_dir)
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
            }

    matched: list[str] = []
    for item in _load_universe_entries(universe_paths):
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
        }

    raise TargetResolutionError(
        f"无法解析主题“{clean_target}”: 观察哨主题和 biaodi1/test2 sector 均未匹配。请显式提供 --symbols。"
    )


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


def _latest_labels(symbols: list[str], *, db_path: str | Path | None = None) -> dict[str, str]:
    if not symbols:
        return {}
    with _connect(db_path) as con:
        if not _table_exists(con, "long_term_labels") or not {"symbol", "label", "date"} <= _columns(con, "long_term_labels"):
            return {}
        placeholders = ",".join("?" for _ in symbols)
        rows = con.execute(
            f"""
            SELECT symbol, label, date
            FROM long_term_labels
            WHERE symbol IN ({placeholders})
            ORDER BY date DESC, id DESC
            """,
            symbols,
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


def _run_backfill(symbols: list[str], *, as_of: str) -> dict[str, Any]:
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


def _run_label_builder(symbols: list[str], *, no_llm: bool) -> dict[str, Any]:
    if no_llm:
        return {"skipped": True, "reason": "--no-llm:跳过长期标签 LLM"}
    from backend.agents.long_term.storage import bulk_get_labels, save_label
    from backend.agents.long_term.team import LongTermTeam
    from backend.data.database import SessionLocal

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
    return {"success": success, "skipped": skipped, "failed": failed}


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
) -> dict[str, Any]:
    if no_llm:
        return {"skipped": True, "reason": "--no-llm:跳过深研"}
    if not _confirm_deep_research(auto):
        return {"skipped": True, "reason": "未确认昂贵 LLM 深研"}
    from backend.data.database import SessionLocal
    from backend.research.deep_research import run_deep_research

    db = SessionLocal()
    try:
        report = run_deep_research(
            topic=str(target["title"]),
            symbols=list(target["symbols"]),
            db=db,
            output_dir=OUTPUT_DIR,
            as_of=as_of,
            persist=True,
        )
        return {
            "skipped": False,
            "summary": report.summary,
            "path": str(report.path) if report.path else None,
            "gate_status": report.gate_status,
            "source_count": report.source_count,
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
    watchlist_dir: Path | str = WATCHLIST_DIR,
) -> dict[str, Any]:
    theme_key = str(target.get("theme_key") or _slug(str(target["target"])))
    path = _watchlist_path(theme_key, watchlist_dir)
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


def _render_research_report(
    *,
    target: dict[str, Any],
    as_of: str,
    stages: list[dict[str, Any]],
    labels_before: dict[str, str],
    labels_after: dict[str, str],
) -> str:
    backfill = _stage_result(stages, "数据补齐")
    deep = _stage_result(stages, "深研")
    copilot = _stage_result(stages, "copilot")
    watchlist = _stage_result(stages, "观察哨")
    health = [
        stage["error"] if not stage.get("ok") else f"{stage['name']}:OK"
        for stage in stages
    ]
    sections = [
        ("随时式研究", [f"日期:{as_of}", f"目标:{target['target']}", f"标的:{','.join(target['symbols'])}", f"解析来源:{target['source']}"]),
        ("数据面", _format_data_lines(backfill)),
        ("标签面", _format_label_lines(list(target["symbols"]), labels_before, labels_after)),
        ("研究结论", [str((deep or {}).get("summary") or (deep or {}).get("reason") or "深研未完成")]),
        ("逐股要点", _format_copilot_lines(copilot)),
        ("观察哨", [f"{'更新' if (watchlist or {}).get('updated') else '创建'}:{(watchlist or {}).get('path', '未写入')}"]),
        ("数据健康", health),
    ]
    return enforce_language_guard(strip_raw_json(render_report(sections)), mode="sanitize")


def _write_report(target: dict[str, Any], as_of: str, text: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"research_{_slug(str(target['target']))}_{as_of.replace('-', '')}.md"
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
) -> dict[str, Any]:
    day = as_of or _today()
    if from_queue:
        queue = load_queue(queue_path)
        entry = _queue_entry_by_id(queue, from_queue)
        if entry is None:
            raise SystemExit(f"未找到队列条目:{from_queue}")
        target = str(entry.get("target") or target)
    resolved = resolve_target(target, symbols=symbols)
    labels_before = _latest_labels(list(resolved["symbols"]))
    stages = [
        _stage("数据补齐", lambda: _run_backfill(list(resolved["symbols"]), as_of=day)),
        _stage("标签", lambda: _run_label_builder(list(resolved["symbols"]), no_llm=no_llm)),
        _stage("深研", lambda: _run_deep_research_stage(resolved, as_of=day, auto=auto, no_llm=no_llm)),
        _stage("copilot", lambda: _run_copilot_stage(list(resolved["symbols"]), no_llm=no_llm)),
    ]
    labels_after = _latest_labels(list(resolved["symbols"]))
    deep_result = _stage_result(stages, "深研")
    stages.append(_stage("观察哨", lambda: _upsert_watchlist(resolved, as_of=day, deep_research=deep_result)))
    text = _render_research_report(
        target=resolved,
        as_of=day,
        stages=stages,
        labels_before=labels_before,
        labels_after=labels_after,
    )
    report_path = _write_report(resolved, day, text)
    print(f"wrote {report_path}")
    print(text)
    if from_queue and all(stage.get("ok") for stage in stages):
        _mark_queue_done(from_queue, queue_path=queue_path)
    return {"target": resolved, "stages": stages, "report_path": str(report_path), "text": text}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run M63-2 on-demand full-stack research")
    parser.add_argument("--target", required=True, help="6位股票代码或主题名")
    parser.add_argument("--symbols", default="", help="主题成分股,逗号分隔")
    parser.add_argument("--auto", action="store_true", help="直接运行昂贵 LLM 深研,不再二次确认")
    parser.add_argument("--no-llm", action="store_true", help="跳过标签/深研/copilot LLM")
    parser.add_argument("--from-queue", default=None, help="从 ~/.mingcang/m63_research_queue.json 读取队列条目")
    args = parser.parse_args(argv)
    try:
        run_research(
            target=args.target,
            symbols=_symbols_arg(args.symbols),
            auto=args.auto,
            no_llm=args.no_llm,
            from_queue=args.from_queue,
        )
    except TargetResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
