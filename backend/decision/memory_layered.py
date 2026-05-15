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
import json
from datetime import datetime, timedelta
from pathlib import Path
from backend.decision.signal_policy import entry_recommendations

from backend.config import settings

MEMORY_DIR = Path.home() / ".stock-sage" / "memory"
LONG_TERM_PATH = MEMORY_DIR / "long_term_reflection.md"

_SHORT_TERM: dict[str, list[dict]] = {}  # symbol → list of recent decisions
_MAX_SHORT_TERM = 7


def _ensure_dir() -> None:
    """Ensure the layered memory directory exists."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _medium_path(symbol: str) -> Path:
    """Return the path to the medium-term memory file for a symbol."""
    return MEMORY_DIR / f"medium_{symbol}.md"


def save_short_term(symbol: str, signal: dict) -> None:
    """写入运行时短期记忆"""
    arr = _SHORT_TERM.setdefault(symbol, [])
    arr.append({
        "ts": datetime.utcnow().isoformat(),
        "score": signal.get("composite_score"),
        "rec": signal.get("recommendation"),
        "stop": signal.get("stop_loss"),
        "take": signal.get("take_profit"),
        "veto": signal.get("veto_reason"),
    })
    if len(arr) > _MAX_SHORT_TERM:
        arr.pop(0)


def save_medium_term(symbol: str, date: str, signal: dict) -> None:
    """追加到该股的中期记忆 markdown 表（保留全部历史，由 get_layered_context 取最新5笔）"""
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


def save_decision_layered(symbol: str, date: str, signal: dict) -> None:
    """统一入口：同时写短期+中期"""
    save_short_term(symbol, signal)
    save_medium_term(symbol, date, signal)


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


def get_long_term_context() -> str:
    """全局长期反思（所有股票共享）"""
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
    long_term = get_long_term_context()
    if long_term:
        parts.append(long_term)
    medium = get_medium_term_context(symbol, db, lookback_days)
    if medium:
        parts.append(medium)
    short = get_short_term_context(symbol)
    if short:
        parts.append(short)
    return "\n".join(parts)


def weekly_long_term_reflect(db) -> str | None:
    """
    调度器周末调用：把过去 7 天所有失败信号丢给 Sonnet，写入 long_term_reflection.md。
    返回新增章节的摘要；失败返回 None。
    """
    from backend.data.database import Signal, Price
    from backend.llm import get_provider

    cutoff = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    sigs = (db.query(Signal)
            .filter(Signal.date >= cutoff)
            .filter(Signal.recommendation.in_(entry_recommendations(include_legacy=True)))
            .order_by(Signal.date.asc()).all())
    if not sigs:
        return None

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
        if pct < 0:
            fail_lines.append(f"- {sig.date} {sig.symbol} 建议{sig.recommendation}(综合分{sig.composite_score:+.0f}) → 实际{pct:+.2f}% 失败")

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
    week_label = datetime.utcnow().strftime("%Y-W%V")
    section = f"\n## {week_label}\n\n失败信号:\n" + "\n".join(fail_lines) + f"\n\n反思:\n{text}\n"
    with LONG_TERM_PATH.open("a", encoding="utf-8") as f:
        f.write(section)
    return text
