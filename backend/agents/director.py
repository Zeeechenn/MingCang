"""[M63 现役] [active] 消费者: backend/agents/pipeline.py, backend/decision/aggregator.py.
M4.2 Research Director Agent —— 协调层。

职责：
  1. 评估 4 路分析师报告的质量
     • 数据完整性：每路是否有 key_findings
     • 平均置信度：低于 director_min_confidence 时打"数据不足"标记
     • 分歧度：分数标准差（用于决定是否触发多轮辩论）
  2. 当分歧达标时，向研究员团下达"辩论议题"（debate_topic）
     —— 即"哪两个信号在打架，需要重点辩证"
  3. 输出 DirectorAssessment，供 pipeline 决定后续流程

设计目标：纯规则、零 LLM。议题生成基于 reports 内部结构，避免额外成本。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from backend.agents.analyst import AnalystReport
from backend.config import settings


@dataclass
class DirectorAssessment:
    quality_ok: bool                    # 报告整体可用
    avg_confidence: float
    score_stdev: float
    diverged: bool                      # 是否达到辩论阈值
    debate_topic: str                   # 给研究员的议题（空字符串 = 自由开场）
    quality_notes: list[str] = field(default_factory=list)
    weak_roles: list[str] = field(default_factory=list)   # 数据缺失/低置信的角色


def _role_label(role: str) -> str:
    """中文角色名（用于 debate_topic 可读性）"""
    return {
        "technical": "技术",
        "quant": "量化",
        "sentiment": "情感",
        "news": "新闻",
    }.get(role, role)


def assess(reports: list[AnalystReport]) -> DirectorAssessment:
    """
    评估分析师报告并生成 DirectorAssessment。

    议题生成规则：
      • 找出分数最高和最低的两个角色（min/max）
      • 若 |max - min| >= multi_round_debate_min_divergence，议题 = "{max_role} vs {min_role}"
      • 否则议题留空（让研究员自由开场或快速达成共识）
    """
    if not reports:
        return DirectorAssessment(
            quality_ok=False,
            avg_confidence=0.0,
            score_stdev=0.0,
            diverged=False,
            debate_topic="",
            quality_notes=["无分析师报告"],
            weak_roles=[],
        )

    avg_conf = sum(r.confidence for r in reports) / len(reports)
    scores = [r.score for r in reports]
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0

    notes: list[str] = []
    weak_roles: list[str] = []

    # 1. 数据完整性 & 置信度
    for r in reports:
        if not r.key_findings:
            weak_roles.append(r.role)
            notes.append(f"{_role_label(r.role)} 缺失关键发现")
        elif r.confidence < settings.director_min_confidence:
            weak_roles.append(r.role)
            notes.append(f"{_role_label(r.role)} 置信度低 ({r.confidence:.2f})")

    # 2. 整体置信度门槛
    if avg_conf < settings.director_min_confidence:
        notes.append(f"平均置信度 {avg_conf:.2f} 偏低，建议谨慎对待结论")

    # 严格多数良好才算 ok：good*2 > n（n=4 时允许 1 个 weak）
    quality_ok = (len(reports) - len(weak_roles)) * 2 > len(reports)

    # 3. 议题生成
    diverged = stdev >= settings.multi_round_debate_min_divergence
    topic = ""
    if diverged and len(reports) >= 2:
        max_r = max(reports, key=lambda r: r.score)
        min_r = min(reports, key=lambda r: r.score)
        topic = (
            f"{_role_label(max_r.role)}信号 {max_r.score:+.0f} 与 "
            f"{_role_label(min_r.role)}信号 {min_r.score:+.0f} 出现重大分歧，"
            f"请论证哪一方在当前市场环境下更可信"
        )

    return DirectorAssessment(
        quality_ok=quality_ok,
        avg_confidence=round(avg_conf, 3),
        score_stdev=round(stdev, 2),
        diverged=diverged,
        debate_topic=topic,
        quality_notes=notes,
        weak_roles=weak_roles,
    )


def assessment_to_dict(assessment: DirectorAssessment) -> dict:
    """序列化 DirectorAssessment（写入 Signal/audit_log 用）"""
    return {
        "quality_ok": assessment.quality_ok,
        "avg_confidence": assessment.avg_confidence,
        "score_stdev": assessment.score_stdev,
        "diverged": assessment.diverged,
        "debate_topic": assessment.debate_topic,
        "quality_notes": assessment.quality_notes,
        "weak_roles": assessment.weak_roles,
    }
