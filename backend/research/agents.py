"""Deterministic role templates for manual deep research."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchSection:
    """A named research-role section used by the deep research writer."""

    role: str
    title: str
    content: str
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    valuation_anchor: str = ""
    evidence_snippets: tuple[str, ...] = ()
    stance: str = ""
    confidence: float = 0.5


def _symbol_label(symbol: str, names: dict[str, str]) -> str:
    """Return a display label for a symbol."""
    return f"{symbol} {names.get(symbol, '')}".strip()


def _bounded_confidence(value: float) -> float:
    """Clamp confidence into the IC memo range."""
    return round(min(1.0, max(0.0, value)), 2)


def _sector_researcher(topic: str, symbols: list[str], names: dict[str, str]) -> ResearchSection:
    """Build the sector/theme research section."""
    covered = "、".join(_symbol_label(symbol, names) for symbol in symbols) or "未指定标的"
    return ResearchSection(
        role="sector_researcher",
        title="行业/主题研究员",
        content=f"主题为 {topic}，覆盖 {covered}。重点观察产业景气、政策催化、订单兑现和估值拥挤度。",
        catalysts=("产业景气改善", "政策或订单催化", "订单兑现超预期"),
        risks=("估值拥挤", "景气反转"),
        valuation_anchor="对照行业 PE/PB 均值与历史分位，避免只看主题叙事。",
        evidence_snippets=(f"主题覆盖：{covered}",),
        stance="中性",
        confidence=0.55 if symbols else 0.4,
    )


def _company_researcher(
    symbols: list[str],
    names: dict[str, str],
    prices: list[dict],
    financials: list[dict],
) -> ResearchSection:
    """Build the company-level research section."""
    price_by_symbol = {item["symbol"]: item for item in prices}
    fin_by_symbol = {item["symbol"]: item for item in financials}
    lines = []
    catalysts: list[str] = []
    risks: list[str] = []
    evidence: list[str] = []
    for symbol in symbols:
        price = price_by_symbol.get(symbol, {})
        fin = fin_by_symbol.get(symbol, {})
        trend = f"近20日变化 {price.get('change_20d')}%" if price.get("available") else "暂无价格上下文"
        quality = (
            f"报告期 {fin.get('report_date')}，ROE {fin.get('roe')}"
            if fin.get("available") else "暂无财务指标上下文"
        )
        lines.append(f"{_symbol_label(symbol, names)}：{trend}；{quality}。")
        label = _symbol_label(symbol, names)
        change = price.get("change_20d") if price.get("available") else None
        if isinstance(change, (int, float)):
            if change > 5:
                catalysts.append(f"{label} 近20日趋势较强")
            elif change < -5:
                risks.append(f"{label} 近20日走弱")
        roe = fin.get("roe") if fin.get("available") else None
        if isinstance(roe, (int, float)):
            if roe > 10:
                catalysts.append(f"{label} ROE 有支撑")
            elif roe < 0:
                risks.append(f"{label} ROE 为负")
        evidence.append(f"{label}：{trend}；{quality}")
    return ResearchSection(
        role="company_researcher",
        title="公司研究员",
        content=" ".join(lines) if lines else "未指定个股，跳过公司层快照。",
        catalysts=tuple(catalysts[:4]),
        risks=tuple(risks[:4]),
        valuation_anchor="以最新 ROE、营收/净利同比和价格位置交叉校验估值锚。",
        evidence_snippets=tuple(evidence[:5]),
        stance="偏多" if len(catalysts) > len(risks) else ("偏空" if len(risks) > len(catalysts) else "中性"),
        confidence=_bounded_confidence(0.45 + 0.08 * len(evidence)),
    )


def _risk_reviewer(risk_flags: list[str]) -> ResearchSection:
    """Build the risk review section."""
    if risk_flags:
        content = "来源/数据风险标记：" + "、".join(risk_flags) + "。需降低对应证据权重。"
    else:
        content = "暂未发现来源审计层面的硬风险；仍需结合估值、仓位和大盘环境。"
    return ResearchSection(
        role="risk_reviewer",
        title="风险复核员",
        content=content,
        risks=tuple(risk_flags[:5]) if risk_flags else ("估值、仓位和大盘环境仍需复核",),
        evidence_snippets=(content,),
        stance="偏空" if risk_flags else "中性",
        confidence=_bounded_confidence(0.55 + 0.08 * len(risk_flags)) if risk_flags else 0.45,
    )


def _source_auditor(source_count: int, weak_source_count: int) -> ResearchSection:
    """Build the source audit summary section."""
    return ResearchSection(
        role="source_auditor",
        title="来源审计员",
        content=f"可追溯来源 {source_count} 条，降权/弱来源 {weak_source_count} 条。",
        risks=(f"{weak_source_count} 条来源需降权",) if weak_source_count else (),
        evidence_snippets=(f"可追溯来源 {source_count} 条，弱来源 {weak_source_count} 条",),
        stance="中性",
        confidence=_bounded_confidence(source_count / max(source_count + weak_source_count, 1)),
    )


def _research_writer(topic: str, source_count: int, weak_source_count: int) -> ResearchSection:
    """Build the final writer synthesis section."""
    return ResearchSection(
        role="research_writer",
        title="研究写作员",
        content=(
            f"{topic} 的结论应以可追溯证据为主；本次 {source_count} 条来源可用，"
            f"{weak_source_count} 条需降权。结论只用于专题研究，不直接触发交易。"
        ),
        catalysts=(f"{topic} 具备可继续跟踪的专题研究价值",) if source_count else (),
        risks=(f"{weak_source_count} 条来源需降权",) if weak_source_count else (),
        valuation_anchor="结论需回到估值、订单兑现和仓位约束，不直接映射交易动作。",
        evidence_snippets=(f"{source_count} 条来源可用，{weak_source_count} 条需降权",),
        stance="偏空" if weak_source_count > source_count else ("中性" if source_count else "偏空"),
        confidence=_bounded_confidence(0.35 + min(source_count, 6) * 0.08 - weak_source_count * 0.04),
    )


def build_research_sections(
    *,
    topic: str,
    symbols: list[str],
    names: dict[str, str],
    prices: list[dict],
    financials: list[dict],
    source_count: int,
    weak_source_count: int,
    risk_flags: list[str],
) -> list[ResearchSection]:
    """Build deterministic role sections for a deep research report."""
    return [
        _sector_researcher(topic, symbols, names),
        _company_researcher(symbols, names, prices, financials),
        _risk_reviewer(risk_flags),
        _source_auditor(source_count, weak_source_count),
        _research_writer(topic, source_count, weak_source_count),
    ]
