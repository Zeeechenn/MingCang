"""Deterministic role templates for manual deep research."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchSection:
    """A named research-role section used by the deep research writer."""

    role: str
    title: str
    content: str


def _symbol_label(symbol: str, names: dict[str, str]) -> str:
    """Return a display label for a symbol."""
    return f"{symbol} {names.get(symbol, '')}".strip()


def _sector_researcher(topic: str, symbols: list[str], names: dict[str, str]) -> ResearchSection:
    """Build the sector/theme research section."""
    covered = "、".join(_symbol_label(symbol, names) for symbol in symbols) or "未指定标的"
    return ResearchSection(
        role="sector_researcher",
        title="行业/主题研究员",
        content=f"主题为 {topic}，覆盖 {covered}。重点观察产业景气、政策催化、订单兑现和估值拥挤度。",
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
    for symbol in symbols:
        price = price_by_symbol.get(symbol, {})
        fin = fin_by_symbol.get(symbol, {})
        trend = f"近20日变化 {price.get('change_20d')}%" if price.get("available") else "暂无价格上下文"
        quality = (
            f"报告期 {fin.get('report_date')}，ROE {fin.get('roe')}"
            if fin.get("available") else "暂无财务指标上下文"
        )
        lines.append(f"{_symbol_label(symbol, names)}：{trend}；{quality}。")
    return ResearchSection(
        role="company_researcher",
        title="公司研究员",
        content=" ".join(lines) if lines else "未指定个股，跳过公司层快照。",
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
    )


def _source_auditor(source_count: int, weak_source_count: int) -> ResearchSection:
    """Build the source audit summary section."""
    return ResearchSection(
        role="source_auditor",
        title="来源审计员",
        content=f"可追溯来源 {source_count} 条，降权/弱来源 {weak_source_count} 条。",
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
