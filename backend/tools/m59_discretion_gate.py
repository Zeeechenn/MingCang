"""Build M59 discretion judgment-gate cases without running judges.

``build`` creates a blind-adjudication compatible gate JSON where:
- arms.starved is the zero-LLM hard-rule baseline.
- arms.full is an empty placeholder for the M59 discretion card.

``generate`` fills arms.full by calling the M59 discretion-card path. Do not run
it from automation unless an LLM-backed provider is intentionally available.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import default_sqlite_path
from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.data.database import SessionLocal
from backend.tools import m59_discretion

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "paper_trading" / "m61_out"
DEFAULT_SOURCE_FILES = (
    DEFAULT_OUT_DIR / "judgment_gate_adjudication_20260704.json",
    DEFAULT_OUT_DIR / "adjudication_h1_expansion_20260705.json",
)
CASE_METADATA_FILES = (
    DEFAULT_OUT_DIR / "judgment_gate_20260704_2217.json",
    DEFAULT_OUT_DIR / "judgment_gate_20260704_2334.json",
    DEFAULT_OUT_DIR / "judgment_gate_20260705_0028.json",
)
CONTEXT_SECTIONS = m59_discretion.CONTEXT_SECTIONS


def _date_token() -> str:
    return datetime.now().strftime("%Y%m%d")


def _case_slug(value: str) -> str:
    base = value.split("(", 1)[0]
    head, sep, tail = base.rpartition("_")
    return head if sep and tail.isdigit() else base


def _load_source_case_ids(paths: tuple[Path, ...] = DEFAULT_SOURCE_FILES) -> list[str]:
    ids: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw_id in (payload.get("cases") or {}).keys():
            slug = _case_slug(str(raw_id))
            if slug not in ids:
                ids.append(slug)
    return ids


def _load_case_metadata(paths: tuple[Path, ...] = CASE_METADATA_FILES) -> dict[str, dict[str, Any]]:
    from backend.tools.m61_judgment_gate import CASES

    cases = {str(case["id"]): dict(case) for case in CASES}
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload.get("cases") or []:
            if isinstance(case, dict) and case.get("id"):
                cases[str(case["id"])] = {
                    key: str(case.get(key))
                    for key in ("id", "symbol", "name", "as_of", "question", "outcome_note")
                    if case.get(key) is not None
                }
    return cases


def selected_cases() -> list[dict[str, Any]]:
    metadata = _load_case_metadata()
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for case_id in _load_source_case_ids():
        case = metadata.get(case_id)
        if not case:
            raise ValueError(f"case metadata not found for source id: {case_id}")
        key = (str(case["symbol"]), str(case["as_of"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(case)
    return result


def _as_of_datetime(as_of: str) -> datetime:
    return datetime.fromisoformat(as_of + "T23:59:59")


def _pit_context(case: dict[str, Any], db) -> tuple[dict[str, Any], str]:
    as_of = _as_of_datetime(str(case["as_of"]))
    pack = build_stock_context_pack(
        str(case["symbol"]),
        as_of=as_of,
        sections=CONTEXT_SECTIONS,
        db=db,
    )
    # 与生产 _build_context 的 2400 字符裁剪对齐;governor 记忆块因 build_agent_context
    # 无 as-of 过滤能力被排除在历史回放外(防记忆泄漏),生产实跑会多一块记忆上下文。
    return pack, render_context_text(pack, max_chars=2400)


def _connect_readonly(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    uri = f"file:{resolved.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _latest_signal(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not {"symbol", "date"} <= _columns(con, "signals"):
        return None
    cols = _columns(con, "signals")
    wanted = [
        col
        for col in ("date", "recommendation", "composite_score", "stop_loss", "take_profit", "rule_version")
        if col in cols
    ]
    row = con.execute(
        f"""
        SELECT {', '.join(wanted)}
        FROM signals
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return dict(row) if row else None


def _open_position(con: sqlite3.Connection, symbol: str) -> dict[str, Any] | None:
    cols = _columns(con, "positions")
    if "symbol" not in cols:
        return None
    wanted = [col for col in ("name", "quantity", "avg_cost", "stop_loss", "take_profit", "status") if col in cols]
    status_clause = "AND COALESCE(status, 'open') = 'open'" if "status" in cols else ""
    order_clause = "ORDER BY id DESC" if "id" in cols else ""
    row = con.execute(
        f"""
        SELECT {', '.join(wanted) if wanted else 'symbol'}
        FROM positions
        WHERE symbol = ? {status_clause}
        {order_clause}
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    return dict(row) if row else None


def _latest_price(con: sqlite3.Connection, symbol: str, as_of: str) -> dict[str, Any] | None:
    if not {"symbol", "date", "close"} <= _columns(con, "prices"):
        return None
    row = con.execute(
        """
        SELECT date, close
        FROM prices
        WHERE symbol = ? AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return dict(row) if row else None


def _hard_rule_snapshot(symbol: str, as_of: str, db_path: str | Path | None) -> dict[str, Any]:
    try:
        with _connect_readonly(db_path) as con:
            return {
                "latest_signal": _latest_signal(con, symbol, as_of),
                "open_position": _open_position(con, symbol),
                "latest_price": _latest_price(con, symbol, as_of),
            }
    except sqlite3.Error as exc:
        return {"degraded": f"{type(exc).__name__}: {exc}"}


def _render_hard_rule_response(case: dict[str, Any], snapshot: dict[str, Any]) -> str:
    signal = snapshot.get("latest_signal") or {}
    position = snapshot.get("open_position") or {}
    price = snapshot.get("latest_price") or {}
    lines = [
        "M59四硬规则零LLM基线(确定性渲染,不含裁量):",
        f"- as_of: {case['as_of']} symbol: {case['symbol']}",
        f"- R1 信号: {signal.get('recommendation', '无')} score={signal.get('composite_score', 'NA')} rule_version={signal.get('rule_version', 'unknown')}",
        f"- R2 风控价: stop_loss={signal.get('stop_loss', position.get('stop_loss', 'NA'))} take_profit={signal.get('take_profit', position.get('take_profit', 'NA'))}",
        f"- R3 持仓: quantity={position.get('quantity', 0)} avg_cost={position.get('avg_cost', 'NA')} status={position.get('status', 'none')}",
        f"- R4 当前PIT价格: {price.get('date', 'NA')} close={price.get('close', 'NA')}",
        "结论: 仅按上述硬规则执行;未调用LLM,未加入反方审视或主观裁量。",
    ]
    if snapshot.get("degraded"):
        lines.append(f"- 降级: {snapshot['degraded']}")
    return "\n".join(lines)


def _arm_payload(
    *,
    label: str,
    context: str,
    response: str,
    status: str,
    raw_result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "context": context,
        "response": response,
        "status": status,
        "raw_result": raw_result,
        "error": error,
    }


def build_gate_cases(
    *,
    db=None,
    db_path: str | Path | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    date_token: str | None = None,
) -> dict[str, Any]:
    own_session = db is None
    session = db or SessionLocal()
    token = date_token or _date_token()
    report: dict[str, Any] = {
        "meta": {
            "schema_version": "m59_discretion_gate.v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_files": [str(path.relative_to(REPO_ROOT)) for path in DEFAULT_SOURCE_FILES],
            "arms_semantics": {
                "starved": "无裁量硬规则基线",
                "full": "裁量增强臂",
            },
            "llm_policy": "build is zero-LLM; generate fills arms.full and may call runtime LLM provider",
            "context_parity": (
                "arm-B 上下文=生产 build_stock_context_pack + 2400 字符裁剪;"
                "governor 记忆块因 build_agent_context 无 as-of 过滤被排除(防历史回放记忆泄漏),"
                "生产实跑会多一块记忆上下文"
            ),
        },
        "cases": [],
    }
    try:
        for case in selected_cases():
            _, context_text = _pit_context(case, session)
            snapshot = _hard_rule_snapshot(str(case["symbol"]), str(case["as_of"]), db_path)
            case_result = {
                **case,
                "status": "ok",
                "arms": {
                    "starved": _arm_payload(
                        label="ARM A starved(无裁量硬规则基线)",
                        context=context_text,
                        response=_render_hard_rule_response(case, snapshot),
                        status="ok",
                        raw_result=snapshot,
                    ),
                    "full": _arm_payload(
                        label="ARM B full(M59裁量增强臂,待generate填充)",
                        context=context_text,
                        response="",
                        status="pending_generate",
                    ),
                },
            }
            report["cases"].append(case_result)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"m59_discretion_gate_cases_{token}.json"
        report["json_path"] = str(json_path)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return report
    finally:
        if own_session:
            session.close()


def _case_slot(case: dict[str, Any]) -> str:
    question = str(case.get("question") or "")
    if any(token in question for token in ("尚未持仓", "观察名单", "是否入场", "是否追高", "纳入观察", "建仓候选")):
        return "candidate_selection"
    return "holding_decision"


def _single_discretion_prompt(case: dict[str, Any], context_pack: dict[str, Any], context_text: str) -> str:
    slot = _case_slot(case)
    item = {
        "symbol": case["symbol"],
        "question": case.get("question"),
        "as_of": case["as_of"],
        "gate_case_id": case.get("id"),
    }
    return m59_discretion.PROMPT_TEMPLATE.format(
        slot=slot,
        allowed_stance=" / ".join(m59_discretion._allowed_stances(slot)),
        panel_item_json=m59_discretion._json_dumps(item),
        context_pack_json=m59_discretion._json_dumps(context_pack),
        context_text=context_text,
    )


SCHEMA_REMINDER = "\n\n注意: rationale 不得超过120字, timing_note 不得超过60字, 超限即无效, 请压缩表述。"


def generate_single_case(
    case: dict[str, Any],
    *,
    db,
    provider: Any | None = None,
    schema_reminder: bool = False,
) -> dict[str, Any]:
    context_pack, context_text = _pit_context(case, db)
    provider = provider or m59_discretion.get_provider()
    prompt = _single_discretion_prompt(case, context_pack, context_text)
    if schema_reminder:
        prompt += SCHEMA_REMINDER
    data = provider.complete_structured(
        prompt=prompt,
        tool=m59_discretion.DISCRETION_TOOL,
        system=m59_discretion.SYSTEM_PROMPT,
        max_tokens=450,
        model_tier="capable",
    )
    slot = _case_slot(case)
    card = m59_discretion._validate_card(data, slot=slot, soft_length=True)
    objection_data = provider.complete_structured(
        prompt=m59_discretion._objection_prompt(
            [{**card, "symbol": case["symbol"], "slot": slot, "as_of": case["as_of"]}]
        ),
        tool=m59_discretion.OBJECTION_TOOL,
        system=m59_discretion.OBJECTION_SYSTEM_PROMPT,
        max_tokens=900,
        model_tier="capable",
    )
    objections = m59_discretion._validate_objections(
        objection_data, {str(case["symbol"])}, soft_length=True
    )
    cards = [{**card, "symbol": case["symbol"], "slot": slot}]
    m59_discretion._apply_objections(cards, objections)
    rendered = m59_discretion.render_card_lines({"cards": cards, "degradations": []})
    return {
        "context": context_text,
        "response": "\n".join(rendered),
        "raw_result": {"card": cards[0], "objections": objections},
    }


def generate_cases(
    cases_path: Path,
    *,
    db=None,
    provider_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    own_session = db is None
    session = db or SessionLocal()
    provider = provider_factory() if provider_factory else None
    report = json.loads(cases_path.read_text(encoding="utf-8"))
    try:
        for case in report.get("cases") or []:
            if case["arms"]["full"].get("status") == "ok":
                continue
            generated = None
            error: str | None = None
            # 生产同款纪律: 单案例失败降级不阻断整批;schema 超限先带字数提醒重试一次。
            for attempt, reminder in enumerate((False, True)):
                try:
                    generated = generate_single_case(
                        case, db=session, provider=provider, schema_reminder=reminder
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - observe-only gate must not block the batch.
                    error = f"attempt{attempt + 1}: {exc}"
            if generated is not None:
                case["arms"]["full"].update(
                    {
                        "context": generated["context"],
                        "response": generated["response"],
                        "raw_result": generated["raw_result"],
                        "status": "ok",
                        "error": None,
                    }
                )
            else:
                case["arms"]["full"].update({"status": "failed", "error": error})
            # 每案例即写盘: 两次 LLM 调用的进度不能因后续崩溃丢失,重跑按 status 幂等续跑。
            cases_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        return report
    finally:
        if own_session:
            session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/fill M59 discretion judgment-gate cases.")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--db-path", type=Path, default=None)
    build.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    build.add_argument("--date-token", default=None)

    generate = sub.add_parser("generate")
    generate.add_argument("--cases", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "build":
        report = build_gate_cases(db_path=args.db_path, out_dir=args.out_dir, date_token=args.date_token)
        print(json.dumps({"json": report["json_path"], "cases": len(report["cases"])}, ensure_ascii=False))
        return 0
    if args.command == "generate":
        report = generate_cases(args.cases)
        print(json.dumps({"json": str(args.cases), "cases": len(report.get("cases") or [])}, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
