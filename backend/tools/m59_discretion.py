"""M59 observe-only LLM discretion cards."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import default_sqlite_path, settings
from backend.data.context_builder import build_stock_context_pack, render_context_text
from backend.llm import get_provider, has_runtime_llm_provider, runtime_readiness

MAX_CANDIDATES = 4
MAX_HOLDINGS = 3
MAX_LLM_CALLS = 8
MAX_INITIAL_CARDS = MAX_LLM_CALLS - 1
CONTEXT_SECTIONS = [
    "price",
    "financials",
    "news",
    "announcements",
    "research_reports",
    "corporate_events",
    "fund_flow",
    "long_term_label",
    "data_health",
]

CANDIDATE_STANCES = ("试错仓倾向", "观望", "跳过")
HOLDING_STANCES = ("持有倾向", "减仓倾向", "清仓倾向")
CONFIDENCE_VALUES = ("low", "med", "high")
STANCE_RENDER_LABELS = {
    "试错仓倾向": "小仓试错倾向",
    "观望": "继续观察",
    "跳过": "暂不纳入",
    "持有倾向": "维持观察倾向",
    "减仓倾向": "降仓倾向",
    "清仓倾向": "离场倾向",
}
INTERNAL_TRIGGER_WORDS = ("内部标签", "内部分数", "标签更新", "评分", "打分", "分数")

SYSTEM_PROMPT = (
    "你是 MingCang 的 M59 LLM 裁量层。输出仅供研究参考。"
    "你只做 observe-only 裁量解释,不得修改官方信号、止损、止盈或仓位。"
    "不得预测价格,不得下买卖指令。证据不足必须明确说证据不足。输出中文。"
)

PROMPT_TEMPLATE = """\
请基于输入包生成一张 M59 裁量参考卡。

纪律约束:
- LLM 只做裁量,不做打分。
- 输出仅供研究参考,不得给出买卖指令。
- 不预测价格,不承诺涨跌。
- 必须引用输入包中的具体证据字段;证据不足就说证据不足。
- reevaluation_trigger 必须是可观测外部条件,禁止锚定内部标签、内部分数或模型打分。
- 输出字数硬上限:timing_note≤60字,rationale≤120字,objection≤80字;超限即为无效输出,必须压缩到限内。
- 以 panel_item_json.as_of 为当前日期作答;禁止使用 as_of 之后的时间视角、日期换算或事实(历史回放时环境日期不可信)。

slot={slot}
allowed_stance={allowed_stance}
panel_item_json={panel_item_json}
context_pack_json={context_pack_json}
context_text={context_text}
"""

OBJECTION_SYSTEM_PROMPT = (
    "你是 MingCang 的 M59 反方研究员。输出仅供研究参考。"
    "你的任务是对每张裁量卡找最强反驳:证据里有什么被忽略的反面事实,"
    "rationale 有什么跳跃。不得预测价格,不得下买卖指令。输出中文。"
)

OBJECTION_PROMPT_TEMPLATE = """\
请批量审视以下 M59 初判卡,逐卡输出最强反方意见。

纪律约束:
- 反方只审视,不改判,不得改 stance。
- 输出仅供研究参考,不得给出买卖指令。
- 不预测价格,不承诺涨跌。
- 只基于输入摘要指出被忽略的反面事实或 rationale 跳跃。
- objection 80字内; low 可给轻微疑点,但渲染层不会展示 low。
- 若卡内含 as_of,以其为当前日期作审视;禁止使用 as_of 之后的时间视角、"距今"换算或事实(历史回放时环境日期不可信)。

cards_json={cards_json}
"""

DISCRETION_TOOL = {
    "name": "m59_discretion_card",
    "description": "M59 observe-only LLM discretion reference card",
    "input_schema": {
        "type": "object",
        "properties": {
            "stance": {"type": "string"},
            "timing_note": {"type": "string", "description": "60字内加减仓时机一句话,可空"},
            "rationale": {"type": "string", "description": "120字内,必须引用输入包内具体证据字段"},
            "confidence": {"type": "string", "enum": list(CONFIDENCE_VALUES)},
            "reevaluation_trigger": {
                "type": "string",
                "description": "可观测外部条件,禁止锚定内部标签或内部分数",
            },
        },
        "required": ["stance", "timing_note", "rationale", "confidence", "reevaluation_trigger"],
    },
}

OBJECTION_TOOL = {
    "name": "m59_discretion_objection_batch",
    "description": "Batch adversarial review for M59 observe-only discretion cards",
    "input_schema": {
        "type": "object",
        "properties": {
            "objections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "objection": {"type": "string", "description": "80字内最强反方意见"},
                        "severity": {"type": "string", "enum": ["low", "med", "high"]},
                        "confidence_adjustment": {"type": "string", "enum": ["none", "downgrade"]},
                    },
                    "required": ["symbol", "objection", "severity", "confidence_adjustment"],
                },
            }
        },
        "required": ["objections"],
    },
}


def _truthy_env(name: str) -> bool:
    return str(__import__("os").environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def m59_discretion_enabled() -> bool:
    # env 实时覆盖优先(运行时旗),否则读 Settings(配置三处同步:config/.env.example/runtime config)
    import os

    if os.environ.get("M59_DISCRETION_ENABLED") is not None:
        return _truthy_env("M59_DISCRETION_ENABLED")
    from backend.config import settings

    return bool(settings.m59_discretion_enabled)


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()[:16]


def _as_of(panel: dict[str, Any], as_of: str | None) -> str:
    if as_of:
        return as_of
    header = panel.get("header") if isinstance(panel, dict) else {}
    return str((header or {}).get("as_of") or datetime.now(UTC).date().isoformat())[:10]


def _flag_count(item: dict[str, Any]) -> int:
    total = 1 if item.get("protective_action") else 0
    for key in ("stop_flags", "quality_flags"):
        flags = item.get(key) or []
        total += len(flags) if isinstance(flags, list) else int(bool(flags))
    return total


def select_panel_items(panel: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        {"slot": "candidate_selection", "item": item}
        for item in (panel.get("buy_candidates", {}).get("items") or [])[:MAX_CANDIDATES]
        if isinstance(item, dict) and item.get("symbol")
    ]
    holdings = [
        item
        for item in (panel.get("position_health", {}).get("items") or [])
        if isinstance(item, dict) and item.get("symbol") and _flag_count(item) > 0
    ]
    holdings = sorted(holdings, key=lambda item: (-_flag_count(item), str(item.get("symbol"))))[:MAX_HOLDINGS]
    selected = [*candidates, *({"slot": "holding_decision", "item": item} for item in holdings)]
    return selected[:MAX_INITIAL_CARDS]


def _provider_name(provider: Any | None = None) -> str:
    if provider is not None:
        return getattr(provider, "name", None) or provider.__class__.__name__
    try:
        return str(runtime_readiness(settings).get("provider") or "unknown")
    except Exception:
        return "unknown"


def _allowed_stances(slot: str) -> tuple[str, ...]:
    return HOLDING_STANCES if slot == "holding_decision" else CANDIDATE_STANCES


_SENTENCE_BREAKS = "。;；!！?？,，"


def _soft_trim(value: str, limit: int) -> str:
    """句界优先截断到 limit 内(末尾省略号),供 soft_length 降级路径使用。"""
    if len(value) <= limit:
        return value
    head = value[: limit - 1]
    cut = max(head.rfind(ch) for ch in _SENTENCE_BREAKS)
    if cut >= limit // 2:
        head = head[: cut + 1]
    return head + "…"


def _validate_card(data: Any, *, slot: str, soft_length: bool = False) -> dict[str, str]:
    # "必须引用具体证据"与字数硬上限存在张力,LLM 高频超限;soft_length=True 时
    # 超长走句界截断+length_truncated 如实标注(降级不阻断),语义类失败仍硬拒。
    if not isinstance(data, dict):
        raise ValueError("schema invalid: not an object")
    allowed = _allowed_stances(slot)
    stance = str(data.get("stance") or "")
    if stance not in allowed:
        raise ValueError("schema invalid: stance")
    confidence = str(data.get("confidence") or "")
    if confidence not in CONFIDENCE_VALUES:
        raise ValueError("schema invalid: confidence")
    timing_note = str(data.get("timing_note") or "").strip()
    rationale = str(data.get("rationale") or "").strip()
    trigger = str(data.get("reevaluation_trigger") or "").strip()
    truncated = False
    if len(timing_note) > 60:
        if not soft_length:
            raise ValueError("schema invalid: timing_note too long")
        timing_note = _soft_trim(timing_note, 60)
        truncated = True
    if not rationale:
        raise ValueError("schema invalid: rationale")
    if len(rationale) > 120:
        if not soft_length:
            raise ValueError("schema invalid: rationale")
        rationale = _soft_trim(rationale, 120)
        truncated = True
    if not trigger:
        raise ValueError("schema invalid: reevaluation_trigger")
    if any(word in trigger for word in INTERNAL_TRIGGER_WORDS):
        raise ValueError("schema invalid: reevaluation_trigger internal anchor")
    card = {
        "stance": stance,
        "timing_note": timing_note,
        "rationale": rationale,
        "confidence": confidence,
        "reevaluation_trigger": trigger,
    }
    if truncated:
        card["length_truncated"] = "true"
    return card


def _sanitize_render_text(value: str) -> str:
    try:
        from backend.tools.m63_render import sanitize_trade_words

        sanitized, _ = sanitize_trade_words(value)
        return sanitized.strip()
    except Exception:  # noqa: BLE001 - rendering guard fallback must not block observe-only cards.
        return value.strip()


def _validate_objections(
    data: Any, symbols: set[str], *, soft_length: bool = False
) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict):
        raise ValueError("objection schema invalid: not an object")
    items = data.get("objections")
    if not isinstance(items, list):
        raise ValueError("objection schema invalid: objections")

    objections: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("objection schema invalid: item")
        symbol = str(item.get("symbol") or "").strip()
        if symbol not in symbols:
            raise ValueError("objection schema invalid: symbol")
        objection = _sanitize_render_text(str(item.get("objection") or ""))
        severity = str(item.get("severity") or "")
        confidence_adjustment = str(item.get("confidence_adjustment") or "")
        if not objection:
            raise ValueError("objection schema invalid: objection")
        length_truncated = False
        if len(objection) > 80:
            if not soft_length:
                raise ValueError("objection schema invalid: objection")
            objection = _soft_trim(objection, 80)
            length_truncated = True
        if severity not in {"low", "med", "high"}:
            raise ValueError("objection schema invalid: severity")
        if confidence_adjustment not in {"none", "downgrade"}:
            raise ValueError("objection schema invalid: confidence_adjustment")
        entry = {
            "symbol": symbol,
            "objection": objection,
            "severity": severity,
            "confidence_adjustment": confidence_adjustment,
        }
        if length_truncated:
            entry["length_truncated"] = "true"
        objections[symbol] = entry
    return objections


def _downgrade_confidence(confidence: str) -> str:
    if confidence == "high":
        return "med"
    if confidence == "med":
        return "low"
    return "low"


def _objection_prompt(cards: list[dict[str, Any]]) -> str:
    payload = [
        {
            "symbol": card.get("symbol"),
            "slot": card.get("slot"),
            "stance": card.get("stance"),
            "confidence": card.get("confidence"),
            "rationale": card.get("rationale"),
            "evidence_summary": card.get("_evidence_summary"),
        }
        for card in cards
    ]
    return OBJECTION_PROMPT_TEMPLATE.format(cards_json=_json_dumps(payload))


def _apply_objections(cards: list[dict[str, Any]], objections: dict[str, dict[str, str]]) -> None:
    for card in cards:
        objection = objections.get(str(card.get("symbol") or ""))
        if not objection:
            card["objection"] = None
            continue
        card["objection"] = objection
        if objection["severity"] == "high":
            card["confidence"] = _downgrade_confidence(str(card.get("confidence") or "low"))


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    con = sqlite3.connect(resolved)
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(db_path: str | Path | None = None) -> None:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    with sqlite3.connect(resolved) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS m59_discretion_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of TEXT NOT NULL,
                symbol TEXT NOT NULL,
                slot TEXT NOT NULL,
                card_json TEXT NOT NULL,
                inputs_digest TEXT NOT NULL,
                provider TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(as_of, symbol, slot)
            );
            CREATE INDEX IF NOT EXISTS idx_m59_discretion_cards_as_of
            ON m59_discretion_cards(as_of);
            CREATE INDEX IF NOT EXISTS idx_m59_discretion_cards_symbol
            ON m59_discretion_cards(symbol);
            """
        )
        con.commit()


def _latest_rule_version(con: sqlite3.Connection, symbol: str, as_of: str) -> str:
    table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='signals'"
    ).fetchone()
    if table is None:
        return "unknown"
    cols = {str(row[1]) for row in con.execute("PRAGMA table_info(signals)")}
    if not {"symbol", "date", "rule_version"} <= cols:
        return "unknown"
    order_by = "date DESC, id DESC" if "id" in cols else "date DESC"
    row = con.execute(
        f"""
        SELECT rule_version
        FROM signals
        WHERE symbol = ? AND date <= ?
        ORDER BY {order_by}
        LIMIT 1
        """,
        (symbol, as_of),
    ).fetchone()
    return str(row["rule_version"] or "unknown") if row else "unknown"


def _upsert_card(db_path: str | Path | None, card: dict[str, Any]) -> None:
    ensure_schema(db_path)
    with _connect(db_path) as con:
        con.execute(
            """
            INSERT INTO m59_discretion_cards(
                as_of, symbol, slot, card_json, inputs_digest, provider, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(as_of, symbol, slot) DO UPDATE SET
                card_json=excluded.card_json,
                inputs_digest=excluded.inputs_digest,
                provider=excluded.provider,
                created_at=excluded.created_at
            """,
            (
                card["as_of"],
                card["symbol"],
                card["slot"],
                _json_dumps(card),
                card["inputs_digest"],
                card["provider"],
                card["created_at"],
            ),
        )
        con.commit()


def _build_context(symbol: str, db_path: str | Path | None, as_of: str) -> tuple[dict[str, Any], str]:
    resolved = Path(db_path) if db_path is not None else default_sqlite_path()
    engine = create_engine(f"sqlite:///{resolved}")
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        pack = build_stock_context_pack(
            symbol,
            as_of=datetime.fromisoformat(as_of),
            sections=CONTEXT_SECTIONS,
            db=db,
        )
        context_text = render_context_text(pack, max_chars=2400)
        try:
            from backend.memory.context_governor import ContextBudget, build_agent_context

            governed = build_agent_context(
                db,
                task_type="m59_discretion",
                query="盘后裁量参考上下文",
                symbol=symbol,
                budget=ContextBudget(total=900, resident=360, retrieval=540),
            )
            pack["context_governor"] = {
                "provenance": governed["provenance"],
                "omitted": governed["omitted"],
                "token_estimate": governed["token_estimate"],
                "trace_id": governed["trace_id"],
            }
            if governed["text"]:
                context_text = f"{context_text}\n\n{governed['text']}"
        except Exception as exc:  # noqa: BLE001 - context governor must not bypass observe-only degradation.
            pack["context_governor"] = {"error": f"{type(exc).__name__}: {exc}"}
        return pack, context_text
    finally:
        db.close()
        engine.dispose()


def _build_prompt(slot: str, item: dict[str, Any], context_pack: dict[str, Any], context_text: str) -> str:
    return PROMPT_TEMPLATE.format(
        slot=slot,
        allowed_stance=" / ".join(_allowed_stances(slot)),
        panel_item_json=_json_dumps(item),
        context_pack_json=_json_dumps(context_pack),
        context_text=context_text,
    )


def build_discretion_cards(
    panel: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    as_of: str | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    day = _as_of(panel, as_of)
    selected = select_panel_items(panel)
    if not selected:
        return {"ok": True, "as_of": day, "cards": [], "skipped": 0, "degradations": [], "text": "裁量层: 无需调用"}

    if provider is None and not has_runtime_llm_provider(settings):
        reason = "无 runtime provider"
        return {
            "ok": True,
            "as_of": day,
            "cards": [],
            "skipped": len(selected),
            "degradations": [{"reason": reason, "count": len(selected)}],
            "text": f"裁量层降级: {reason} {len(selected)} 支",
        }

    provider = provider or get_provider()
    provider_name = _provider_name(provider)
    cards: list[dict[str, Any]] = []
    degradations: dict[str, int] = {}
    skipped = 0
    with _connect(db_path) as con:
        for entry in selected:
            slot = str(entry["slot"])
            item = entry["item"]
            symbol = str(item["symbol"])
            try:
                context_pack, context_text = _build_context(symbol, db_path, day)
                inputs = {"panel_item": item, "context_pack": context_pack, "slot": slot}
                data = provider.complete_structured(
                    prompt=_build_prompt(slot, item, context_pack, context_text),
                    tool=DISCRETION_TOOL,
                    system=SYSTEM_PROMPT,
                    max_tokens=450,
                    model_tier="capable",
                )
                llm_card = _validate_card(data, slot=slot, soft_length=True)
                digest = _digest(inputs)
                card = {
                    **llm_card,
                    "slot": slot,
                    "symbol": symbol,
                    "reference_only": True,
                    "rule_profile_version": _latest_rule_version(con, symbol, day),
                    "inputs_digest": digest,
                    "provider": provider_name,
                    "as_of": day,
                    "created_at": _now_iso(),
                    "_evidence_summary": context_text[:600],
                }
                cards.append(card)
            except Exception as exc:  # noqa: BLE001 - observe-only layer must not block M63.
                reason = f"{type(exc).__name__}: {exc}"
                degradations[reason] = degradations.get(reason, 0) + 1
                skipped += 1
        if cards:
            try:
                objection_data = provider.complete_structured(
                    prompt=_objection_prompt(cards),
                    tool=OBJECTION_TOOL,
                    system=OBJECTION_SYSTEM_PROMPT,
                    max_tokens=900,
                    model_tier="capable",
                )
                objections = _validate_objections(
                    objection_data,
                    {str(card["symbol"]) for card in cards},
                    soft_length=True,
                )
                _apply_objections(cards, objections)
            except Exception as exc:  # noqa: BLE001 - adversarial review degrades without blocking cards.
                reason = f"反方审视失败: {type(exc).__name__}: {exc}"
                degradations[reason] = degradations.get(reason, 0) + 1
                for card in cards:
                    card["objection"] = None
        for card in cards:
            card.pop("_evidence_summary", None)
            _upsert_card(db_path, card)
    degradation_items = [{"reason": reason, "count": count} for reason, count in degradations.items()]
    texts = [f"裁量层完成: {len(cards)} 支"] if cards else []
    texts.extend(f"裁量层降级: {item['reason']} {item['count']} 支" for item in degradation_items)
    return {
        "ok": True,
        "as_of": day,
        "cards": cards,
        "skipped": skipped,
        "degradations": degradation_items,
        "text": "；".join(texts) if texts else "裁量层: 无结果",
    }


def render_stance(stance: str) -> str:
    return STANCE_RENDER_LABELS.get(stance, stance)


def render_card_lines(result: dict[str, Any] | None) -> list[str]:
    if not result:
        return ["裁量层: 未运行"]
    lines: list[str] = []
    for card in result.get("cards") or []:
        line = (
            f"{card.get('symbol')} 倾向:{render_stance(str(card.get('stance') or ''))} "
            f"信心:{card.get('confidence')}; 理由:{card.get('rationale')}; "
            f"时机:{card.get('timing_note') or '-'}; 再评估:{card.get('reevaluation_trigger')}"
        )
        objection = card.get("objection") if isinstance(card.get("objection"), dict) else None
        if objection and objection.get("severity") in {"med", "high"}:
            line += f"; ⚖️ 反方: {_sanitize_render_text(str(objection.get('objection') or ''))}"
        lines.append(line)
    for item in result.get("degradations") or []:
        lines.append(f"裁量层降级: {item.get('reason')} {item.get('count')} 支")
    return lines or ["裁量层: 暂无参考卡"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build M59 observe-only LLM discretion cards.")
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from backend.tools.m59_panel import build_panel

    panel = build_panel(db_path=args.db_path, as_of=args.as_of)
    result = build_discretion_cards(panel, db_path=args.db_path, as_of=args.as_of)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        for line in render_card_lines(result):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
