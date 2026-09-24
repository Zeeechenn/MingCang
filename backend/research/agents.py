"""[M63 现役] [active] 消费者: backend/research/deep_research.py.
Deterministic role templates for manual deep research."""
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
        content=f"主题为 {topic}，本次名单覆盖 {covered}。现有输入没有板块指数、供需、同行份额或行业估值序列，不能据此判断行业周期或竞争格局。",
        catalysts=(),
        risks=(),
        valuation_anchor="当前缺少板块 PE/PB、EV 和历史分位输入；需补齐后再评估估值。",
        evidence_snippets=(f"主题覆盖：{covered}",),
        stance="证据不足",
        confidence=0.2 if symbols else 0.1,
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
    observed_metrics = 0
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
            observed_metrics += 1
            if change > 5:
                catalysts.append(f"{label} 近20日趋势较强")
            elif change < -5:
                risks.append(f"{label} 近20日走弱")
        roe = fin.get("roe") if fin.get("available") else None
        if isinstance(roe, (int, float)):
            observed_metrics += 1
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
        stance=(
            "证据不足" if observed_metrics == 0 else
            "偏多" if len(catalysts) > len(risks) else
            "偏空" if len(risks) > len(catalysts) else "中性"
        ),
        confidence=_bounded_confidence(0.2 + min(0.5, 0.12 * observed_metrics)),
    )


def _risk_reviewer(risk_flags: list[str]) -> ResearchSection:
    """Build the risk review section."""
    if risk_flags:
        content = "来源/数据风险标记：" + "、".join(risk_flags) + "。需降低对应证据权重。"
    else:
        content = "当前来源审计没有触发已编码的硬风险标记；这不代表公司、估值或市场风险已被排除。"
    return ResearchSection(
        role="risk_reviewer",
        title="风险复核员",
        content=content,
        risks=tuple(risk_flags[:5]) if risk_flags else ("估值、仓位和大盘环境仍需复核",),
        evidence_snippets=(content,),
        # Source-quality flags describe evidence reliability, not the company outlook.
        stance="证据质量需复核",
        confidence=0.2,
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
        # Source count alone is not evidence that the topic has upside or a catalyst.
        catalysts=(),
        risks=(f"{weak_source_count} 条来源需降权",) if weak_source_count else (),
        valuation_anchor="结论需回到估值、订单兑现和仓位约束，不直接映射交易动作。",
        evidence_snippets=(f"{source_count} 条来源可用，{weak_source_count} 条需降权",),
        stance="证据不足" if source_count == 0 or weak_source_count > source_count else "中性",
        confidence=_bounded_confidence(
            0.25 if source_count == 0 else min(0.55, source_count / max(source_count + weak_source_count, 1))
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


def build_long_term_theme_framework(
    *,
    topic: str,
    symbols: list[str],
    names: dict[str, str],
    financials: list[dict],
    source_count: int,
    weak_source_count: int,
    risk_flags: list[str],
) -> dict[str, object]:
    """Return an evidence-bounded long-term sector checklist, not an analyst vote.

    The deep-research inputs do not currently include sector supply/capacity,
    market-share, peer valuation, inventory or industry-cycle series. Keep those
    dimensions explicitly unknown instead of filling them with generic claims.
    """
    available_financials = [item for item in financials if item.get("available")]
    measured_metrics = sum(
        item.get(field) is not None
        for item in available_financials
        for field in ("revenue_yoy", "net_profit_yoy", "roe", "gross_margin")
    )
    expected_metrics = len(symbols) * 4
    financially_supported = measured_metrics > 0
    names_text = "、".join(_symbol_label(symbol, names) for symbol in symbols) or "未解析"
    def display_metric(value):
        return "未知" if value is None else value
    return {
        "topic": topic,
        "coverage": {
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "display": names_text,
            "financial_rows": len(available_financials),
            "financial_metric_coverage": f"{measured_metrics}/{expected_metrics}" if expected_metrics else "0/0",
            "financial_report_periods": sorted({str(item.get("report_date")) for item in available_financials if item.get("report_date")}),
            "financial_periods_comparable": len(available_financials) == len(symbols) and len({item.get("report_date") for item in available_financials}) == 1 if symbols else False,
        },
        "evidence_status": "partial" if source_count or financially_supported else "insufficient",
        "source_counts": {"usable": source_count, "weak_or_stale": weak_source_count},
        "framework": [
            {
                "dimension": "产业周期",
                "status": "unknown",
                "evidence": [],
                "missing": ["行业收入/产量/利用率与周期位置；当前输入没有行业时间序列"],
                "check": "后续按统一披露日核对行业收入、产量和利用率的连续变化。",
            },
            {
                "dimension": "供需与竞争",
                "status": "unknown",
                "evidence": [],
                "missing": ["供给能力、库存/订单、价格、份额与可比公司；当前输入没有这些横向数据"],
                "check": "建立同口径公司名单后，检验供给扩张、库存和订单兑现是否一致。",
            },
            {
                "dimension": "成分公司财务",
                "status": "partial" if financially_supported else "unknown",
                "evidence": [
                    f"{item['symbol']} 报告期 {item.get('report_date')}：营收同比={display_metric(item.get('revenue_yoy'))}，"
                    f"净利同比={display_metric(item.get('net_profit_yoy'))}，ROE={display_metric(item.get('roe'))}，毛利率={display_metric(item.get('gross_margin'))}"
                    for item in available_financials
                ],
                "missing": (
                    [
                        f"{item['symbol']} 缺少 {','.join(item.get('missing_fields') or [])}"
                        for item in available_financials if item.get("missing_fields")
                    ]
                    + ([f"{symbol} 没有 PIT 可见财务行" for symbol in symbols if symbol not in {item['symbol'] for item in available_financials}])
                ) or ([] if financially_supported else ["覆盖成分股的同一报告期财务指标"]),
                "check": "仅在披露期可比且指标完整时比较增长、盈利质量和现金转化。",
            },
            {
                "dimension": "估值",
                "status": "unknown",
                "evidence": [],
                "missing": ["PE/PB/EV、历史分位和同行估值；当前报告没有估值数据"],
                "check": "补齐同一 as-of 日期的成分股估值与历史分位，再判断预期是否已计价。",
            },
            {
                "dimension": "催化与风险",
                "status": "partial" if source_count or risk_flags else "unknown",
                "evidence": [f"已审核可用来源 {source_count} 条；弱/过期来源 {weak_source_count} 条"] if source_count or weak_source_count else [],
                "missing": ["尚未人工核实可验证的行业级订单/政策催化及其兑现期限；来源数量/文本提及不能证明催化成立"],
                "check": "逐条绑定来源日期和受影响成分股，后续用公告/财报核验兑现或证伪。",
            },
        ],
        "risk_flags": list(risk_flags),
        "limitations": [
            "本框架由现有本地输入生成，不代表 LongTermTeam、Serenity 或独立行业分析师已运行。",
            "未取得板块指数、完整行业成员名册或估值横截面，不能据此给出行业长期看多/看空判断。",
            "文本命中只表示标题/正文出现公司或主题字样，不等于语义审核确认内容支持对应论点。",
        ],
    }
