"""M60 thesis-condition compiler and deterministic evaluators.

Phase 1 is deliberately rule-only: compile the data-shaped parts of Chinese
validation/invalidation prose into JSON specs, and mark the rest as
``manual_review`` instead of pretending they are machine-observable.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.research.forward_thesis import theme_key_from_statement

CONDITION_TYPES = {"validation", "invalidation"}

EVENT_TABLES = ["announcements", "research_reports", "corporate_events", "news"]
OVERSEAS_KEYWORDS = (
    "ASML",
    "backlog",
    "AI capex",
    "NV",
    "NVIDIA",
    "Corning",
    "Lumentum",
    "Meta",
    "美光",
    "SCA",
    "HBM",
    "DRAM",
    "NAND",
)
NEGATIVE_LONG_TERM_LABELS = ("规避", "观望", "估值偏高")


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def ensure_specs_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS thesis_condition_specs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            forward_thesis_id INTEGER NOT NULL,
            condition_type TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            compiled_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_thesis_condition_specs_thesis
        ON thesis_condition_specs(forward_thesis_id, condition_type)
        """
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _pct(raw: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", raw)
    return float(match.group(1)) if match else None


def _days(raw: str, default: int = 3) -> int:
    match = re.search(r"持续\s*([0-9]+)\s*[日天]", raw)
    return int(match.group(1)) if match else default


def _direction(raw: str) -> str:
    if any(word in raw for word in ("流出", "回调", "下跌", "跌", "走弱", "转弱")):
        return "down"
    return "up"


def _keyword_tail(raw: str) -> list[str]:
    quoted = re.findall(r"[“\"']([^”\"']+)[”\"']", raw)
    if quoted:
        return [item.strip() for item in quoted if item.strip()]
    marker = re.search(r"关键词[:：]?\s*([^，。；;]+)", raw)
    if marker:
        return [item.strip() for item in re.split(r"[,，/、\s]+", marker.group(1)) if item.strip()]
    candidates = [
        word
        for word in ("公告", "研报", "解禁", "订单", "合同", "中标", "减持", "监管", "评级", "业绩")
        if word in raw
    ]
    return candidates


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = item.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _event_keywords(raw: str) -> list[str]:
    pairs = (
        ("订单下修", "订单下修"),
        ("订单", "订单"),
        ("合同", "合同"),
        ("中标", "中标"),
        ("交付", "交付"),
        ("收入", "收入"),
        ("营收", "营收"),
        ("利润", "利润"),
        ("净利", "净利"),
        ("毛利率", "毛利率"),
        ("产能利用率", "产能利用率"),
        ("产能扩张", "产能扩张"),
        ("扩产", "扩产"),
        ("客户验证", "客户验证"),
        ("份额", "份额"),
        ("产品结构", "产品结构"),
        ("交期缩短", "交期缩短"),
        ("交期", "交期"),
        ("价格松动", "价格松动"),
        ("涨价", "涨价"),
        ("供给约束", "供给约束"),
        ("库存", "库存"),
        ("回购", "回购"),
        ("诉讼", "诉讼"),
        ("移出清单", "移出清单"),
        ("出口管制", "出口管制"),
        ("投资禁令", "投资禁令"),
        ("强制剥离", "强制剥离"),
        ("商誉减值", "商誉减值"),
        ("减持", "减持"),
        ("回落", "回落"),
        ("转弱", "转弱"),
        ("松动", "松动"),
    )
    return _dedupe([*_keyword_tail(raw), *[keyword for needle, keyword in pairs if needle in raw]])


def _looks_event_observable(raw: str) -> bool:
    markers = (
        "订单",
        "交付",
        "收入",
        "营收",
        "利润",
        "净利",
        "毛利率",
        "产能",
        "客户验证",
        "份额",
        "产品结构",
        "交期",
        "价格",
        "供给",
        "库存",
        "回购",
        "诉讼",
        "清单",
        "出口管制",
        "投资禁令",
        "强制剥离",
        "商誉减值",
        "减持",
    )
    return any(marker in raw for marker in markers) and bool(_event_keywords(raw))


def _financial_metric_threshold(raw: str) -> dict[str, Any] | None:
    if not any(word in raw for word in ("财报", "营收", "净利", "毛利率", "收入增速")):
        return None
    thresholds: list[dict[str, Any]] = []
    direction = "lte" if any(word in raw for word in ("以下", "跌破", "滑落", "回落")) else "gte"
    if any(word in raw for word in ("营收", "收入", "增速")):
        pct = _pct(raw)
        if pct is not None:
            thresholds.append({"field": "revenue_yoy", "operator": direction, "threshold_pct": pct})
    if "净利" in raw or "利润" in raw or "增速" in raw:
        pct = _pct(raw)
        if pct is not None:
            thresholds.append({"field": "net_profit_yoy", "operator": direction, "threshold_pct": pct})
    gross_margin = re.search(r"毛利率[^0-9%]*([0-9]+(?:\.[0-9]+)?)\s*%", raw)
    if gross_margin:
        thresholds.append(
            {"field": "gross_margin", "operator": "lte" if "跌破" in raw else direction, "threshold_pct": float(gross_margin.group(1))}
        )
    if not thresholds:
        return None
    return {
        "kind": "financial_metric_threshold",
        "params": {"thresholds": thresholds, "join": "any" if "或" in raw else "all"},
        "raw_text": raw,
    }


def _long_term_label_state(raw: str) -> dict[str, Any] | None:
    if "长期标签" not in raw:
        return None
    labels = [label for label in NEGATIVE_LONG_TERM_LABELS if label in raw]
    if not labels:
        if "估值约束缓和" in raw:
            labels = ["估值约束缓和"]
        else:
            return None
    return {"kind": "long_term_label_state", "params": {"labels": labels, "match": "any"}, "raw_text": raw}


def _relative_move(raw: str) -> dict[str, Any] | None:
    if "沪深300" not in raw or not any(word in raw for word in ("跑赢", "超额")):
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*pp", raw)
    threshold = float(match.group(1)) if match else 5.0
    window_match = re.search(r"([0-9]+)\s*交易日", raw)
    window_days = int(window_match.group(1)) if window_match else 1
    return {
        "kind": "relative_benchmark_move",
        "params": {"benchmark_symbol": "000300", "threshold_pp": threshold, "window_days": window_days, "direction": "up"},
        "raw_text": raw,
    }


def _research_report_density(raw: str) -> dict[str, Any] | None:
    if not any(word in raw for word in ("研报密度", "研报数量", "覆盖提升", "评级上调")):
        return None
    keywords = _keyword_tail(raw) if "关键词" in raw else []
    return {
        "kind": "research_report_density",
        "params": {"lookback_days": 30, "min_count": 2, "keywords": keywords},
        "raw_text": raw,
    }


def _fund_flow_ma_break(raw: str) -> dict[str, Any] | None:
    if "资金流" not in raw or "净流出" not in raw or "跌破" not in raw or "日均线" not in raw:
        return None
    window_match = re.search(r"([0-9]+)\s*日均线", raw)
    return {
        "kind": "fund_flow_ma_break",
        "params": {"days": _days(raw), "flow_direction": "down", "ma_window": int(window_match.group(1)) if window_match else 20},
        "raw_text": raw,
    }


def _overseas_indicator_keywords(raw: str) -> list[str]:
    return _dedupe([keyword for keyword in OVERSEAS_KEYWORDS if keyword in raw])


def compile_condition(raw_text: str, *, condition_type: str) -> dict[str, Any]:
    if condition_type not in CONDITION_TYPES:
        raise ValueError(f"invalid condition_type: {condition_type}")
    raw = str(raw_text or "").strip()
    pct = _pct(raw)

    for compiled in (
        _financial_metric_threshold(raw),
        _long_term_label_state(raw),
        _relative_move(raw),
        _research_report_density(raw),
        _fund_flow_ma_break(raw),
    ):
        if compiled is not None:
            return compiled

    if "海外" in raw and pct is not None:
        return {
            "kind": "overseas_pct_move",
            "params": {"threshold_pct": pct, "direction": _direction(raw), "field": "chg_pct_1d"},
            "raw_text": raw,
        }

    overseas_keywords = _overseas_indicator_keywords(raw)
    if overseas_keywords or ("海外领先指标" in raw and _event_keywords(raw)):
        return {
            "kind": "overseas_indicator_keyword",
            "params": {"keywords": overseas_keywords or _event_keywords(raw), "lookback_days": 10},
            "raw_text": raw,
        }

    if pct is not None and any(word in raw for word in ("回调", "涨跌", "上涨", "下跌", "涨", "跌")):
        return {
            "kind": "price_pct_move",
            "params": {"threshold_pct": pct, "direction": _direction(raw), "window": "1d"},
            "raw_text": raw,
        }

    if "主力净" in raw and any(word in raw for word in ("流入", "流出")):
        return {
            "kind": "fund_flow_streak",
            "params": {"days": _days(raw), "direction": _direction(raw), "field": "main_net"},
            "raw_text": raw,
        }

    if (any(word in raw for word in ("公告", "研报", "解禁")) and ("关键词" in raw or _keyword_tail(raw))) or _looks_event_observable(raw):
        tables = []
        if "公告" in raw:
            tables.append("announcements")
        if "研报" in raw:
            tables.append("research_reports")
        if "解禁" in raw:
            tables.append("corporate_events")
        if not tables:
            tables = EVENT_TABLES
        return {
            "kind": "event_keyword",
            "params": {"tables": tables, "keywords": _event_keywords(raw), "lookback_days": 5},
            "raw_text": raw,
        }

    return {
        "kind": "manual_review",
        "params": {"reason": "unmatched_rule_template"},
        "raw_text": raw,
    }


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    return parsed if isinstance(parsed, list) else [parsed]


def compile_forward_thesis_conditions(
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_db = Path(db_path) if db_path is not None else default_sqlite_path()
    with _connect(resolved_db) as con:
        ensure_specs_table(con)
        if not _table_exists(con, "forward_theses"):
            return {"forward_theses": 0, "total_conditions": 0, "compiled_conditions": 0, "manual_review_conditions": 0}
        rows = con.execute(
            """
            SELECT id, invalidation_conditions_json, follow_up_metrics_json
            FROM forward_theses
            WHERE symbol IS NULL
              AND statement LIKE '[theme:%'
              AND status IN ('active', 'watch', 'draft')
            ORDER BY id
            """
        ).fetchall()
        con.execute("DELETE FROM thesis_condition_specs")
        now = _utc_now_iso()
        total = compiled = manual = 0
        for row in rows:
            for condition_type, values in (
                ("validation", _json_list(row["follow_up_metrics_json"])),
                ("invalidation", _json_list(row["invalidation_conditions_json"])),
            ):
                for raw in values:
                    total += 1
                    spec = compile_condition(str(raw), condition_type=condition_type)
                    compiled_by = "manual" if spec["kind"] == "manual_review" else "rule"
                    if compiled_by == "manual":
                        manual += 1
                    else:
                        compiled += 1
                    con.execute(
                        """
                        INSERT INTO thesis_condition_specs(
                            forward_thesis_id, condition_type, spec_json, compiled_by, created_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row["id"], condition_type, json.dumps(spec, ensure_ascii=False), compiled_by, now),
                    )
        con.commit()
    return {
        "forward_theses": len(rows),
        "total_conditions": total,
        "compiled_conditions": compiled,
        "manual_review_conditions": manual,
        "coverage_pct": round((compiled / total * 100.0), 2) if total else 0.0,
    }


def evaluate_condition_spec(
    con: sqlite3.Connection,
    *,
    symbol: str,
    as_of: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    kind = spec.get("kind")
    params = spec.get("params") or {}
    if kind == "price_pct_move":
        return _eval_price_pct_move(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "fund_flow_streak":
        return _eval_fund_flow_streak(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "event_keyword":
        return _eval_event_keyword(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "overseas_pct_move":
        return _eval_overseas_pct_move(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "overseas_indicator_keyword":
        return _eval_overseas_indicator_keyword(con, as_of=as_of, params=params)
    if kind == "financial_metric_threshold":
        return _eval_financial_metric_threshold(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "long_term_label_state":
        return _eval_long_term_label_state(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "relative_benchmark_move":
        return _eval_relative_benchmark_move(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "research_report_density":
        return _eval_research_report_density(con, symbol=symbol, as_of=as_of, params=params)
    if kind == "fund_flow_ma_break":
        return _eval_fund_flow_ma_break(con, symbol=symbol, as_of=as_of, params=params)
    return {"triggered": False, "coverage": "manual_review"}


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _parse_day(value: str) -> datetime:
    return datetime.fromisoformat(value[:10])


def _window_start(as_of: str, lookback_days: int) -> str:
    return (_parse_day(as_of) - timedelta(days=lookback_days)).date().isoformat()


def _load_historical_specs(
    con: sqlite3.Connection,
    *,
    condition_type: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if condition_type not in CONDITION_TYPES:
        raise ValueError(f"invalid condition_type: {condition_type}")
    if not _table_exists(con, "thesis_condition_specs") or not _table_exists(con, "forward_theses"):
        return [], {"total": 0, "compiled": 0, "manual_review": 0}
    rows = con.execute(
        """
        SELECT
            s.forward_thesis_id,
            s.condition_type,
            s.spec_json,
            s.compiled_by,
            t.statement,
            t.status
        FROM thesis_condition_specs s
        JOIN forward_theses t ON t.id = s.forward_thesis_id
        WHERE s.condition_type = ?
          AND t.symbol IS NULL
          AND t.statement LIKE '[theme:%'
          AND t.status IN ('active', 'watch', 'draft')
        ORDER BY s.id
        """,
        (condition_type,),
    ).fetchall()
    specs: list[dict[str, Any]] = []
    stats = {"total": 0, "compiled": 0, "manual_review": 0}
    for row in rows:
        try:
            spec = json.loads(str(row["spec_json"]))
        except json.JSONDecodeError:
            continue
        stats["total"] += 1
        if row["compiled_by"] == "manual" or spec.get("kind") == "manual_review":
            stats["manual_review"] += 1
            continue
        stats["compiled"] += 1
        theme_key = theme_key_from_statement(str(row["statement"] or ""))
        if not theme_key:
            continue
        specs.append(
            {
                "forward_thesis_id": int(row["forward_thesis_id"]),
                "theme_key": theme_key,
                "condition_type": str(row["condition_type"]),
                "spec": spec,
            }
        )
    return specs, stats


def _fetch_rows(
    con: sqlite3.Connection,
    table: str,
    cols: Sequence[str],
    *,
    date_col: str,
    start: str,
    end: str,
    symbols: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    if not cols:
        return []
    if not _table_exists(con, table):
        return []
    available = _columns(con, table)
    if not set(cols) <= available or date_col not in available:
        return []
    params: list[Any] = [start, end]
    symbol_clause = ""
    if symbols is not None and "symbol" in available:
        selected = [str(symbol) for symbol in symbols if symbol]
        if not selected:
            return []
        placeholders = ",".join("?" for _ in selected)
        symbol_clause = f" AND symbol IN ({placeholders})"
        params.extend(selected)
    rows = con.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE date({date_col}) >= date(?)
          AND date({date_col}) <= date(?)
          {symbol_clause}
        ORDER BY date({date_col}) ASC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _rows_by_symbol(rows: Sequence[dict[str, Any]], date_col: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        row = dict(row)
        row["_day"] = _day(row.get(date_col))
        grouped.setdefault(symbol, []).append(row)
    return grouped


def _latest_rows_by_date(rows: Sequence[dict[str, Any]], as_of: str, *, exact_latest: bool = False) -> list[dict[str, Any]]:
    eligible = [row for row in rows if str(row.get("_day") or "") <= as_of]
    if exact_latest and (not eligible or str(eligible[-1].get("_day")) != as_of):
        return []
    return eligible


def _eval_cached_condition(
    cache: dict[str, Any],
    *,
    symbol: str,
    as_of: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    kind = spec.get("kind")
    params = spec.get("params") or {}
    if kind == "price_pct_move":
        rows = _latest_rows_by_date(cache["prices"].get(symbol, []), as_of, exact_latest=True)
        if len(rows) < 2:
            return {"triggered": False, "coverage": "missing:as_of_price"}
        cur = float(rows[-1]["close"])
        prev = float(rows[-2]["close"])
        if prev == 0:
            return {"triggered": False, "coverage": "invalid:prev_close_zero"}
        pct = (cur / prev - 1.0) * 100.0
        threshold = float(params.get("threshold_pct") or 0)
        direction = str(params.get("direction") or "up")
        return {"triggered": _threshold_hit(pct, threshold, direction), "coverage": "ok", "value": pct, "threshold_pct": threshold}
    if kind == "relative_benchmark_move":
        window_days = int(params.get("window_days") or 1)
        benchmark = str(params.get("benchmark_symbol") or "000300")
        stock_rows = _latest_rows_by_date(cache["prices"].get(symbol, []), as_of, exact_latest=True)[-(max(window_days + 1, 2)) :]
        index_rows = _latest_rows_by_date(cache["index_prices"].get(benchmark, []), as_of, exact_latest=True)[-(max(window_days + 1, 2)) :]
        if len(stock_rows) < 2 or len(index_rows) < 2:
            return {"triggered": False, "coverage": "missing:relative_prices"}
        stock_now, stock_prev = float(stock_rows[-1]["close"]), float(stock_rows[0]["close"])
        index_now, index_prev = float(index_rows[-1]["close"]), float(index_rows[0]["close"])
        if stock_prev == 0 or index_prev == 0:
            return {"triggered": False, "coverage": "invalid:prev_close_zero"}
        excess_pp = ((stock_now / stock_prev - 1.0) - (index_now / index_prev - 1.0)) * 100.0
        threshold = float(params.get("threshold_pp") or 0)
        direction = str(params.get("direction") or "up")
        triggered = excess_pp <= -abs(threshold) if direction == "down" else excess_pp >= abs(threshold)
        return {"triggered": triggered, "coverage": "ok", "excess_pp": excess_pp, "threshold_pp": threshold}
    if kind == "fund_flow_streak":
        days = int(params.get("days") or 3)
        rows = _latest_rows_by_date(cache["fund_flows"].get(symbol, []), as_of, exact_latest=True)[-days:]
        if len(rows) < days:
            return {"triggered": False, "coverage": "missing:flow_streak"}
        values = [float(row["main_net"]) for row in reversed(rows)]
        direction = str(params.get("direction") or "up")
        triggered = all(value < 0 for value in values) if direction == "down" else all(value > 0 for value in values)
        return {"triggered": triggered, "coverage": "ok", "values": values, "days": days}
    if kind == "fund_flow_ma_break":
        days = int(params.get("days") or 3)
        flow_rows = _latest_rows_by_date(cache["fund_flows"].get(symbol, []), as_of, exact_latest=True)[-days:]
        if len(flow_rows) < days:
            return {"triggered": False, "coverage": "missing:flow_streak"}
        flow_values = [float(row["main_net"]) for row in reversed(flow_rows)]
        flow_hit = all(value < 0 for value in flow_values)
        ma_window = int(params.get("ma_window") or 20)
        price_rows = _latest_rows_by_date(cache["prices"].get(symbol, []), as_of, exact_latest=True)[-ma_window:]
        if len(price_rows) < ma_window:
            return {"triggered": False, "coverage": "missing:ma_window"}
        latest_close = float(price_rows[-1]["close"])
        ma_value = sum(float(row["close"]) for row in price_rows) / ma_window
        return {
            "triggered": flow_hit and latest_close < ma_value,
            "coverage": "ok",
            "flow_values": flow_values,
            "latest_close": latest_close,
            "ma_window": ma_window,
            "ma_value": ma_value,
        }
    if kind == "event_keyword":
        tables = [str(table) for table in params.get("tables") or []]
        keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
        if not keywords:
            return {"triggered": False, "coverage": "missing:keywords"}
        lookback_days = int(params.get("lookback_days") or 5)
        start = _window_start(as_of, lookback_days)
        matches: list[dict[str, Any]] = []
        missing: list[str] = []
        for table in tables:
            table_rows = cache["events"].get(table)
            if table_rows is None:
                missing.append(table)
                continue
            for row in table_rows.get(symbol, []):
                item_day = str(row.get("_day") or "")
                if not (start <= item_day <= as_of):
                    continue
                title = str(row.get("title") or "")
                hit = [keyword for keyword in keywords if keyword in title]
                if hit:
                    matches.append({"table": table, "date": item_day, "title": title, "keywords": hit})
        return {"triggered": bool(matches), "coverage": "ok" if matches or len(missing) < len(tables) else "missing:event_tables", "matches": matches, "missing_tables": missing}
    if kind == "overseas_indicator_keyword":
        keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
        if not keywords:
            return {"triggered": False, "coverage": "missing:keywords"}
        lookback_days = int(params.get("lookback_days") or 10)
        start = _window_start(as_of, lookback_days)
        matches = []
        for row in cache["overseas_snapshots"]:
            item_day = str(row.get("_day") or "")
            if not (start <= item_day <= as_of):
                continue
            haystack = f"{row.get('symbol') or ''} {row.get('name') or ''} {row.get('note') or ''}"
            hit = [keyword for keyword in keywords if keyword in haystack]
            if hit:
                matches.append({"symbol": row.get("symbol"), "name": row.get("name"), "date": item_day, "keywords": hit})
        return {"triggered": bool(matches), "coverage": "ok", "matches": matches}
    if kind == "overseas_pct_move":
        field = str(params.get("field") or "chg_pct_1d")
        rows = _latest_rows_by_date(cache["overseas_by_symbol"].get(symbol, []), as_of, exact_latest=True)
        if not rows or field not in rows[-1] or rows[-1].get(field) is None:
            return {"triggered": False, "coverage": "missing:as_of_overseas"}
        value = float(rows[-1][field])
        threshold = float(params.get("threshold_pct") or 0)
        direction = str(params.get("direction") or "up")
        return {"triggered": _threshold_hit(value, threshold, direction), "coverage": "ok", "value": value, "threshold_pct": threshold}
    if kind == "financial_metric_threshold":
        thresholds = [item for item in params.get("thresholds") or [] if isinstance(item, dict)]
        rows = [row for row in cache["financial_metrics"].get(symbol, []) if str(row.get("_day") or "") <= as_of]
        if not rows:
            return {"triggered": False, "coverage": "missing:financial_row"}
        row = rows[-1]
        checks = []
        for item in thresholds:
            field = str(item.get("field"))
            if row.get(field) is None:
                continue
            value = float(row[field])
            threshold = float(item.get("threshold_pct") or 0)
            operator = str(item.get("operator") or "gte")
            checks.append({"field": field, "value": value, "operator": operator, "threshold_pct": threshold, "hit": _compare(value, operator, threshold)})
        if not checks:
            return {"triggered": False, "coverage": "missing:financial_values"}
        join = str(params.get("join") or "all")
        triggered = any(check["hit"] for check in checks) if join == "any" else all(check["hit"] for check in checks)
        return {"triggered": triggered, "coverage": "ok", "checks": checks, "join": join}
    if kind == "long_term_label_state":
        labels = [str(label) for label in params.get("labels") or [] if str(label)]
        if not labels:
            return {"triggered": False, "coverage": "missing:labels"}
        rows = [row for row in cache["long_term_labels"].get(symbol, []) if str(row.get("_day") or "") <= as_of]
        if not rows:
            return {"triggered": False, "coverage": "missing:long_term_label_row"}
        row = rows[-1]
        haystack = f"{row.get('label') or ''} {row.get('key_findings_json') or ''}"
        hits = [label for label in labels if label in haystack]
        return {"triggered": bool(hits), "coverage": "ok", "date": str(row.get("_day")), "hits": hits}
    return {"triggered": False, "coverage": "manual_review"}


def _max_spec_lookback(specs: Sequence[dict[str, Any]]) -> int:
    lookback = 1
    for item in specs:
        params = (item.get("spec") or {}).get("params") or {}
        for key in ("lookback_days", "window_days", "ma_window", "days"):
            try:
                lookback = max(lookback, int(params.get(key) or 0))
            except (TypeError, ValueError):
                continue
    return lookback + 5


def _build_history_cache(
    con: sqlite3.Connection,
    *,
    symbols: Sequence[str],
    start: str,
    end: str,
    specs: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    buffered_start = _window_start(start, _max_spec_lookback(specs))
    symbol_list = sorted({str(symbol) for symbol in symbols if symbol})
    price_rows = _fetch_rows(
        con,
        "prices",
        ("symbol", "date", "close"),
        date_col="date",
        start=buffered_start,
        end=end,
        symbols=symbol_list,
    )
    index_rows = _fetch_rows(
        con,
        "index_prices",
        ("symbol", "date", "close"),
        date_col="date",
        start=buffered_start,
        end=end,
    )
    fund_rows = _fetch_rows(
        con,
        "fund_flows",
        ("symbol", "trade_date", "main_net"),
        date_col="trade_date",
        start=buffered_start,
        end=end,
        symbols=symbol_list,
    )
    financial_rows = _fetch_rows(
        con,
        "financial_metrics",
        tuple(
            col
            for col in _columns(con, "financial_metrics")
            if col in {"symbol", "report_date", "disclosure_date", "revenue_yoy", "net_profit_yoy", "gross_margin"}
        ),
        date_col="report_date",
        start="1900-01-01",
        end=end,
        symbols=symbol_list,
    )
    for row in financial_rows:
        row["_day"] = _day(row.get("disclosure_date") or row.get("report_date"))
    label_date_col = "date" if "date" in _columns(con, "long_term_labels") else "as_of"
    label_rows = _fetch_rows(
        con,
        "long_term_labels",
        tuple(col for col in ("symbol", label_date_col, "label", "key_findings_json") if col in _columns(con, "long_term_labels")),
        date_col=label_date_col,
        start="1900-01-01",
        end=end,
        symbols=symbol_list,
    )
    for row in label_rows:
        row["_day"] = _day(row.get(label_date_col))
    events: dict[str, dict[str, list[dict[str, Any]]] | None] = {}
    event_meta = {
        "announcements": ("published_at", "title"),
        "research_reports": ("publish_date", "title"),
        "corporate_events": ("event_date", "title"),
        "news": ("published_at", "title"),
    }
    for table, (date_col, title_col) in event_meta.items():
        rows = _fetch_rows(
            con,
            table,
            ("symbol", date_col, title_col),
            date_col=date_col,
            start=buffered_start,
            end=end,
            symbols=symbol_list,
        )
        normalized = []
        for row in rows:
            normalized.append({"symbol": row.get("symbol"), "title": row.get(title_col), "_day": _day(row.get(date_col))})
        events[table] = _rows_by_symbol(normalized, "_day") if rows or _table_exists(con, table) else None
    overseas_cols = [col for col in ("symbol", "name", "snap_date", "note", "chg_pct_1d") if col in _columns(con, "overseas_snapshots")]
    overseas_rows = _fetch_rows(
        con,
        "overseas_snapshots",
        tuple(overseas_cols),
        date_col="snap_date",
        start=buffered_start,
        end=end,
    )
    for row in overseas_rows:
        row["_day"] = _day(row.get("snap_date"))
    return {
        "prices": _rows_by_symbol(price_rows, "date"),
        "index_prices": _rows_by_symbol(index_rows, "date"),
        "fund_flows": _rows_by_symbol(fund_rows, "trade_date"),
        "financial_metrics": _rows_by_symbol(financial_rows, "_day"),
        "long_term_labels": _rows_by_symbol(label_rows, "_day"),
        "events": events,
        "overseas_snapshots": overseas_rows,
        "overseas_by_symbol": _rows_by_symbol(overseas_rows, "_day"),
    }


def historical_condition_backscan(
    con: sqlite3.Connection,
    *,
    symbols_by_theme: dict[str, Sequence[str]],
    start: str,
    end: str,
    condition_type: str = "validation",
) -> dict[str, Any]:
    """Replay compiled thesis specs over historical trading days with PIT inputs only.

    The thesis text and theme membership are assumed to be known for the replay.
    Each condition evaluation only sees rows dated on or before ``as_of``.
    """
    specs, stats = _load_historical_specs(con, condition_type=condition_type)
    symbols = sorted({str(symbol) for values in symbols_by_theme.values() for symbol in values if symbol})
    cache = _build_history_cache(con, symbols=symbols, start=start, end=end, specs=specs)
    hits: list[dict[str, Any]] = []
    evaluated = 0
    for item in specs:
        theme_key = str(item["theme_key"])
        theme_symbols = [str(symbol) for symbol in symbols_by_theme.get(theme_key, []) if symbol]
        if not theme_symbols:
            continue
        spec = item["spec"]
        for symbol in theme_symbols:
            trading_days = [
                str(row.get("_day") or "")
                for row in cache["prices"].get(symbol, [])
                if start <= str(row.get("_day") or "") <= end
            ]
            for as_of in trading_days:
                evaluated += 1
                evaluation = _eval_cached_condition(cache, symbol=symbol, as_of=as_of, spec=spec)
                if not evaluation.get("triggered"):
                    continue
                hits.append(
                    {
                        "symbol": symbol,
                        "as_of": as_of,
                        "trigger_type": f"thesis_{condition_type}_backscan",
                        "theme_key": theme_key,
                        "forward_thesis_id": item["forward_thesis_id"],
                        "condition_type": condition_type,
                        "spec": spec,
                        "evaluation": evaluation,
                    }
                )
    dedup: dict[tuple[str, str, str, int, str], dict[str, Any]] = {}
    for hit in hits:
        dedup[(hit["symbol"], hit["as_of"], hit["theme_key"], int(hit["forward_thesis_id"]), json.dumps(hit["spec"], sort_keys=True, ensure_ascii=False))] = hit
    return {
        "schema_version": "m60_thesis_conditions.history_backscan.v1",
        "condition_type": condition_type,
        "start": start,
        "end": end,
        "stats": {**stats, "evaluated_points": evaluated, "hit_count": len(dedup)},
        "hits": sorted(dedup.values(), key=lambda row: (row["as_of"], row["theme_key"], row["symbol"], row["forward_thesis_id"])),
    }


def _threshold_hit(value: float, threshold: float, direction: str) -> bool:
    return value <= -abs(threshold) if direction == "down" else value >= abs(threshold)


def _eval_price_pct_move(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return {"triggered": False, "coverage": "missing:prices"}
    rows = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date(date) <= date(?) AND close IS NOT NULL
        ORDER BY date(date) DESC
        LIMIT 2
        """,
        (symbol, as_of),
    ).fetchall()
    if len(rows) < 2 or str(rows[0]["date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:as_of_price"}
    cur = float(rows[0]["close"])
    prev = float(rows[1]["close"])
    if prev == 0:
        return {"triggered": False, "coverage": "invalid:prev_close_zero"}
    pct = (cur / prev - 1.0) * 100.0
    threshold = float(params.get("threshold_pct") or 0)
    direction = str(params.get("direction") or "up")
    return {"triggered": _threshold_hit(pct, threshold, direction), "coverage": "ok", "value": pct, "threshold_pct": threshold}


def _eval_fund_flow_streak(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "fund_flows") or not {"symbol", "trade_date", "main_net"} <= _columns(con, "fund_flows"):
        return {"triggered": False, "coverage": "missing:fund_flows"}
    days = int(params.get("days") or 3)
    rows = con.execute(
        """
        SELECT trade_date, main_net
        FROM fund_flows
        WHERE symbol = ? AND date(trade_date) <= date(?) AND main_net IS NOT NULL
        ORDER BY date(trade_date) DESC
        LIMIT ?
        """,
        (symbol, as_of, days),
    ).fetchall()
    if len(rows) < days or str(rows[0]["trade_date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:flow_streak"}
    values = [float(row["main_net"]) for row in rows]
    direction = str(params.get("direction") or "up")
    triggered = all(value < 0 for value in values) if direction == "down" else all(value > 0 for value in values)
    return {"triggered": triggered, "coverage": "ok", "values": values, "days": days}


def _eval_event_keyword(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    tables = [str(table) for table in params.get("tables") or []]
    keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
    if not keywords:
        return {"triggered": False, "coverage": "missing:keywords"}
    table_meta = {
        "announcements": ("published_at", "title"),
        "research_reports": ("publish_date", "title"),
        "corporate_events": ("event_date", "title"),
        "news": ("published_at", "title"),
    }
    lookback_days = int(params.get("lookback_days") or 5)
    matches: list[dict[str, Any]] = []
    missing: list[str] = []
    for table in tables:
        date_col, title_col = table_meta.get(table, ("", ""))
        if not date_col or not _table_exists(con, table) or not {"symbol", date_col, title_col} <= _columns(con, table):
            missing.append(table)
            continue
        rows = con.execute(
            f"""
            SELECT symbol, {date_col} AS item_date, {title_col} AS title
            FROM {table}
            WHERE symbol = ?
              AND date({date_col}) <= date(?)
              AND date({date_col}) >= date(?, ?)
            ORDER BY date({date_col}) DESC
            LIMIT 50
            """,
            (symbol, as_of, as_of, f"-{lookback_days} day"),
        ).fetchall()
        for row in rows:
            title = str(row["title"] or "")
            hit = [keyword for keyword in keywords if keyword in title]
            if hit:
                matches.append({"table": table, "date": str(row["item_date"])[:10], "title": title, "keywords": hit})
    return {"triggered": bool(matches), "coverage": "ok" if matches or len(missing) < len(tables) else "missing:event_tables", "matches": matches, "missing_tables": missing}


def _eval_overseas_indicator_keyword(con: sqlite3.Connection, *, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "overseas_snapshots") or not {"snap_date", "name", "note"} <= _columns(con, "overseas_snapshots"):
        return {"triggered": False, "coverage": "missing:overseas_snapshots"}
    keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
    if not keywords:
        return {"triggered": False, "coverage": "missing:keywords"}
    lookback_days = int(params.get("lookback_days") or 10)
    rows = con.execute(
        """
        SELECT symbol, name, snap_date, note
        FROM overseas_snapshots
        WHERE date(snap_date) <= date(?)
          AND date(snap_date) >= date(?, ?)
        ORDER BY date(snap_date) DESC
        LIMIT 100
        """,
        (as_of, as_of, f"-{lookback_days} day"),
    ).fetchall()
    matches = []
    for row in rows:
        haystack = f"{row['symbol'] or ''} {row['name'] or ''} {row['note'] or ''}"
        hit = [keyword for keyword in keywords if keyword in haystack]
        if hit:
            matches.append({"symbol": row["symbol"], "name": row["name"], "date": str(row["snap_date"])[:10], "keywords": hit})
    return {"triggered": bool(matches), "coverage": "ok", "matches": matches}


def _compare(value: float, operator: str, threshold: float) -> bool:
    return value <= threshold if operator == "lte" else value >= threshold


def _eval_financial_metric_threshold(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    required = {"symbol", "disclosure_date", "report_date"}
    if not _table_exists(con, "financial_metrics") or not required <= _columns(con, "financial_metrics"):
        return {"triggered": False, "coverage": "missing:financial_metrics"}
    thresholds = [item for item in params.get("thresholds") or [] if isinstance(item, dict)]
    fields = [str(item.get("field")) for item in thresholds if item.get("field")]
    if not fields or not set(fields) <= _columns(con, "financial_metrics"):
        return {"triggered": False, "coverage": "missing:financial_fields"}
    rows = con.execute(
        f"""
        SELECT report_date, disclosure_date, {", ".join(fields)}
        FROM financial_metrics
        WHERE symbol = ? AND date(COALESCE(disclosure_date, report_date)) <= date(?)
        ORDER BY date(COALESCE(disclosure_date, report_date)) DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchall()
    if not rows:
        return {"triggered": False, "coverage": "missing:financial_row"}
    row = rows[0]
    checks = []
    for item in thresholds:
        field = str(item.get("field"))
        if row[field] is None:
            continue
        value = float(row[field])
        threshold = float(item.get("threshold_pct") or 0)
        operator = str(item.get("operator") or "gte")
        checks.append({"field": field, "value": value, "operator": operator, "threshold_pct": threshold, "hit": _compare(value, operator, threshold)})
    if not checks:
        return {"triggered": False, "coverage": "missing:financial_values"}
    join = str(params.get("join") or "all")
    triggered = any(check["hit"] for check in checks) if join == "any" else all(check["hit"] for check in checks)
    return {"triggered": triggered, "coverage": "ok", "checks": checks, "join": join}


def _eval_long_term_label_state(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    required = {"symbol", "date", "label", "key_findings_json"}
    if not _table_exists(con, "long_term_labels") or not required <= _columns(con, "long_term_labels"):
        return {"triggered": False, "coverage": "missing:long_term_labels"}
    labels = [str(label) for label in params.get("labels") or [] if str(label)]
    if not labels:
        return {"triggered": False, "coverage": "missing:labels"}
    row = con.execute(
        """
        SELECT date, label, key_findings_json
        FROM long_term_labels
        WHERE symbol = ? AND date(date) <= date(?)
        ORDER BY date(date) DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    if row is None:
        return {"triggered": False, "coverage": "missing:long_term_label_row"}
    haystack = f"{row['label'] or ''} {row['key_findings_json'] or ''}"
    hits = [label for label in labels if label in haystack]
    return {"triggered": bool(hits), "coverage": "ok", "date": str(row["date"])[:10], "hits": hits}


def _latest_close(con: sqlite3.Connection, table: str, symbol: str, as_of: str, window_days: int) -> tuple[float, float] | None:
    date_col = "date"
    rows = con.execute(
        f"""
        SELECT {date_col}, close
        FROM {table}
        WHERE symbol = ? AND date({date_col}) <= date(?) AND close IS NOT NULL
        ORDER BY date({date_col}) DESC
        LIMIT ?
        """,
        (symbol, as_of, max(window_days + 1, 2)),
    ).fetchall()
    if len(rows) < 2 or str(rows[0][date_col])[:10] != as_of:
        return None
    return float(rows[0]["close"]), float(rows[-1]["close"])


def _eval_relative_benchmark_move(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return {"triggered": False, "coverage": "missing:prices"}
    if not _table_exists(con, "index_prices") or not {"symbol", "date", "close"} <= _columns(con, "index_prices"):
        return {"triggered": False, "coverage": "missing:index_prices"}
    window_days = int(params.get("window_days") or 1)
    benchmark = str(params.get("benchmark_symbol") or "000300")
    stock_pair = _latest_close(con, "prices", symbol, as_of, window_days)
    index_pair = _latest_close(con, "index_prices", benchmark, as_of, window_days)
    if stock_pair is None or index_pair is None:
        return {"triggered": False, "coverage": "missing:relative_prices"}
    stock_now, stock_prev = stock_pair
    index_now, index_prev = index_pair
    if stock_prev == 0 or index_prev == 0:
        return {"triggered": False, "coverage": "invalid:prev_close_zero"}
    stock_pct = (stock_now / stock_prev - 1.0) * 100.0
    index_pct = (index_now / index_prev - 1.0) * 100.0
    excess_pp = stock_pct - index_pct
    threshold = float(params.get("threshold_pp") or 0)
    direction = str(params.get("direction") or "up")
    triggered = excess_pp <= -abs(threshold) if direction == "down" else excess_pp >= abs(threshold)
    return {"triggered": triggered, "coverage": "ok", "excess_pp": excess_pp, "threshold_pp": threshold}


def _eval_research_report_density(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "research_reports") or not {"symbol", "publish_date", "title"} <= _columns(con, "research_reports"):
        return {"triggered": False, "coverage": "missing:research_reports"}
    keywords = [str(keyword) for keyword in params.get("keywords") or [] if str(keyword)]
    lookback_days = int(params.get("lookback_days") or 30)
    min_count = int(params.get("min_count") or 2)
    rows = con.execute(
        """
        SELECT publish_date, title
        FROM research_reports
        WHERE symbol = ?
          AND date(publish_date) <= date(?)
          AND date(publish_date) >= date(?, ?)
        ORDER BY date(publish_date) DESC
        LIMIT 100
        """,
        (symbol, as_of, as_of, f"-{lookback_days} day"),
    ).fetchall()
    matches = []
    for row in rows:
        title = str(row["title"] or "")
        if not keywords or any(keyword in title for keyword in keywords):
            matches.append({"date": str(row["publish_date"])[:10], "title": title})
    return {"triggered": len(matches) >= min_count, "coverage": "ok", "count": len(matches), "min_count": min_count, "matches": matches}


def _eval_fund_flow_ma_break(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "fund_flows") or not {"symbol", "trade_date", "main_net"} <= _columns(con, "fund_flows"):
        return {"triggered": False, "coverage": "missing:fund_flows"}
    if not _table_exists(con, "prices") or not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return {"triggered": False, "coverage": "missing:prices"}
    days = int(params.get("days") or 3)
    flow_rows = con.execute(
        """
        SELECT trade_date, main_net
        FROM fund_flows
        WHERE symbol = ? AND date(trade_date) <= date(?) AND main_net IS NOT NULL
        ORDER BY date(trade_date) DESC
        LIMIT ?
        """,
        (symbol, as_of, days),
    ).fetchall()
    if len(flow_rows) < days or str(flow_rows[0]["trade_date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:flow_streak"}
    flow_values = [float(row["main_net"]) for row in flow_rows]
    flow_hit = all(value < 0 for value in flow_values)
    ma_window = int(params.get("ma_window") or 20)
    price_rows = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date(date) <= date(?) AND close IS NOT NULL
        ORDER BY date(date) DESC
        LIMIT ?
        """,
        (symbol, as_of, ma_window),
    ).fetchall()
    if len(price_rows) < ma_window or str(price_rows[0]["date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:ma_window"}
    latest_close = float(price_rows[0]["close"])
    ma_value = sum(float(row["close"]) for row in price_rows) / ma_window
    ma_hit = latest_close < ma_value
    return {
        "triggered": flow_hit and ma_hit,
        "coverage": "ok",
        "flow_values": flow_values,
        "latest_close": latest_close,
        "ma_window": ma_window,
        "ma_value": ma_value,
    }


def _eval_overseas_pct_move(con: sqlite3.Connection, *, symbol: str, as_of: str, params: dict[str, Any]) -> dict[str, Any]:
    if not _table_exists(con, "overseas_snapshots"):
        return {"triggered": False, "coverage": "missing:overseas_snapshots"}
    field = str(params.get("field") or "chg_pct_1d")
    if not {"symbol", "snap_date", field} <= _columns(con, "overseas_snapshots"):
        return {"triggered": False, "coverage": "missing:overseas_columns"}
    rows = con.execute(
        f"""
        SELECT snap_date, {field} AS chg
        FROM overseas_snapshots
        WHERE symbol = ? AND date(snap_date) <= date(?) AND {field} IS NOT NULL
        ORDER BY date(snap_date) DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchall()
    if not rows or str(rows[0]["snap_date"])[:10] != as_of:
        return {"triggered": False, "coverage": "missing:as_of_overseas"}
    value = float(rows[0]["chg"])
    threshold = float(params.get("threshold_pct") or 0)
    direction = str(params.get("direction") or "up")
    return {"triggered": _threshold_hit(value, threshold, direction), "coverage": "ok", "value": value, "threshold_pct": threshold}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compile ForwardThesis condition prose into M60 monitor specs.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite DB path; defaults to configured MingCang DB")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    args = parser.parse_args(argv)
    summary = compile_forward_thesis_conditions(db_path=args.db)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"thesis conditions: {summary['compiled_conditions']}/{summary['total_conditions']} "
            f"compiled ({summary['coverage_pct']}%), manual_review={summary['manual_review_conditions']}"
        )


if __name__ == "__main__":
    main()
