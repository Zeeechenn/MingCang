"""
A 老师赛道分析师（LLM 主导，五层框架）

参考 .pi/skills/a-teacher/SKILL.md（fallback：~/.claude/skills/a-teacher/SKILL.md）的方法论：
  1. 供应链数据核查
  2. 海外领先指标
  3. 周期 vs 结构性
  4. 炒作过滤
  5. 高位过滤（入场时机）

数据获取：
  • Stock.industry（来自 sync_industry）
  • 近 30/90/180 日涨幅（来自 prices 表）
  • Tavily 检索近 14 天供应链/海外关键词

LLM 调用：
  • model_tier="capable"（Sonnet）保证质量
  • complete_structured 强制 tool schema 输出
  • 失败兜底 score=0, vote="观望", confidence=0
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from backend.agents.long_term.base import LongTermReport
from backend.config import settings
from backend.data.database import Price, Stock
from backend.llm import get_provider

logger = logging.getLogger(__name__)

# 优先级：项目内 .pi/skills/a-teacher/SKILL.md > 用户全局 ~/.claude/skills/...> _FALLBACK_SYSTEM
# 项目内版本随 git 同步到 GitHub，避免在其他机器/服务器上退化到精简兜底版
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_MD_CANDIDATES = (
    _PROJECT_ROOT / ".pi" / "skills" / "a-teacher" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "a-teacher" / "SKILL.md",
)

# 兜底用的精简 system prompt（SKILL.md 不可达时用）
_FALLBACK_SYSTEM = """你是 A老师（小红书 @A也叫艾利克斯）风格的研究员，对 A 股科技/硬件赛道做研究级判断。
方法论五层：
1. 供应链数据核查 — 锁单/排产、原材料涨价、交期、产品单价上涨（要量化数据，不接受叙事）
2. 海外领先指标 — Lumentum/Coherent/Corning 订单 backlog、NV/Google 战略投资、需求上修
3. 周期 vs 结构性 — 库存周期回升 vs 新应用永久增量；产品代际跨越是结构性
4. 炒作过滤 — 国内无实际订单的概念、算力租赁情绪标的、只有需求叙事
5. 高位过滤 — 6 个月涨幅 >50% 需高确定性；估值消化超 3 年警示

约束：
- 不接受没有数据支撑的方向性判断
- 即使方向正确，若估值透支，结论必须是"观望/等回调"
- 必须呈现反例（与多头叙事矛盾的数据）
"""

_A_TEACHER_TOOL = {
    "name": "a_teacher_assessment",
    "description": "对单一标的/赛道的五层结构研究级判断",
    "input_schema": {
        "type": "object",
        "properties": {
            "layer1_supply_chain": {
                "type": "string",
                "description": "供应链数据评估。必须含至少一个具体数字（锁单天数/涨幅%/交期周数），找不到则写'未找到可量化证据'",
            },
            "layer2_overseas": {
                "type": "string",
                "description": "海外领先指标（Lumentum/Corning/NV 等订单/投资/上修）",
            },
            "layer3_cycle_or_structural": {
                "type": "string",
                "enum": ["周期", "结构性", "混合", "无法判断"],
            },
            "layer4_speculation_risk": {
                "type": "string",
                "description": "炒作风险点；无明显炒作则写'未发现明显炒作特征'",
            },
            "layer5_entry_timing": {
                "type": "string",
                "enum": ["可建仓", "等回调", "观望", "规避"],
            },
            "score": {
                "type": "integer",
                "minimum": -100,
                "maximum": 100,
                "description": "综合分：方向 + 估值 + 时机",
            },
            "label_vote": {
                "type": "string",
                "enum": ["值得持有", "估值偏高", "观望", "规避"],
            },
            "key_findings": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "≤3 条最关键的发现，给用户看",
            },
        },
        "required": [
            "layer3_cycle_or_structural", "layer5_entry_timing",
            "score", "label_vote", "key_findings",
        ],
    },
}


def _load_skill_system_prompt() -> str:
    """按候选路径优先级读 SKILL.md 作 system prompt，全部失败时用兜底"""
    for path in SKILL_MD_CANDIDATES:
        try:
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                # 剥离 YAML frontmatter（避免 `---` 开头让 CLI argparser 把整段当 option）
                if raw.startswith("---"):
                    end = raw.find("\n---", 3)
                    if end != -1:
                        raw = raw[end + 4:].lstrip()
                logger.debug("a_teacher SKILL.md loaded from %s", path)
                return raw
        except Exception as e:
            logger.warning("读取 SKILL.md 失败 %s: %s", path, e)
    return _FALLBACK_SYSTEM


def _compute_price_moves(symbol: str, db) -> dict:
    """近 30/90/180 日累计涨幅（高位过滤数据）"""
    rows = (db.query(Price.date, Price.close)
              .filter(Price.symbol == symbol)
              .order_by(Price.date.desc()).limit(200).all())
    if len(rows) < 30:
        return {}
    closes = [r[1] for r in rows]
    cur = closes[0]

    def _move(n) -> float | None:
        """Calculate price move percentage over n bars."""
        if len(closes) <= n:
            return None
        prev = closes[n]
        if prev <= 0:
            return None
        return round((cur / prev - 1) * 100, 1)

    return {
        "current_close": cur,
        "move_30d": _move(20),    # 20 个交易日 ≈ 30 自然日
        "move_90d": _move(60),
        "move_180d": _move(120),
    }


def _fetch_supply_chain_evidence(industry: str, name: str) -> list[str]:
    """用 Tavily 拉近 14 天供应链/海外关键词，失败返回空"""
    try:
        from backend.data.news import fetch_titles_tavily
    except ImportError:
        return []

    if not settings.tavily_api_key:
        return []

    queries = [
        f"{industry} 锁单 OR 排产 OR 涨价 2026",
        f"{name} 海外订单 OR Lumentum OR Corning OR Nvidia",
    ]
    titles: list[str] = []
    for q in queries:
        try:
            t = fetch_titles_tavily(q, name, days=14)
            if t:
                titles.extend(t[:5])
        except Exception as e:
            logger.debug("Tavily 检索失败 %s: %s", q, e)
    return titles[:10]


def _build_prompt(symbol: str, name: str, industry: str | None,
                  moves: dict, evidence: list[str]) -> str:
    """Build the user prompt for A-teacher five-layer analysis."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    move_txt = ""
    if moves:
        cur = moves.get("current_close")
        m30 = moves.get("move_30d")
        m90 = moves.get("move_90d")
        m180 = moves.get("move_180d")
        move_txt = (f"\n\n价格走势（今天 {today}，当前收盘 {cur}）：\n"
                    f"- 近 30 日：{m30:+.1f}%（若有数据）\n" if m30 is not None else "")
        if m90 is not None:
            move_txt += f"- 近 90 日：{m90:+.1f}%\n"
        if m180 is not None:
            move_txt += f"- 近 180 日：{m180:+.1f}%\n"
        if m180 is not None and m180 > 50:
            move_txt += "⚠️ 涨幅已超 50%，第五层高位过滤需特别警觉\n"

    evidence_txt = ""
    if evidence:
        evidence_txt = "\n\n近 14 天供应链/海外检索结果：\n" + "\n".join(
            f"- {t}" for t in evidence[:8]
        )

    industry_txt = f"行业：{industry}" if industry else "行业：未知（请基于公司名推断）"
    return (
        f"请对以下标的做 A 老师五层框架研究：\n"
        f"代码：{symbol}\n"
        f"名称：{name}\n"
        f"{industry_txt}"
        f"{move_txt}"
        f"{evidence_txt}\n\n"
        f"输出 JSON 必须含 layer1-5 + score(-100~+100) + label_vote + key_findings(≤3条)。"
    )


def analyze(symbol: str, name: str, db) -> LongTermReport:
    """主入口"""
    if not settings.long_term_a_teacher_enabled:
        return LongTermReport(
            role="track", score=0, confidence=0,
            label_vote="观望", key_findings=["A 老师分析师已禁用"],
        )

    # 取行业 + 价格走势
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    industry = stock.industry if stock else None
    moves = _compute_price_moves(symbol, db)
    evidence = _fetch_supply_chain_evidence(industry or "", name) if industry else []

    system = _load_skill_system_prompt()
    prompt = _build_prompt(symbol, name, industry, moves, evidence)

    try:
        data = get_provider().complete_structured(
            prompt=prompt,
            tool=_A_TEACHER_TOOL,
            system=system,
            max_tokens=600,
            model_tier="capable",
        )
    except Exception as e:
        logger.warning("a_teacher LLM 调用失败 %s: %s", symbol, e)
        data = {}

    if not data:
        # 失败兜底
        return LongTermReport(
            role="track", score=0, confidence=0,
            label_vote="观望",
            key_findings=["LLM 调用失败，默认观望"],
            raw={"industry": industry, "moves": moves, "evidence_count": len(evidence)},
        )

    score = float(data.get("score", 0))
    label_vote = data.get("label_vote", "观望")
    findings = (data.get("key_findings") or [])[:3]
    if not findings:
        findings = [f"第三层: {data.get('layer3_cycle_or_structural', 'N/A')}",
                    f"第五层: {data.get('layer5_entry_timing', 'N/A')}"]

    # 高位强制降级：如 180 日 > 50% 且 LLM 投"值得持有"，降为"估值偏高"
    if moves.get("move_180d") is not None and moves["move_180d"] > 50 \
            and label_vote == "值得持有":
        logger.info("a_teacher %s: 180日涨幅 %.1f%% > 50%%，强制降级值得持有→估值偏高",
                    symbol, moves["move_180d"])
        label_vote = "估值偏高"

    confidence = min(1.0, abs(score) / 60)
    logger.info("a_teacher %s: score=%.0f → %s", symbol, score, label_vote)

    return LongTermReport(
        role="track",
        score=score,
        confidence=round(confidence, 2),
        label_vote=label_vote,
        key_findings=findings,
        raw={
            "industry": industry,
            "moves": moves,
            "evidence_count": len(evidence),
            "layers": {k: data.get(k) for k in (
                "layer1_supply_chain", "layer2_overseas",
                "layer3_cycle_or_structural", "layer4_speculation_risk",
                "layer5_entry_timing",
            )},
        },
    )
