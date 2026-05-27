"""
FinMem 风格分层决策记忆（阶段C）

三层记忆：
  • short_term: 当日所有股票的 Signal（运行时字典）
  • medium_term: ~/.stock-sage/memory/medium_{symbol}.md
                 该股最近 5 笔信号 + 实际盈亏的 markdown 表
  • long_term:  ~/.stock-sage/memory/long_term_reflection.md
                 每周末 LLM 自动总结系统的偏差和教训

调用约定：
  • save_decision_layered() — 替代 decision_memory.save_decision()
  • get_layered_context()    — 替代 decision_memory.get_reflection_context()
  • weekly_long_term_reflect() — 调度器周末调用，生成长期反思
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.config import settings
from backend.decision.signal_policy import entry_recommendations

MEMORY_DIR = Path.home() / ".stock-sage" / "memory"
LONG_TERM_PATH = MEMORY_DIR / "long_term_reflection.md"

_SHORT_TERM: dict[str, list[dict]] = {}  # symbol → list of recent decisions
_MAX_SHORT_TERM = 7
_MAX_MEDIUM_TERM_ROWS = 30


def _ensure_dir() -> None:
    """Ensure the layered memory directory exists."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _medium_path(symbol: str) -> Path:
    """Return the path to the medium-term memory file for a symbol."""
    return MEMORY_DIR / f"medium_{symbol}.md"


def _trim_medium_content(content: str, *, max_rows: int | None = None) -> str:
    """Keep only the newest medium-term table rows to cap prompt growth."""
    max_rows = max_rows or _MAX_MEDIUM_TERM_ROWS
    lines = content.splitlines()
    rows = [
        line for line in lines
        if line.startswith("| ") and not line.startswith("| 日期 ") and not line.startswith("|------")
    ]
    if len(rows) <= max_rows:
        return content if content.endswith("\n") else content + "\n"
    kept_rows = rows[-max_rows:]
    header = ("| 日期 | 建议 | 综合分 | 仓位 | 止损 | 止盈 | 风控备注 |\n"
              "|------|------|--------|------|------|------|----------|\n")
    title = lines[0] if lines else "# 中期决策记忆"
    return f"{title}\n\n{header}{''.join(row + chr(10) for row in kept_rows)}"


def save_short_term(symbol: str, signal: dict) -> None:
    """写入运行时短期记忆"""
    arr = _SHORT_TERM.setdefault(symbol, [])
    arr.append({
        "ts": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "score": signal.get("composite_score"),
        "rec": signal.get("recommendation"),
        "stop": signal.get("stop_loss"),
        "take": signal.get("take_profit"),
        "veto": signal.get("veto_reason"),
    })
    if len(arr) > _MAX_SHORT_TERM:
        arr.pop(0)


def save_medium_term(symbol: str, date: str, signal: dict, db=None) -> None:
    """追加到该股的中期记忆 markdown 表（保留全部历史）。

    M9.1：文件 + DB 双写。文件保留作为旧路径兜底，DB 是 source of truth；
    若未提供 db 则仅写文件（保持兼容）。
    """
    if not settings.layered_memory_enabled:
        return
    _ensure_dir()
    path = _medium_path(symbol)
    header = ("| 日期 | 建议 | 综合分 | 仓位 | 止损 | 止盈 | 风控备注 |\n"
              "|------|------|--------|------|------|------|----------|\n")
    arb = signal.get("llm_arbitration", {}) or {}
    bias = arb.get("action_bias", "-")
    risk_notes = signal.get("risk_notes", [])
    veto = signal.get("veto_reason")
    note = veto if veto else ("; ".join(risk_notes) if risk_notes else bias)
    row = (
        f"| {date} | {signal.get('recommendation','-')} | "
        f"{signal.get('composite_score', 0):+.0f} | "
        f"{(signal.get('position_pct') or 0) * 100:.1f}% | "
        f"{signal.get('stop_loss', 0):.2f} | "
        f"{signal.get('take_profit', 0):.2f} | "
        f"{note} |\n"
    )
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(f"# {symbol} 中期决策记忆\n\n{header}", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(row)
    trimmed = _trim_medium_content(path.read_text(encoding="utf-8"))
    path.write_text(trimmed, encoding="utf-8")

    if db is not None:
        _upsert_layered_row(db, symbol=symbol, layer="medium",
                            content=trimmed)


def save_decision_layered(symbol: str, date: str, signal: dict, db=None) -> None:
    """统一入口：同时写短期+中期；若提供 db 则同时写一笔 audit + 双写 DB。"""
    save_short_term(symbol, signal)
    save_medium_term(symbol, date, signal, db=db)
    if db is not None:
        from backend.memory.audit_log import audit_write
        from backend.memory.stock_memory import create_stock_memory
        audit_write(
            db,
            "decision_memory.save",
            f"symbol={symbol} date={date} rec={signal.get('recommendation','-')} "
            f"score={signal.get('composite_score', 0):+.0f}",
            related_symbol=symbol,
        )
        create_stock_memory(
            db,
            symbol=symbol,
            memory_type="judgment",
            summary=(
                f"{date} 建议{signal.get('recommendation','-')}，"
                f"综合分{signal.get('composite_score', 0):+.0f}，"
                f"仓位{(signal.get('position_pct') or 0) * 100:.1f}%"
            ),
            evidence={
                "date": date,
                "recommendation": signal.get("recommendation"),
                "composite_score": signal.get("composite_score"),
                "stop_loss": signal.get("stop_loss"),
                "take_profit": signal.get("take_profit"),
                "veto_reason": signal.get("veto_reason"),
            },
            source_type="postmarket_signal",
            source_ref=f"{symbol}:{date}",
            importance=3,
            confidence=0.6,
        )


_GLOBAL_SENTINEL = "__GLOBAL__"


def _coerce_symbol(symbol: str | None) -> str:
    """Map None → sentinel so UNIQUE(symbol, layer) works under SQLite NULL rules."""
    return symbol if symbol else _GLOBAL_SENTINEL


def _upsert_layered_row(db, *, symbol: str | None, layer: str, content: str) -> None:
    """Upsert a row into `decision_memory_layered` keyed by (symbol, layer).

    SQLite treats NULL ≠ NULL for UNIQUE, so the long-term row (no symbol)
    uses a `__GLOBAL__` sentinel internally.
    """
    from datetime import datetime as _dt

    from sqlalchemy import text as _text
    db.execute(_text("""
        INSERT INTO decision_memory_layered(symbol, layer, content, updated_at)
        VALUES(:symbol, :layer, :content, :now)
        ON CONFLICT(symbol, layer) DO UPDATE SET
            content = excluded.content,
            updated_at = excluded.updated_at
    """), {
        "symbol": _coerce_symbol(symbol),
        "layer": layer,
        "content": content,
        "now": _dt.utcnow().isoformat(timespec="seconds"),
    })
    db.commit()


def migrate_layered_files_to_db(db) -> dict:
    """One-shot ingest of `~/.stock-sage/memory/{medium_*.md, long_term_reflection.md}`
    into `decision_memory_layered`. Idempotent (upsert). Returns counts dict."""
    counts = {"medium": 0, "long": 0}
    if not MEMORY_DIR.exists():
        return counts
    for path in MEMORY_DIR.glob("medium_*.md"):
        symbol = path.stem.removeprefix("medium_")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        _upsert_layered_row(db, symbol=symbol, layer="medium", content=content)
        counts["medium"] += 1
    if LONG_TERM_PATH.exists():
        try:
            content = LONG_TERM_PATH.read_text(encoding="utf-8")
            _upsert_layered_row(db, symbol=None, layer="long", content=content)
            counts["long"] = 1
        except OSError:
            pass
    return counts


def get_short_term_context(symbol: str) -> str:
    """Return formatted string of recent in-session decisions for a symbol."""
    arr = _SHORT_TERM.get(symbol, [])
    if not arr:
        return ""
    lines = ["【短期记忆 — 本会话信号】"]
    for d in arr[-3:]:
        lines.append(f"- {d['ts'][:10]} {d['rec']} 综合{d['score']:+.0f}")
    return "\n".join(lines) + "\n"


def get_medium_term_context(symbol: str, db, lookback_days: int = 30) -> str:
    """复用原 decision_memory.get_reflection_context 思路 + 中期表头部"""
    from backend.decision.decision_memory import get_reflection_context
    return get_reflection_context(symbol, db, lookback_days)


def get_long_term_context(db=None) -> str:
    """全局长期反思（所有股票共享）。优先读 DB，缺失时退回文件。"""
    text: str | None = None
    if db is not None:
        from sqlalchemy import text as _text
        row = db.execute(_text(
            "SELECT content FROM decision_memory_layered "
            "WHERE symbol = :sentinel AND layer='long' LIMIT 1"
        ), {"sentinel": _GLOBAL_SENTINEL}).first()
        if row and row.content:
            text = row.content
    if text is None:
        if not LONG_TERM_PATH.exists():
            return ""
        text = LONG_TERM_PATH.read_text(encoding="utf-8")
    # 只取最近 1 节（## 开头）
    sections = text.split("\n## ")
    return "【长期反思】\n## " + sections[-1] + "\n" if len(sections) > 1 else text


def get_layered_context(symbol: str, db, lookback_days: int = 30) -> str:
    """注入给 LLM debate 的完整分层记忆"""
    if not settings.layered_memory_enabled:
        from backend.decision.decision_memory import get_reflection_context
        return get_reflection_context(symbol, db, lookback_days)

    parts = []
    long_term = get_long_term_context(db=db)
    if long_term:
        parts.append(long_term)
    medium = get_medium_term_context(symbol, db, lookback_days)
    if medium:
        parts.append(medium)
    short = get_short_term_context(symbol)
    if short:
        parts.append(short)
    result = "\n".join(parts)
    if result:
        from backend.memory.audit_log import audit_write
        audit_write(
            db,
            "decision_memory.recall",
            f"symbol={symbol} layers={'+'.join(['L' if long_term else '', 'M' if medium else '', 'S' if short else '']).strip('+')}",
            related_symbol=symbol,
        )
    return result


def weekly_long_term_reflect(db) -> str | None:
    """
    调度器周末调用：把过去 7 天所有失败信号丢给 Sonnet，写入 long_term_reflection.md。
    返回新增章节的摘要；失败返回 None。
    """
    from backend.data.database import IndexPrice, Price, Signal
    from backend.llm import get_provider

    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)).strftime("%Y-%m-%d")
    sigs = (db.query(Signal)
            .filter(Signal.date >= cutoff)
            .filter(Signal.recommendation.in_(entry_recommendations(include_legacy=True)))
            .order_by(Signal.date.asc()).all())
    if not sigs:
        return None

    # M15.3 失败判定基准化：用沪深 300 同期收益做超额收益判断，避免大盘大跌日
    # 把所有正向信号系统性记为"失败"导致长期反思偏空。
    def _bench_pct(sig_date: str) -> float | None:
        b0 = (db.query(IndexPrice.close)
              .filter(IndexPrice.symbol == "sh000300", IndexPrice.date == sig_date)
              .first())
        b1 = (db.query(IndexPrice.close)
              .filter(IndexPrice.symbol == "sh000300", IndexPrice.date > sig_date)
              .order_by(IndexPrice.date.asc()).first())
        if not b0 or not b1 or not b0[0]:
            return None
        return (b1[0] - b0[0]) / b0[0] * 100

    fail_lines = []
    for sig in sigs:
        sig_row = (db.query(Price.close)
                   .filter(Price.symbol == sig.symbol, Price.date == sig.date)
                   .first())
        next_row = (db.query(Price.close)
                    .filter(Price.symbol == sig.symbol, Price.date > sig.date)
                    .order_by(Price.date.asc()).first())
        if not sig_row or not next_row:
            continue
        pct = (next_row[0] - sig_row[0]) / sig_row[0] * 100
        bench_pct = _bench_pct(sig.date)
        excess = (pct - bench_pct) if bench_pct is not None else pct
        if excess < 0:
            bench_note = f" (vs HS300 {bench_pct:+.2f}%, 超额 {excess:+.2f}%)" if bench_pct is not None else " (无 HS300 基准, 用裸收益)"
            fail_lines.append(f"- {sig.date} {sig.symbol} 建议{sig.recommendation}(综合分{sig.composite_score:+.0f}) → 实际{pct:+.2f}%{bench_note}")

    if not fail_lines:
        return None

    prompt = (
        '以下是过去 7 天系统给出正向关注但实际亏损的信号。'
        '请用 3 句话总结：(1) 共同失败模式 (2) 可能的系统性偏差 (3) 下周需特别注意的环境信号。\n\n'
        + "\n".join(fail_lines)
    )

    # 顺手修：LLM provider 没有 complete_text，统一走 complete_structured + 简单 tool schema
    _REFLECTION_TOOL = {
        "name": "weekly_reflection",
        "description": "每周失败信号反思",
        "input_schema": {
            "type": "object",
            "properties": {
                "reflection": {
                    "type": "string",
                    "description": "3 句话：(1) 共同失败模式 (2) 系统性偏差 (3) 下周注意点",
                },
            },
            "required": ["reflection"],
        },
    }
    data = get_provider().complete_structured(
        prompt=prompt,
        tool=_REFLECTION_TOOL,
        max_tokens=400,
        model_tier="capable",
    )
    text = data.get("reflection") if data else None
    if not text:
        return None

    _ensure_dir()
    week_label = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-W%V")
    section = f"\n## {week_label}\n\n失败信号:\n" + "\n".join(fail_lines) + f"\n\n反思:\n{text}\n"
    with LONG_TERM_PATH.open("a", encoding="utf-8") as f:
        f.write(section)
    _upsert_layered_row(db, symbol=None, layer="long",
                        content=LONG_TERM_PATH.read_text(encoding="utf-8"))
    return text
