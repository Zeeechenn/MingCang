"""M63 weekly fixed health check: cheap scan, attribution, and queue upgrades."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.research.watchlist import WATCHLIST_DIR, load_watchlists
from backend.tools import m63_daily
from backend.tools.m63_render import render_report, strip_raw_json

OUTPUT_DIR = m63_daily.OUTPUT_DIR
DEFAULT_QUEUE_PATH = m63_daily.DEFAULT_QUEUE_PATH
DEFAULT_TRIGGER_HISTORY_PATH = m63_daily.DEFAULT_TRIGGER_HISTORY_PATH
R5_RULE = "R5_weekly_sweep"

_ATTRIBUTION_TOOL = {
    "name": "m63_weekly_attribution",
    "input_schema": {
        "type": "object",
        "properties": {
            "lessons": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "validated": {"type": "array", "items": {"type": "string"}},
            "falsified": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["lessons", "validated", "falsified"],
        "additionalProperties": False,
    },
}


def _today() -> str:
    return date.today().isoformat()


def _week_start(as_of: str) -> str:
    return (date.fromisoformat(as_of) - timedelta(days=6)).isoformat()


def _in_week(value: Any, start: str, end: str) -> bool:
    if not value:
        return False
    text = str(value)[:10]
    return start <= text <= end


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    return con


def _week_price_changes(con: sqlite3.Connection, symbols: set[str], *, start: str, end: str) -> list[dict[str, Any]]:
    if not m63_daily._table_exists(con, "prices") or not {"symbol", "date", "close"} <= m63_daily._columns(con, "prices"):
        return []
    changes: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        rows = con.execute(
            """
            SELECT date, close
            FROM prices
            WHERE symbol = ? AND date >= ? AND date <= ? AND close IS NOT NULL
            ORDER BY date
            """,
            (symbol, start, end),
        ).fetchall()
        if len(rows) < 2 or not rows[0]["close"]:
            continue
        pct = (float(rows[-1]["close"]) / float(rows[0]["close"]) - 1) * 100
        changes.append(
            {
                "symbol": symbol,
                "start_date": rows[0]["date"],
                "end_date": rows[-1]["date"],
                "start_close": rows[0]["close"],
                "end_close": rows[-1]["close"],
                "week_chg_pct": round(pct, 2),
            }
        )
    return changes


def _label_changes(con: sqlite3.Connection, symbols: set[str], *, start: str, end: str) -> list[dict[str, Any]]:
    if not m63_daily._table_exists(con, "long_term_labels"):
        return []
    cols = m63_daily._columns(con, "long_term_labels")
    if not {"symbol", "label"} <= cols:
        return []
    if {"created_at", "date"} <= cols:
        date_expr = "COALESCE(created_at, date)"
    elif "created_at" in cols:
        date_expr = "created_at"
    elif "date" in cols:
        date_expr = "date"
    else:
        return []
    placeholders = ",".join("?" for _ in symbols) or "''"
    rows = con.execute(
        f"""
        SELECT symbol, label, {date_expr} AS changed_at
        FROM long_term_labels
        WHERE symbol IN ({placeholders})
          AND date({date_expr}) >= date(?)
          AND date({date_expr}) <= date(?)
        ORDER BY date({date_expr}), symbol, id
        """,
        [*sorted(symbols), start, end],
    ).fetchall()
    return [dict(row) for row in rows]


def _expiring_labels(con: sqlite3.Connection, symbols: set[str], *, as_of: str) -> list[dict[str, Any]]:
    if not m63_daily._table_exists(con, "long_term_labels"):
        return []
    cols = m63_daily._columns(con, "long_term_labels")
    if not {"symbol", "expires_at"} <= cols:
        return []
    until = (date.fromisoformat(as_of) + timedelta(days=3)).isoformat()
    placeholders = ",".join("?" for _ in symbols) or "''"
    rows = con.execute(
        f"""
        SELECT symbol, MAX(expires_at) AS expires_at
        FROM long_term_labels
        WHERE symbol IN ({placeholders})
        GROUP BY symbol
        HAVING date(expires_at) >= date(?) AND date(expires_at) <= date(?)
        ORDER BY date(expires_at), symbol
        """,
        [*sorted(symbols), as_of, until],
    ).fetchall()
    return [dict(row) for row in rows]


def _pending_overdue(queue: list[dict[str, Any]], *, as_of: str) -> list[dict[str, Any]]:
    day = date.fromisoformat(as_of)
    overdue: list[dict[str, Any]] = []
    for item in queue:
        if item.get("status") != "pending":
            continue
        try:
            age = (day - date.fromisoformat(str(item.get("created_at"))[:10])).days
        except ValueError:
            continue
        if age > 7:
            row = dict(item)
            row["age_days"] = age
            overdue.append(row)
    return overdue


def _trigger_targets_this_week(history: list[dict[str, Any]], queue: list[dict[str, Any]], *, start: str, end: str) -> set[str]:
    targets: set[str] = set()
    for item in history:
        if _in_week(item.get("date"), start, end) and item.get("target"):
            targets.add(str(item["target"]))
    for item in queue:
        if (_in_week(item.get("created_at"), start, end) or _in_week(item.get("done_at"), start, end)) and item.get("target"):
            targets.add(str(item["target"]))
    return targets


def _missed_movers(changes: list[dict[str, Any]], seen_targets: set[str]) -> list[dict[str, Any]]:
    return [row for row in changes if abs(float(row["week_chg_pct"])) >= 10 and str(row["symbol"]) not in seen_targets]


def _history_stats(history: list[dict[str, Any]], *, start: str, end: str) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for item in history:
        if _in_week(item.get("date"), start, end):
            counter[str(item.get("trigger_type") or item.get("trigger_rule") or "unknown")] += 1
    return [{"rule": rule, "fires": count} for rule, count in sorted(counter.items())]


def _date_from_source_ref(source_ref: str) -> str | None:
    match = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", source_ref)
    if not match:
        return None
    return "-".join(match.groups())


def _stale_watchlists(watchlist_dir: Path | str, *, as_of: str) -> tuple[list[dict[str, Any]], list[str]]:
    entries, errors = load_watchlists(watchlist_dir)
    day = date.fromisoformat(as_of)
    stale: list[dict[str, Any]] = []
    for entry in entries:
        updated = str(entry.get("updated_at") or "")[:10]
        source_date = _date_from_source_ref(str(entry.get("source_ref") or ""))
        basis = source_date or updated or str(entry.get("created_at") or "")[:10]
        try:
            age = (day - date.fromisoformat(basis)).days
        except ValueError:
            continue
        if age > 30 and not updated:
            stale.append(
                {
                    "theme_key": entry["theme_key"],
                    "title": entry["title"],
                    "symbols": entry.get("symbols", []),
                    "source_ref": entry.get("source_ref"),
                    "age_days": age,
                }
            )
    return stale, errors


def _symbol_sectors(con: sqlite3.Connection, universe_paths: tuple[Path, ...] | None = None) -> dict[str, str]:
    sectors: dict[str, str] = {}
    for path in universe_paths or tuple(m63_daily.DEFAULT_UNIVERSE_PATHS):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in payload.get("stocks", []) if isinstance(payload, dict) else []:
            symbol = str(row.get("symbol") or "")
            sector = row.get("sector") or row.get("industry")
            if symbol and sector:
                sectors[symbol] = str(sector)
    if m63_daily._table_exists(con, "stocks"):
        cols = m63_daily._columns(con, "stocks")
        sector_col = "sector" if "sector" in cols else ("industry" if "industry" in cols else None)
        if sector_col and "symbol" in cols:
            for row in con.execute(f"SELECT symbol, {sector_col} AS sector FROM stocks WHERE {sector_col} IS NOT NULL").fetchall():
                sectors.setdefault(str(row["symbol"]), str(row["sector"]))
    if m63_daily._table_exists(con, "positions"):
        cols = m63_daily._columns(con, "positions")
        sector_col = "sector" if "sector" in cols else ("industry" if "industry" in cols else None)
        if sector_col and "symbol" in cols:
            for row in con.execute(f"SELECT symbol, {sector_col} AS sector FROM positions WHERE {sector_col} IS NOT NULL").fetchall():
                sectors[str(row["symbol"])] = str(row["sector"])
    return sectors


def _sector_concentration(con: sqlite3.Connection, watchlist_dir: Path | str) -> list[dict[str, Any]]:
    entries, _ = load_watchlists(watchlist_dir)
    symbols = set(m63_daily._holding_symbols(con))
    for entry in entries:
        symbols.update(str(symbol) for symbol in entry.get("symbols", []) if symbol)
    sectors = _symbol_sectors(con)
    counts = Counter(sectors.get(symbol, "未知") for symbol in symbols)
    total = sum(counts.values())
    if not total:
        return []
    sector, count = counts.most_common(1)[0]
    share = count / total * 100
    if share > 60:
        return [{"sector": sector, "count": count, "total": total, "share_pct": round(share, 2)}]
    return []


def _data_health(con: sqlite3.Connection, *, start: str, end: str) -> list[dict[str, Any]]:
    if not m63_daily._table_exists(con, "degradation_events"):
        return []
    cols = m63_daily._columns(con, "degradation_events")
    if not {"ts", "component"} <= cols:
        return []
    rows = con.execute(
        """
        SELECT component, COUNT(*) AS count
        FROM degradation_events
        WHERE date(ts) >= date(?) AND date(ts) <= date(?)
        GROUP BY component
        ORDER BY count DESC, component
        """,
        (start, end),
    ).fetchall()
    return [dict(row) for row in rows]


def _exit_shadow_divergences(builder, *, db_path: str | Path | None, as_of: str) -> list[dict[str, Any]]:
    if builder is None:
        try:
            from backend.tools.m58_exit_shadow import build_shadow_report
            from paper_trading.test2_ab_data import DEFAULT_UNIVERSE

            builder = lambda **_: build_shadow_report(db_path=Path(db_path) if db_path else default_sqlite_path(), universe_path=DEFAULT_UNIVERSE, run_date=as_of)
        except Exception:  # noqa: BLE001 - weekly scan must remain readable.
            return []
    try:
        report = builder(db_path=db_path, run_date=as_of)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(report, dict):
        return []
    return list(report.get("trade_differences") or [])


@contextmanager
def _forced_claude_env():
    updates = {"LOCAL_CLI_PREFER_CODEX": "false", "LOCAL_CLI_NO_CODEX_FALLBACK": "true"}
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


def _run_attribution_llm(facts: dict[str, Any]) -> dict[str, Any]:
    from backend.llm.factory import get_provider

    prompt = (
        "本周复盘归因:哪些判断被验证/证伪,提炼≤3条可执行教训。\n"
        "只基于以下事实,不要给交易指令:\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
    )
    with _forced_claude_env():
        data = get_provider().complete_structured(
            prompt=prompt,
            tool=_ATTRIBUTION_TOOL,
            system="你是明仓周末复盘归因助手,输出可执行研究教训。",
            max_tokens=1000,
            model_tier="capable",
        )
    if not data:
        raise RuntimeError("LLM returned empty weekly attribution")
    return {
        "lessons": list(data.get("lessons") or [])[:3],
        "validated": list(data.get("validated") or []),
        "falsified": list(data.get("falsified") or []),
    }


def _attribution(no_llm: bool, facts: dict[str, Any], runner=None) -> dict[str, Any]:
    if no_llm:
        return {"skipped": True, "note": "--no-llm:跳过本周复盘归因LLM步骤", "lessons": [], "validated": [], "falsified": []}
    try:
        result = (runner or _run_attribution_llm)(facts)
    except Exception as exc:  # noqa: BLE001
        return {"skipped": True, "note": f"LLM归因失败:{type(exc).__name__}: {exc}", "lessons": [], "validated": [], "falsified": []}
    result["skipped"] = False
    return result


def _lines_attribution(attribution: dict[str, Any]) -> list[str]:
    if attribution.get("skipped"):
        return [str(attribution.get("note") or "归因跳过")]
    lines = [f"教训:{item}" for item in attribution.get("lessons", [])]
    lines.extend(f"验证:{item}" for item in attribution.get("validated", []))
    lines.extend(f"证伪:{item}" for item in attribution.get("falsified", []))
    return lines or ["本周归因未返回有效条目"]


def _write_report(as_of: str, text: str, output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"weekly_{as_of}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_weekly(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    no_llm: bool = False,
    queue_path: Path = DEFAULT_QUEUE_PATH,
    history_path: Path = DEFAULT_TRIGGER_HISTORY_PATH,
    watchlist_dir: Path | str = WATCHLIST_DIR,
    output_dir: Path = OUTPUT_DIR,
    exit_shadow_builder=None,
    attribution_runner=None,
) -> dict[str, Any]:
    day = as_of or _today()
    start = _week_start(day)
    queue = m63_daily.load_queue(queue_path)
    history = m63_daily._load_history(history_path)
    with _connect(db_path) as con:
        universe = m63_daily._universe_symbols(con) | m63_daily._holding_symbols(con)
        week_changes = _week_price_changes(con, universe, start=start, end=day)
        label_changes = _label_changes(con, universe, start=start, end=day)
        expiring = _expiring_labels(con, universe, as_of=day)
        concentration = _sector_concentration(con, watchlist_dir)
        data_health = _data_health(con, start=start, end=day)
    exit_divergences = _exit_shadow_divergences(exit_shadow_builder, db_path=db_path, as_of=day)
    queue_week = [item for item in queue if _in_week(item.get("created_at"), start, day) or _in_week(item.get("done_at"), start, day)]
    facts = {
        "as_of": day,
        "window": {"start": start, "end": day},
        "week_price_changes": week_changes,
        "label_changes": label_changes,
        "exit_shadow_divergences": exit_divergences,
        "queue_items_this_week": queue_week,
    }
    attribution = _attribution(no_llm, facts, runner=attribution_runner)
    seen = _trigger_targets_this_week(history, queue, start=start, end=day)
    missed = _missed_movers(week_changes, seen)
    overdue = _pending_overdue(queue, as_of=day)
    stats = _history_stats(history, start=start, end=day)
    stale, watchlist_errors = _stale_watchlists(watchlist_dir, as_of=day)

    enqueued: list[dict[str, Any]] = []
    for row in missed:
        if m63_daily._enqueue(
            queue,
            as_of=day,
            target=str(row["symbol"]),
            reason=f"周度体检漏网:{row['symbol']} 本周涨跌{row['week_chg_pct']:+.2f}%未被触发器/队列覆盖",
            trigger_rule=R5_RULE,
        ):
            enqueued.append(queue[-1])
    for row in stale:
        if m63_daily._enqueue(
            queue,
            as_of=day,
            target=str(row["theme_key"]),
            reason=f"周度体检陈旧论点:{row['title']} source_ref已{row['age_days']}天未更新",
            trigger_rule=R5_RULE,
        ):
            enqueued.append(queue[-1])
    m63_daily.save_queue(queue, queue_path)

    sections = [
        ("周归因", _lines_attribution(attribution)),
        (
            "触发器审计",
            [
                f"窗口:{start}~{day}",
                *[
                    f"漏网清单:{row['symbol']} 本周涨跌{row['week_chg_pct']:+.2f}% 未进trigger/queue/watchtower"
                    for row in missed
                ],
                *[f"待办超7天:{item.get('target')} 已{item.get('age_days')}天 -- {item.get('reason')}" for item in overdue],
                *[f"触发统计:{row['rule']}={row['fires']}" for row in stats],
            ]
            or ["本周无触发器审计发现"],
        ),
        (
            "陈旧与漂移",
            [
                *[f"长期标签临期:{row['symbol']} expires_at={row['expires_at']}" for row in expiring],
                *[f"陈旧论点:{row['title']}({row['theme_key']}) source_ref_age={row['age_days']}天" for row in stale],
                *[f"集中度提示:{row['sector']} {row['count']}/{row['total']}={row['share_pct']}%" for row in concentration],
                *[f"watchlist错误:{err}" for err in watchlist_errors],
            ]
            or ["未见临期标签、陈旧论点或集中度漂移"],
        ),
        (
            "本周升级",
            [f"已排队:{item['target']} -- {item['reason']}" for item in enqueued]
            + (["无新增升级;已有待办保持去重"] if not enqueued else []),
        ),
        (
            "数据健康周报",
            [f"{row['component']}: {row['count']}次降级" for row in data_health]
            or ["近7天未见 degradation_events 记录"],
        ),
    ]
    text = strip_raw_json(render_report(sections))
    path = _write_report(day, text, output_dir=output_dir)
    print(text)
    print(f"wrote {path}")
    return {
        "ok": True,
        "date": day,
        "window": {"start": start, "end": day},
        "attribution": attribution,
        "missed_movers": missed,
        "stale_watchlists": stale,
        "expiring_labels": expiring,
        "enqueued": enqueued,
        "output_path": str(path),
        "text": text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M63 weekly fixed health check")
    parser.add_argument("--no-llm", action="store_true", help="Skip the one weekly attribution LLM call")
    parser.add_argument("--as-of", default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--db", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    run_weekly(db_path=args.db, as_of=args.as_of, no_llm=args.no_llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
