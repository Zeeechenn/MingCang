"""M63 shared human-readable report rendering helpers."""

from __future__ import annotations

import re
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from backend.research.research_evidence_defs import FORBIDDEN_REPORT_WORDING

logger = logging.getLogger(__name__)

GLOSSARY: dict[str, str] = {
    "ATR": "平均真实波幅,用来估算一只股票平时每天大概波动多大。",
    "止损位": "预先写好的风险线,跌破后需要盘后重新决断,不是价格预测。",
    "止盈位": "预先写好的收益参考线,用于提醒保护浮盈,不是保证能到的目标价。",
    "解禁": "原来不能流通的股票到期可卖,短期可能增加卖压。",
    "定增": "公司向特定对象增发股票融资,会影响股本和市场预期。",
    "龙虎榜": "交易所披露的异常交易席位榜单,常用于观察短线资金行为。",
    "主力资金": "大额资金流入流出的统计口径,只能作资金热度参考。",
    "Piotroski": "九项财务质量打分,分越高通常代表财务韧性越好。",
    "估值偏高": "长期标签,表示当前价格相对基本面不便宜,需要更高安全边际。",
    "规避": "长期或风险标签,表示暂不适合作为重点研究对象。",
    "观望": "证据不够强或风险收益不清晰,先放入观察而非行动。",
    "可关注": "进入观察清单,等待盘后证据确认,不是操作指令。",
    "动量": "一段时间内价格延续上涨或下跌的强弱。",
    "回撤": "从阶段高点往下跌的幅度。",
    "EPS": "每股收益,常用于看公司盈利和估值。",
    "研报评级": "券商研究报告给出的观点标签,只能作为外部参考。",
    "观察哨": "只扫描已关注标的是否出现价格、资金、新闻或主题联动变化,触发后进入盘后复核,不是操作指令。",
    "触发器": "把异常变化记录成待复核事项的规则,用于提醒继续研究,不等于结论。",
    "sector_resonance": "联动共振,同一观察主题里多数已有价格数据的成员同日上涨且平均涨幅超过阈值。",
    "lhb_spotlight": "龙虎榜上榜,交易所异常交易席位榜单出现该标的,用于观察短线资金行为。",
    "flow_anomaly": "资金流异动,当日主力资金相对近期分布偏离较大,用于提示资金热度异常。",
    "accrual": "前向账本计提,把每日新证据先记入待验证账本,等后续结果兑现再复盘。",
    "影子出场": "影子臂对照的出场参数试验,只做验证记录,不影响实际持仓。",
    "1.5×ATR": "初始风险线口径:一倍半平均日波幅,用于估算正常波动外的风险缓冲。",
}

SEMANTIC_NOTES: dict[str, str] = {
    "long_term_signal": (
        "说明:长期标签管'这公司值不值得研究',信号管'现在是不是买点',"
        "出场规则管'持有中怎么退'--三者各管一段,不互相否决。"
    ),
    "position_avoid": (
        "长期标签(规避)与当前持仓并存:标签是长期研究观点,"
        "持仓处置以止损纪律与保护动作为准,不构成自动平仓指令"
    ),
    "position_overvalued": (
        "长期标签(估值偏高)与当前持仓并存:标签是长期研究观点,"
        "持仓处置以止损纪律与保护动作为准,不构成自动平仓指令"
    ),
}

LANGUAGE_GUARD_WORDS = ("买入", "卖出", "加仓", "清仓", "建仓")
_LOCAL_LANGUAGE_GUARD_PATTERNS = (
    "买入",
    "卖出",
    "加仓",
    "清仓",
    "建仓",
    "满仓",
    "梭哈",
    "抄底",
    "半仓",
    "重仓",
    "全仓买",
    "强烈推荐",
    "目标价",
    "必涨",
    "必跌",
    r"\b(strong buy|buy now|sell now)\b",
)
_LANGUAGE_GUARD_PATTERNS = tuple(dict.fromkeys([*_LOCAL_LANGUAGE_GUARD_PATTERNS, *(pattern for pattern, _ in FORBIDDEN_REPORT_WORDING)]))


def _language_guard_pattern(pattern: str) -> re.Pattern[str]:
    flags = re.IGNORECASE if pattern.isascii() else 0
    return re.compile(pattern, flags)


def _language_guard_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _LANGUAGE_GUARD_PATTERNS:
        if _language_guard_pattern(pattern).search(text):
            hits.append(pattern)
    return hits


def sanitize_trade_words(text: str) -> tuple[str, int]:
    """Replace trade wording in-place without the report footer; returns (text, hits)."""
    sanitized = text
    count = 0
    for pattern in _LANGUAGE_GUARD_PATTERNS:
        sanitized, replaced = _language_guard_pattern(pattern).subn("[操作词已屏蔽]", sanitized)
        count += replaced
    return sanitized, count


def enforce_language_guard(text: str, mode: str = "strict") -> str:
    """Apply M63 wording guard in strict or sanitizing mode."""
    if mode not in {"strict", "sanitize"}:
        raise ValueError(f"unknown language guard mode: {mode}")
    hits = _language_guard_hits(text)
    if not hits:
        return text
    if mode == "strict":
        raise ValueError(f"M63 language guard blocked trade words: {', '.join(hits)}")

    sanitized, count = sanitize_trade_words(text)
    logger.warning(
        "M63 language guard sanitized %s actionable wording hit(s); compliance design, not an error",
        count,
    )
    return (
        sanitized.rstrip()
        + f"\n⚠️ 语言守卫：已屏蔽 {count} 处操作性表述(合规设计,系统不输出买卖指令,非错误)\n"
    )


def assert_no_trade_words(text: str) -> None:
    """Reject direct trading verbs in premarket/intraday reports."""
    enforce_language_guard(text, mode="strict")


def format_cn_number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    if not isinstance(value, (int, float)):
        return str(value)
    abs_value = abs(float(value))
    if abs_value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if abs_value >= 10_000:
        return f"{value / 10_000:.2f}万"
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{float(value):.2f}"


def _format_line(line: Any) -> str:
    if isinstance(line, dict):
        parts = []
        for key, value in line.items():
            parts.append(f"{key}:{format_cn_number(value)}")
        return " | ".join(parts)
    if isinstance(line, (list, tuple)):
        return " | ".join(format_cn_number(value) for value in line)
    return str(line)


def render_section(title: str, lines: Sequence[Any] | None) -> str:
    body = [_format_line(line) for line in (lines or []) if _format_line(line).strip()]
    if not body:
        body = ["暂无"]
    width = max(18, len(title) + 4)
    return "\n".join([f"## {title}", "-" * width, *body])


def _collect_terms(text: str, glossary_terms: Iterable[str] | None) -> list[str]:
    candidates = set(glossary_terms or [])
    for term in GLOSSARY:
        if term in text:
            candidates.add(term)
    return [term for term in GLOSSARY if term in candidates and term in text]


def render_report(
    sections: Sequence[tuple[str, Sequence[Any]] | dict[str, Any]],
    glossary_terms: Iterable[str] | None = None,
) -> str:
    rendered_sections: list[str] = []
    for section in sections:
        if isinstance(section, dict):
            title = str(section.get("title", "未命名"))
            lines = section.get("lines") or []
        else:
            title, lines = section
        rendered_sections.append(render_section(title, lines))
    text = "\n\n".join(rendered_sections)
    terms = _collect_terms(text, glossary_terms)
    if terms:
        footnotes = ["", "(?)term explanations"]
        footnotes.extend(f"- {term}: {GLOSSARY[term]}" for term in terms)
        text += "\n".join(footnotes)
    return text.rstrip() + "\n"


def inject_semantic_notes(lines: list[str]) -> list[str]:
    text = "\n".join(lines)
    notes: list[str] = []
    if "长期标签" in text and ("信号" in text or "建议" in text):
        notes.append(SEMANTIC_NOTES["long_term_signal"])
    if "持仓" in text and "规避" in text:
        notes.append(SEMANTIC_NOTES["position_avoid"])
    if "持仓" in text and "估值偏高" in text:
        notes.append(SEMANTIC_NOTES["position_overvalued"])
    return [*lines, *notes] if notes else lines


def strip_raw_json(text: str) -> str:
    """Small guardrail for accidental raw JSON dumps in terminal reports."""
    return re.sub(r"\{[^{}\n]{80,}\}", "{...}", text)
