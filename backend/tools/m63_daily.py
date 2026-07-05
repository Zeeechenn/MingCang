"""M63 daily touchpoints: premarket look, intraday note, postmarket decision."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.tools.m63_render import (
    assert_no_trade_words,
    enforce_language_guard,
    format_cn_number,
    inject_semantic_notes,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "paper_trading" / "m63_out"
DEFAULT_QUEUE_PATH = Path.home() / ".mingcang" / "m63_research_queue.json"
DEFAULT_TRIGGER_HISTORY_PATH = Path.home() / ".mingcang" / "m63_trigger_history.json"
DEFAULT_UNIVERSE_PATH = REPO_ROOT / "paper_trading" / "test2_universe.json"
# M63 关注面 = test2 实盘跟踪池 ∪ 标的1(赛道研究员池) ∪ 持仓;不含全库 active(145支刷屏教训)
DEFAULT_UNIVERSE_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "paper_trading" / "test2_universe.json",
    REPO_ROOT / "paper_trading" / "biaodi1_universe.json",
)
AUTO_REFRESH_LIMIT = 5
# R6 thresholds come from 2026-07-05 weekly sweep evidence: 15 misses at ±10-19%/week;
# keep subject to weekly-audit tuning.
R6_CHG_5D_PCT = 10.0
R6_CHG_1D_PCT = 7.0
R6_DAMPER_DAYS = 5
R6_RULE = "R6_price_move"
QUEUE_DONE_TTL_DAYS = 30
POSTMARKET_STEP_MODULES = {
    "backend.tools.m61_backfill",
    "backend.tools.m60_watchtower",
    "backend.tools.m60_second_entry",
    "backend.tools.m54_daily_accrual",
    "backend.tools.m58_exit_shadow",
    "backend.tools.m59_panel",
    "backend.tools.m59_discretion",
    "backend.tools.m63_daily",
    "backend.tools.coverage_snapshot",
    "backend.tools.long_term_constraint_impact",
    "backend.tools.m52_flow_floor",
}
INTRADAY_STEP_MODULES = {
    "backend.tools.m60_watchtower",
}


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _date_only(value: Any) -> str:
    return str(value)[:10]


def _now_date(as_of: str | None = None) -> str:
    return as_of or date.today().isoformat()


def _dt_prev_1800(as_of: str) -> str:
    return datetime.combine(date.fromisoformat(as_of), time(18, 0)) - timedelta(days=1)


def _active_symbols(con: sqlite3.Connection) -> set[str]:
    if not _table_exists(con, "stocks"):
        return set()
    cols = _columns(con, "stocks")
    if "symbol" not in cols:
        return set()
    where = "WHERE COALESCE(active, 1) = 1" if "active" in cols else ""
    return {str(row["symbol"]) for row in con.execute(f"SELECT symbol FROM stocks {where}").fetchall()}


def _holding_symbols(con: sqlite3.Connection) -> set[str]:
    if not _table_exists(con, "positions") or "symbol" not in _columns(con, "positions"):
        return set()
    where = "WHERE COALESCE(status, 'open') = 'open'" if "status" in _columns(con, "positions") else ""
    return {str(row["symbol"]) for row in con.execute(f"SELECT symbol FROM positions {where}").fetchall()}


def _universe_symbols(con: sqlite3.Connection, universe_path: Path | None = None) -> set[str]:
    # M63 关注面口径 = test2池 ∪ 标的1池 ∪ 持仓(调用侧并入),**不含**全库 active——
    # 否则触发路由/事件日历会被 145 支非关注股刷屏(leader 验收修正,2026-07-05)。
    # universe_path 显式传入时只读该文件(测试用);默认读 DEFAULT_UNIVERSE_PATHS(调用时解析,可 monkeypatch)。
    paths = (universe_path,) if universe_path is not None else tuple(DEFAULT_UNIVERSE_PATHS)
    symbols: set[str] = set()
    for path in paths:
        if path is None or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            symbols.update(str(item["symbol"]) for item in payload.get("stocks", []) if item.get("symbol"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return symbols


def _latest_price(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return None
    row = con.execute(
        """
        SELECT symbol, date, open, close, atr14
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return dict(row) if row else None


def _price_move(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return None
    rows = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date <= ? AND close IS NOT NULL
        ORDER BY date DESC
        LIMIT 6
        """,
        (symbol, as_of),
    ).fetchall()
    if len(rows) < 2 or not rows[0]["close"] or not rows[1]["close"]:
        return None
    latest = float(rows[0]["close"])
    chg_1d = (latest / float(rows[1]["close"]) - 1) * 100
    chg_5d = None
    if len(rows) >= 6 and rows[5]["close"]:
        chg_5d = (latest / float(rows[5]["close"]) - 1) * 100
    return {
        "symbol": symbol,
        "date": str(rows[0]["date"])[:10],
        "chg_1d": chg_1d,
        "chg_5d": chg_5d,
    }


def _latest_signal_stop(con: sqlite3.Connection, symbol: str, as_of: str) -> float | None:
    if not _table_exists(con, "signals") or not {"symbol", "date", "stop_loss"} <= _columns(con, "signals"):
        return None
    row = con.execute(
        """
        SELECT stop_loss
        FROM signals
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC, id DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    if row is None or row["stop_loss"] is None:
        return None
    return float(row["stop_loss"])


def _open_positions(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(con, "positions"):
        return []
    cols = _columns(con, "positions")
    if "symbol" not in cols:
        return []
    select_cols = [column for column in ("symbol", "name", "quantity", "avg_cost", "stop_loss", "take_profit") if column in cols]
    where = "WHERE COALESCE(status, 'open') = 'open'" if "status" in cols else ""
    rows = con.execute(f"SELECT {', '.join(select_cols)} FROM positions {where} ORDER BY symbol").fetchall()
    return [dict(row) for row in rows]


def _position_risk_lines(con: sqlite3.Connection, as_of: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pos in _open_positions(con):
        symbol = str(pos["symbol"])
        price = _latest_price(con, symbol, as_of)
        stop = pos.get("stop_loss")
        if stop is None:
            stop = _latest_signal_stop(con, symbol, as_of)
        distance = None
        if price and price.get("close") not in (None, 0) and stop is not None:
            distance = (float(price["close"]) - float(stop)) / float(price["close"]) * 100
        rows.append(
            {
                "标的": f"{symbol} {pos.get('name') or ''}".strip(),
                "现价": price.get("close") if price else None,
                "止损位": stop,
                "距止损": None if distance is None else f"{distance:.2f}%",
                "日期": price.get("date") if price else "缺行情",
            }
        )
    return rows


def _event_rows(con: sqlite3.Connection, as_of: str, symbols: set[str]) -> list[dict[str, Any]]:
    if not _table_exists(con, "corporate_events"):
        return []
    cols = _columns(con, "corporate_events")
    if not {"symbol", "event_type", "event_date"} <= cols:
        return []
    placeholders = ",".join("?" for _ in symbols) or "''"
    params: list[Any] = [as_of, *sorted(symbols)]
    rows = con.execute(
        f"""
        SELECT symbol, event_type, title, event_date
        FROM corporate_events
        WHERE date(event_date) = date(?)
          AND symbol IN ({placeholders})
          AND (event_type LIKE '%解禁%' OR event_type LIKE '%复牌%' OR event_type LIKE '%定增%')
        ORDER BY symbol, event_type
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _overnight_news_lines(con: sqlite3.Connection, as_of: str, symbols: set[str]) -> list[str]:
    start = _dt_prev_1800(as_of)
    lines: list[str] = []
    for table, title_col, time_col, label in (
        ("announcements", "title", "published_at", "公告"),
        ("news", "title", "published_at", "新闻"),
    ):
        if not _table_exists(con, table) or not {"symbol", title_col, time_col} <= _columns(con, table):
            lines.append(f"{label}:表缺失,跳过")
            continue
        placeholders = ",".join("?" for _ in symbols) or "''"
        params: list[Any] = [start.isoformat(sep=" "), *sorted(symbols)]
        count = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE datetime({time_col}) >= datetime(?) AND symbol IN ({placeholders})",
            params,
        ).fetchone()[0]
        top_rows = con.execute(
            f"""
            SELECT symbol, {title_col} AS title
            FROM {table}
            WHERE datetime({time_col}) >= datetime(?) AND symbol IN ({placeholders})
            ORDER BY datetime({time_col}) DESC
            LIMIT 3
            """,
            params,
        ).fetchall()
        titles = [f"{row['symbol']} {row['title']}" for row in top_rows]
        lines.append(f"{label}:新增{count}条" + (f"; top3: {' / '.join(titles)}" if titles else ""))
    return lines


def _overseas_lines(con: sqlite3.Connection) -> list[str]:
    if not _table_exists(con, "overseas_snapshots"):
        return ["海外隔夜:表缺失,跳过"]
    cols = _columns(con, "overseas_snapshots")
    if not {"symbol", "name", "snap_date"} <= cols:
        return ["海外隔夜:字段缺失,跳过"]
    note_select = ", note" if "note" in cols else ""
    rows = con.execute(
        f"""
        SELECT symbol, name, snap_date, close, chg_pct_1d{note_select}
        FROM overseas_snapshots
        ORDER BY datetime(snap_date) DESC
        LIMIT 5
        """
    ).fetchall()
    if not rows:
        return ["海外隔夜:暂无最新快照"]
    return [
        f"{row['symbol']} {row['name']} {_date_only(row['snap_date'])} 涨跌{format_cn_number(row['chg_pct_1d'])}%"
        for row in rows
    ]


def build_premarket_report(*, db_path: str | Path | None = None, as_of: str | None = None) -> dict[str, Any]:
    day = _now_date(as_of)
    with _connect(db_path) as con:
        symbols = _universe_symbols(con) | _holding_symbols(con)
        event_lines = [
            f"{row['symbol']} 今日{row['event_type']}: {row.get('title') or ''}".strip()
            for row in _event_rows(con, day, symbols)
        ]
        sections = [
            ("盘前看", [f"日期:{day}", "定位:只看风险和待观察事项,已列入今晚盘后决断。"]),
            ("海外隔夜", _overseas_lines(con)),
            ("今日事件日历", event_lines or ["今日未见解禁/复牌/定增事件"]),
            ("隔夜公告新闻", _overnight_news_lines(con, day, symbols)),
            ("持仓风险线", _position_risk_lines(con, day) or ["当前无持仓风险线"]),
        ]
    text = render_report(sections, glossary_terms={"解禁", "定增", "止损位"})
    assert_no_trade_words(text)
    return {"ok": True, "mode": "premarket", "date": day, "text": text}


def _proximity_alerts(con: sqlite3.Connection, as_of: str, threshold_pct: float = 3.0) -> list[str]:
    alerts: list[str] = []
    for line in _position_risk_lines(con, as_of):
        distance_text = str(line.get("距止损") or "")
        if not distance_text.endswith("%"):
            continue
        try:
            distance = float(distance_text[:-1])
        except ValueError:
            continue
        if distance <= threshold_pct:
            alerts.append(
                f"{line['标的']} 距止损位 {distance:.2f}%,盘中只记录,已列入今晚盘后决断。"
            )
    return alerts


def _move_flags(con: sqlite3.Connection, as_of: str, symbols: set[str]) -> list[str]:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return ["异动:缺少价格表,跳过"]
    flags: list[str] = []
    for symbol in sorted(symbols):
        rows = con.execute(
            """
            SELECT date, close
            FROM prices
            WHERE symbol = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 2
            """,
            (symbol, as_of),
        ).fetchall()
        if len(rows) < 2 or not rows[1]["close"]:
            continue
        change = (float(rows[0]["close"]) / float(rows[1]["close"]) - 1) * 100
        if abs(change) > 6:
            flags.append(f"{symbol} 近两日价格异动 {change:+.2f}%")
    return flags or ["异动:未见超过6%的低成本价格异动"]


def build_intraday_report(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    watchtower_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    day = _now_date(as_of)
    with _connect(db_path) as con:
        symbols = _universe_symbols(con) | _holding_symbols(con)
        proximity = _proximity_alerts(con, day)
    if watchtower_builder is None:
        from backend.tools.m60_watchtower import build_watchtower_report

        watchtower_builder = build_watchtower_report
    try:
        watchtower = watchtower_builder(db_path=db_path, as_of=day)
        wt_lines = [
            watchtower.get("summary", {}).get("text", "观察哨完成"),
            *[
                f"{item.get('symbol')} {item.get('trigger_type')}:已列入今晚盘后决断"
                for item in watchtower.get("triggers", [])[:8]
            ],
        ]
    except Exception as exc:  # noqa: BLE001 - intraday must stay readable.
        wt_lines = [f"⚠️ 观察哨失败:{type(exc).__name__}: {exc}"]
    with _connect(db_path) as con:
        move_flags = _move_flags(con, day, symbols)
    sections = [
        ("盘中记", [f"日期:{day}", "定位:只记录触发和风险线,不在盘中下结论。"]),
        ("观察哨触发", wt_lines),
        ("止损位接近", proximity or ["暂无3%以内接近止损位的持仓"]),
        ("价格异动", move_flags),
        ("收口", ["以上仅记录,决断在盘后。"]),
    ]
    text = render_report(sections, glossary_terms={"止损位", "主力资金", "龙虎榜", "动量"})
    assert_no_trade_words(text)
    return {"ok": True, "mode": "intraday", "date": day, "text": text}


def _step_result(name: str, func: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"name": name, "ok": True, "result": func()}
    except Exception as exc:  # noqa: BLE001 - postmarket is explicitly resilient.
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _run_backfill_drip(as_of: str) -> dict[str, Any]:
    from backend.tools import m61_backfill

    db = None
    try:
        from backend.data.database import SessionLocal
        from backend.data.orm import Base

        db = SessionLocal()
        Base.metadata.create_all(bind=db.get_bind())
        start = date.fromisoformat(as_of)
        stocks = []
        if DEFAULT_UNIVERSE_PATH.exists():
            stocks = m61_backfill._load_universe(str(DEFAULT_UNIVERSE_PATH), limit=3)
        results: dict[str, Any] = {}
        for category in ("fund_flow", "announcements", "corporate_events"):
            inserted, degradations = m61_backfill._backfill_stock_category(category, stocks, start, start, db) if category != "corporate_events" else m61_backfill._backfill_corporate_events(stocks, start, start, db)
            results[category] = {"inserted": inserted, "degradations": degradations[:5]}
        inserted, degradations = m61_backfill._backfill_overseas(db)
        results["overseas"] = {"inserted": inserted, "degradations": degradations[:5]}
        return results
    finally:
        if db is not None:
            db.close()


def _run_accrual(as_of: str, *, no_llm: bool) -> dict[str, Any]:
    from backend.tools.m54_daily_accrual import compute_progress, run_daily_accrual

    if no_llm:
        return {"skipped": True, "reason": "--no-llm:跳过会消耗LLM的accrual scoring", "progress": compute_progress()}
    return run_daily_accrual(date=as_of)


def _run_exit_shadow() -> dict[str, Any]:
    from backend.tools.m58_exit_shadow import build_shadow_report
    from paper_trading.test2_ab_data import DEFAULT_UNIVERSE

    return build_shadow_report(db_path=default_sqlite_path(), universe_path=DEFAULT_UNIVERSE)


def _run_panel(as_of: str) -> dict[str, Any]:
    from backend.tools.m59_panel import build_panel

    return build_panel(as_of=as_of)


def _run_discretion(panel: dict[str, Any], db_path: str | Path | None, as_of: str) -> dict[str, Any]:
    from backend.tools.m59_discretion import build_discretion_cards

    return build_discretion_cards(panel, db_path=db_path, as_of=as_of)


def _run_second_entry_ledger(db_path: str | Path | None, as_of: str) -> dict[str, Any]:
    from backend.tools.m60_second_entry import build_second_entry_ledger

    return build_second_entry_ledger(db_path=db_path, as_of=as_of)


def _run_task_capsule(
    *,
    db_path: str | Path | None,
    as_of: str,
    steps: list[dict[str, Any]],
    router: dict[str, Any] | None,
) -> dict[str, Any]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.memory.task_capsule import write_task_capsule

    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    engine = create_engine(f"sqlite:///{resolved}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        ok_steps = [step["name"] for step in steps if step.get("ok")]
        failed_steps = [step["name"] for step in steps if not step.get("ok")]
        pending = (router or {}).get("pending") if isinstance(router, dict) else []
        symbols = sorted({
            str(item.get("target"))
            for item in pending or []
            if isinstance(item, dict) and item.get("target") and str(item.get("target")).isdigit()
        })[:5]
        capsule = write_task_capsule(
            db,
            task_type="data_refresh",
            goal=f"M63 postmarket finished for {as_of}",
            symbols=symbols,
            themes=["M63", "盘后决"],
            confirmed_facts=[
                f"completed_steps={','.join(ok_steps)}",
                f"failed_steps={','.join(failed_steps) if failed_steps else 'none'}",
                f"pending_queue={len(pending or [])}",
            ],
            decisions=["仅生成盘后研究上下文,不执行真实交易"],
            open_loops=[f"{item.get('target')}:{item.get('reason')}" for item in (pending or [])[:5] if isinstance(item, dict)],
            next_actions=["新会话先读取 latest_task_capsule,再按需 drilldown 到 M63 报告和队列"],
            used_memory_refs=[],
            artifact_refs=[
                f"paper_trading/m63_out/postmarket_{as_of}.md",
                str((router or {}).get("queue_path") or ""),
            ],
            trust_state="draft",
            as_of=as_of,
            capsule_id=f"m63_postmarket:{as_of}",
        )
        return {"capsule_id": capsule["capsule_id"], "token_estimate": capsule["token_estimate"]}
    finally:
        db.close()
        engine.dispose()


def load_queue(path: Path = DEFAULT_QUEUE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def save_queue(queue: list[dict[str, Any]], path: Path = DEFAULT_QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_compact_queue(queue), ensure_ascii=False, indent=2), encoding="utf-8")


def _queue_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _compact_queue(queue: list[dict[str, Any]], *, today: date | None = None) -> list[dict[str, Any]]:
    anchors = [_queue_date(item.get("done_at")) for item in queue]
    anchor = max([today or date.today(), *(item for item in anchors if item is not None)])
    cutoff = anchor - timedelta(days=QUEUE_DONE_TTL_DAYS)
    compacted: list[dict[str, Any]] = []
    latest_done_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for item in queue:
        if item.get("status") != "done":
            compacted.append(item)
            continue
        done_at = _queue_date(item.get("done_at"))
        if done_at is None or done_at < cutoff:
            continue
        key = (str(item.get("target") or ""), str(item.get("trigger_rule") or ""))
        previous = latest_done_by_key.get(key)
        if previous is None or done_at >= (_queue_date(previous.get("done_at")) or date.min):
            latest_done_by_key[key] = item
    latest_done_ids = {id(item) for item in latest_done_by_key.values()}
    for item in queue:
        if item.get("status") == "done" and id(item) in latest_done_ids:
            compacted.append(item)
    return compacted


def _enqueue(
    queue: list[dict[str, Any]],
    *,
    as_of: str,
    target: str,
    reason: str,
    trigger_rule: str,
) -> bool:
    for item in queue:
        if item.get("status") == "pending" and item.get("target") == target and item.get("trigger_rule") == trigger_rule:
            return False
    queue.append(
        {
            "id": f"{as_of}:{trigger_rule}:{target}",
            "created_at": as_of,
            "target": target,
            "reason": reason,
            "trigger_rule": trigger_rule,
            "status": "pending",
        }
    )
    return True


def _auto_refresh_label(symbol: str, *, db) -> dict[str, Any]:
    old = os.environ.get("LOCAL_CLI_PREFER_CODEX")
    os.environ["LOCAL_CLI_PREFER_CODEX"] = "false"
    try:
        from backend.api.routes.watchlist import run_long_term_label

        result = run_long_term_label(symbol, db=db)
        return {"symbol": symbol, "refreshed": True, "result": result}
    finally:
        if old is None:
            os.environ.pop("LOCAL_CLI_PREFER_CODEX", None)
        else:
            os.environ["LOCAL_CLI_PREFER_CODEX"] = old


def _expired_label_symbols(con: sqlite3.Connection, as_of: str, symbols: set[str]) -> list[str]:
    if not _table_exists(con, "long_term_labels") or not {"symbol", "expires_at"} <= _columns(con, "long_term_labels"):
        return []
    placeholders = ",".join("?" for _ in symbols) or "''"
    rows = con.execute(
        f"""
        SELECT symbol, MAX(expires_at) AS expires_at
        FROM long_term_labels
        WHERE symbol IN ({placeholders})
        GROUP BY symbol
        HAVING date(expires_at) < date(?)
        ORDER BY date(expires_at), symbol
        """,
        [*sorted(symbols), as_of],
    ).fetchall()
    return [str(row["symbol"]) for row in rows]


def _load_history(path: Path = DEFAULT_TRIGGER_HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _save_history(history: list[dict[str, Any]], path: Path = DEFAULT_TRIGGER_HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_watchtower_history(
    watchtower: dict[str, Any],
    *,
    as_of: str,
    history_path: Path = DEFAULT_TRIGGER_HISTORY_PATH,
    history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    history = _load_history(history_path) if history is None else history
    existing = {
        (item.get("date"), item.get("target"), item.get("trigger_type"))
        for item in history
    }
    for trigger in watchtower.get("triggers", []) if isinstance(watchtower, dict) else []:
        targets = [trigger.get("symbol"), *(trigger.get("themes") or [])]
        for target in [str(t) for t in targets if t]:
            key = (as_of, target, trigger.get("trigger_type"))
            if key in existing:
                continue
            history.append({"date": as_of, "target": target, "trigger_type": trigger.get("trigger_type")})
    cutoff = date.fromisoformat(as_of) - timedelta(days=14)
    history = [item for item in history if date.fromisoformat(str(item["date"])) >= cutoff]
    _save_history(history, history_path)
    return history


def _history_rule(item: dict[str, Any]) -> str:
    return str(item.get("trigger_rule") or item.get("trigger_type") or "")


def _trading_days_since(con: sqlite3.Connection, symbol: str, *, start: str, end: str) -> int:
    if not _table_exists(con, "prices") or not {"symbol", "date"} <= _columns(con, "prices"):
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    row = con.execute(
        """
        SELECT COUNT(DISTINCT date) AS count
        FROM prices
        WHERE symbol = ? AND date(date) > date(?) AND date(date) <= date(?)
        """,
        (symbol, start, end),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def _r6_recently_recorded(con: sqlite3.Connection, history: list[dict[str, Any]], symbol: str, *, as_of: str) -> bool:
    dates: list[str] = []
    for item in history:
        if str(item.get("target")) != symbol or _history_rule(item) != R6_RULE or not item.get("date"):
            continue
        try:
            item_date = date.fromisoformat(str(item["date"])[:10])
        except ValueError:
            continue
        if item_date <= date.fromisoformat(as_of):
            dates.append(item_date.isoformat())
    if not dates:
        return False
    return _trading_days_since(con, symbol, start=max(dates), end=as_of) <= R6_DAMPER_DAYS


def _record_r6_history(
    history: list[dict[str, Any]],
    *,
    as_of: str,
    symbol: str,
    chg_1d: float,
    chg_5d: float | None,
    reason: str,
) -> bool:
    key = (as_of, symbol, R6_RULE)
    existing = {
        (str(item.get("date")), str(item.get("target")), _history_rule(item))
        for item in history
    }
    if key in existing:
        return False
    history.append(
        {
            "date": as_of,
            "target": symbol,
            "trigger_type": R6_RULE,
            "trigger_rule": R6_RULE,
            "reason": reason,
            "chg_1d_pct": round(chg_1d, 2),
            "chg_5d_pct": None if chg_5d is None else round(chg_5d, 2),
        }
    )
    return True


def _run_r6_price_moves(
    con: sqlite3.Connection,
    queue: list[dict[str, Any]],
    history: list[dict[str, Any]],
    *,
    as_of: str,
    symbols: set[str],
) -> list[dict[str, Any]]:
    enqueued: list[dict[str, Any]] = []
    history_changed = False
    for symbol in sorted(symbols):
        move = _price_move(con, symbol, as_of)
        if move is None:
            continue
        chg_1d = float(move["chg_1d"])
        chg_5d = move.get("chg_5d")
        chg_5d_value = None if chg_5d is None else float(chg_5d)
        if abs(chg_1d) < R6_CHG_1D_PCT and (chg_5d_value is None or abs(chg_5d_value) < R6_CHG_5D_PCT):
            continue
        if _r6_recently_recorded(con, history, symbol, as_of=as_of):
            continue
        direction_source = chg_1d if abs(chg_1d) >= R6_CHG_1D_PCT else float(chg_5d_value or 0)
        direction = "急涨(考虑观察哨确认/第二时间评估)" if direction_source > 0 else "急跌(考虑持仓决断/避雷复核)"
        reason = f"价格异动 1日{chg_1d:+.1f}%/5日{(chg_5d_value or 0):+.1f}% {direction}"
        history_changed = _record_r6_history(
            history,
            as_of=as_of,
            symbol=symbol,
            chg_1d=chg_1d,
            chg_5d=chg_5d_value,
            reason=reason,
        ) or history_changed
        if _enqueue(queue, as_of=as_of, target=symbol, reason=reason, trigger_rule=R6_RULE):
            enqueued.append(queue[-1])
    if history_changed:
        cutoff = date.fromisoformat(as_of) - timedelta(days=14)
        history[:] = [item for item in history if date.fromisoformat(str(item["date"])[:10]) >= cutoff]
    return enqueued


def _opinion_change_stub(*, as_of: str) -> list[dict[str, Any]]:
    """M63-2 will wire 喂观点 here; queue entries will use target/reason/trigger_rule/status."""
    return []


def run_trigger_router(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    watchtower: dict[str, Any] | None = None,
    queue_path: Path = DEFAULT_QUEUE_PATH,
    history_path: Path = DEFAULT_TRIGGER_HISTORY_PATH,
    auto_refresh_limit: int = AUTO_REFRESH_LIMIT,
    auto_refresh_fn: Callable[[str], Any] | None = None,
    allow_auto_refresh: bool = True,
) -> dict[str, Any]:
    day = _now_date(as_of)
    queue = load_queue(queue_path)
    auto_refreshed: list[str] = []
    enqueued: list[dict[str, Any]] = []
    history = _load_history(history_path)
    with _connect(db_path) as con:
        universe = _universe_symbols(con) | _holding_symbols(con)
        expired = _expired_label_symbols(con, day, universe)
        refresh_slice = expired[:auto_refresh_limit] if allow_auto_refresh else []
        queue_slice = expired[auto_refresh_limit:] if allow_auto_refresh else expired
        for symbol in refresh_slice:
            if auto_refresh_fn is not None:
                auto_refresh_fn(symbol)
            else:
                from backend.data.database import SessionLocal

                db = SessionLocal()
                try:
                    _auto_refresh_label(symbol, db=db)
                finally:
                    db.close()
            auto_refreshed.append(symbol)
        for symbol in queue_slice:
            if _enqueue(
                queue,
                as_of=day,
                target=symbol,
                reason=(
                    f"长期标签已过期,超过每日自动刷新上限{auto_refresh_limit}"
                    if allow_auto_refresh
                    else "--no-llm:长期标签已过期,已排队等待人工触发刷新"
                ),
                trigger_rule="R1_label_expired",
            ):
                enqueued.append(queue[-1])
        for row in _event_rows(con, day, universe):
            event_type = str(row.get("event_type") or "")
            title = str(row.get("title") or "")
            if any(keyword in event_type + title for keyword in ("解禁", "监管", "定增")):
                if _enqueue(
                    queue,
                    as_of=day,
                    target=str(row["symbol"]),
                    reason=f"今日事件:{event_type} {title}".strip(),
                    trigger_rule="R2_major_event",
                ):
                    enqueued.append(queue[-1])
        enqueued.extend(_run_r6_price_moves(con, queue, history, as_of=day, symbols=universe))
    if watchtower is not None:
        history = _record_watchtower_history(watchtower, as_of=day, history_path=history_path, history=history)
        recent_start = date.fromisoformat(day) - timedelta(days=4)
        distinct_days: dict[str, set[str]] = {}
        for item in history:
            item_date = date.fromisoformat(str(item["date"]))
            if recent_start <= item_date <= date.fromisoformat(day):
                distinct_days.setdefault(str(item["target"]), set()).add(str(item["date"]))
        for target, days in distinct_days.items():
            if len(days) >= 3:
                if _enqueue(
                    queue,
                    as_of=day,
                    target=target,
                    reason=f"观察哨5日内{len(days)}个不同交易日重复触发",
                    trigger_rule="R3_watchtower_repeat",
                ):
                    enqueued.append(queue[-1])
    for item in _opinion_change_stub(as_of=day):
        if _enqueue(queue, as_of=day, **item):
            enqueued.append(queue[-1])
    _save_history(history, history_path)
    save_queue(queue, queue_path)
    pending = [item for item in queue if item.get("status") == "pending"]
    return {
        "queue_path": str(queue_path),
        "history_path": str(history_path),
        "auto_refreshed": auto_refreshed,
        "enqueued": enqueued,
        "pending": pending,
    }


def _watchtower_lines(report: dict[str, Any] | None) -> list[str]:
    if not report:
        return ["观察哨:无结果"]
    lines = [report.get("summary", {}).get("text", "观察哨完成")]
    for trigger in report.get("triggers", [])[:10]:
        lines.append(f"{trigger.get('symbol')} {trigger.get('trigger_type')} {trigger.get('card') or ''}".strip())
    return lines


def _format_stop_distance(value: Any) -> str:
    if value is None:
        return "- (止损数据缺失)"
    text = format_cn_number(value)
    return text if text.endswith("%") else f"{text}%"


def _panel_lines(panel: dict[str, Any] | None) -> list[str]:
    if not panel:
        return ["面板:无结果"]
    lines = [panel.get("summary", {}).get("text", "面板完成")]
    position_items = panel.get("position_health", {}).get("items", [])
    candidate_items = panel.get("buy_candidates", {}).get("items", [])
    risk_actions: list[tuple[str, str]] = []
    seen_actions: set[tuple[str, str]] = set()
    for section in ("event_warnings", "momentum_tail", "concentration"):
        for item in (panel.get("risk_warnings", {}).get(section, {}) or {}).get("items") or []:
            action = str(item.get("protective_action") or "")
            if not action or action.startswith("数据不足") or "维持观察" in action:
                continue
            key = (str(item.get("symbol") or ""), action)
            if key in seen_actions:
                continue
            seen_actions.add(key)
            risk_actions.append(key)
    protective_count = sum(1 for item in position_items if item.get("protective_action")) + len(risk_actions)
    stop_flag_count = sum(1 for item in position_items if item.get("stop_flags"))
    quality_flag_count = sum(1 for item in candidate_items if item.get("quality_flags"))
    degraded_symbols = {
        str(item.get("symbol"))
        for item in [*position_items, *candidate_items]
        if ((item.get("research_reference") or {}).get("copilot") or {}).get("trigger_quality") == "degraded"
        and item.get("symbol")
    }
    trigger_degraded_count = len(degraded_symbols)
    if protective_count or stop_flag_count or quality_flag_count or trigger_degraded_count:
        line = f"保护动作 {protective_count} 条 / 止损贴身旗 {stop_flag_count} 条 / 质量旗 {quality_flag_count} 条"
        if trigger_degraded_count:
            line += f" / 触发降级 {trigger_degraded_count} 条"
        lines.append(line)
    for item in panel.get("position_health", {}).get("items", [])[:8]:
        label = (item.get("research_reference") or {}).get("long_term_label") or {}
        symbol = format_cn_number(item.get("symbol"))
        label_text = format_cn_number(label.get("label"))
        line = (
            f"持仓 {symbol} 现价{format_cn_number(item.get('current_price'))} "
            f"距止损{_format_stop_distance(item.get('distance_to_stop_loss_pct'))} 长期标签{label_text}"
        )
        if item.get("protective_action"):
            line += f" → 保护动作: {item.get('protective_action')}"
        if item.get("stop_flags"):
            line += f" 旗标: {', '.join(item.get('stop_flags') or [])}"
        lines.append(line)
    for item in candidate_items[:8]:
        if item.get("quality_flags"):
            lines.append(f"候选 {format_cn_number(item.get('symbol'))} 质量旗标: {', '.join(item.get('quality_flags') or [])}(建议仓位上限减半)")
    for symbol, action in risk_actions[:5]:
        lines.append(f"风险警示 {format_cn_number(symbol)} → 保护动作: {action}")
    for item in panel.get("risk_warnings", {}).get("event_warnings", {}).get("items", [])[:8]:
        if isinstance(item, dict):
            lines.append(
                f"⚠️ {format_cn_number(item.get('symbol'))} {item.get('name') or ''} "
                f"{format_cn_number(item.get('event_type'))} {format_cn_number(item.get('event_date'))}".strip()
            )
        else:
            lines.append(re.sub(r"\s*\(\{.*\}\)", "", str(item)))
    return inject_semantic_notes(lines)


def build_postmarket_report(
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    no_llm: bool = False,
    step_overrides: dict[str, Callable[[], Any]] | None = None,
    queue_path: Path = DEFAULT_QUEUE_PATH,
    history_path: Path = DEFAULT_TRIGGER_HISTORY_PATH,
) -> dict[str, Any]:
    day = _now_date(as_of)
    overrides = step_overrides or {}
    steps: list[dict[str, Any]] = []
    steps.append(_step_result("m61_backfill_drip", overrides.get("m61_backfill_drip", lambda: _run_backfill_drip(day))))
    steps.append(_step_result("m60_watchtower", overrides.get("m60_watchtower", lambda: __import__("backend.tools.m60_watchtower", fromlist=["build_watchtower_report"]).build_watchtower_report(db_path=db_path, as_of=day))))
    steps.append(_step_result("m60_second_entry", overrides.get("m60_second_entry", lambda: _run_second_entry_ledger(db_path, day))))
    steps.append(_step_result("m54_daily_accrual", overrides.get("m54_daily_accrual", lambda: _run_accrual(day, no_llm=no_llm))))
    steps.append(_step_result("m58_exit_shadow", overrides.get("m58_exit_shadow", _run_exit_shadow)))
    steps.append(_step_result("m59_panel", overrides.get("m59_panel", lambda: _run_panel(day))))
    panel = next((step["result"] for step in steps if step["name"] == "m59_panel" and step["ok"]), None)
    if panel is not None:
        from backend.tools.m59_discretion import m59_discretion_enabled

        if m59_discretion_enabled():
            steps.append(
                _step_result(
                    "m59_discretion",
                    overrides.get("m59_discretion", lambda: _run_discretion(panel, db_path, day)),
                )
            )
    watchtower = next((step["result"] for step in steps if step["name"] == "m60_watchtower" and step["ok"]), None)
    steps.append(
        _step_result(
            "trigger_router",
            overrides.get(
                "trigger_router",
                lambda: run_trigger_router(
                    db_path=db_path,
                    as_of=day,
                    watchtower=watchtower,
                    queue_path=queue_path,
                    history_path=history_path,
                    allow_auto_refresh=not no_llm,
                ),
            ),
        )
    )
    router = next((step["result"] for step in steps if step["name"] == "trigger_router" and step["ok"]), {})
    steps.append(
        _step_result(
            "task_capsule",
            overrides.get(
                "task_capsule",
                lambda: _run_task_capsule(db_path=db_path, as_of=day, steps=steps, router=router),
            ),
        )
    )
    discretion = next((step["result"] for step in steps if step["name"] == "m59_discretion" and step["ok"]), None)
    from backend.tools.m59_discretion import render_card_lines

    failures = [f"⚠️ {step['name']} 失败:{step['error']}" for step in steps if not step["ok"]]
    accrual = next((step["result"] for step in steps if step["name"] == "m54_daily_accrual" and step["ok"]), {})
    exit_shadow = next((step["result"] for step in steps if step["name"] == "m58_exit_shadow" and step["ok"]), {})
    pending = router.get("pending", []) if isinstance(router, dict) else []
    sections = [
        ("盘后决", [f"日期:{day}", "定位:汇总盘后证据、触发队列和数据健康。"]),
        ("执行步骤", [f"{step['name']}:{'OK' if step['ok'] else 'FAIL'}" for step in steps] + failures),
        ("核心面板", _panel_lines(panel)),
        (
            "🧭 裁量参考区（LLM,仅供参考）",
            render_card_lines(discretion),
        ),
        ("观察哨卡片", _watchtower_lines(watchtower)),
        (
            "影子出场",
            [
                f"窗口:{(exit_shadow.get('meta') or {}).get('window')}",
                f"分歧:{'无' if exit_shadow.get('no_divergence_yet') else '有'}",
                f"持仓中:{exit_shadow.get('open_position_count', '-')}",
            ],
        ),
        (
            "accrual进度",
            [
                accrual.get("reason", "已运行") if isinstance(accrual, dict) and accrual.get("skipped") else "已运行",
                f"gate:{((accrual.get('progress') or {}).get('gate') if isinstance(accrual, dict) else '-')}",
            ],
        ),
        (
            "待研究队列",
            [f"待研究({len(pending)}): {item['target']} -- {item['reason']}" for item in pending]
            + ["跑: python3 -m backend.tools.m63_research --target <X>"],
        ),
        (
            "data-health",
            [
                f"queue:{router.get('queue_path') if isinstance(router, dict) else '-'}",
                f"trigger-history:{router.get('history_path') if isinstance(router, dict) else '-'}",
                "R3说明:若历史不可查询,M63从本地trigger-history JSON自今日开始累积。",
            ],
        ),
    ]
    text = render_report(
        sections,
        glossary_terms={"止损位", "止盈位", "ATR", "规避", "观望", "可关注", "动量", "解禁", "定增", "Piotroski"},
    )
    text = enforce_language_guard(text, mode="sanitize")
    return {"ok": True, "mode": "postmarket", "date": day, "text": text, "steps": steps, "router": router}


def write_report(mode: str, as_of: str, text: str, output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{mode}_{as_of}.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_mode(args: argparse.Namespace) -> dict[str, Any]:
    kwargs = {"db_path": args.db, "as_of": args.date}
    if args.mode == "premarket":
        result = build_premarket_report(**kwargs)
    elif args.mode == "intraday":
        result = build_intraday_report(**kwargs)
    else:
        result = build_postmarket_report(**kwargs, no_llm=args.no_llm)
    path = write_report(args.mode, result["date"], result["text"])
    result["output_path"] = str(path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M63 daily touchpoint reports")
    parser.add_argument("--mode", required=True, choices=("premarket", "intraday", "postmarket"))
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM-burning postmarket steps")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope instead of text only")
    parser.add_argument("--db", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--date", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_mode(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(result["text"])
        print(f"wrote {result['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
