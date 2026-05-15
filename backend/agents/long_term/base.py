"""长期分析师团共享数据结构"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal

VoteLabel = Literal["值得持有", "估值偏高", "观望", "规避"]


@dataclass
class LongTermReport:
    """单个长期分析师的报告（与短期 AnalystReport 同型，多 horizon 字段）"""
    role: str                  # "track" / "quality" / "boom"
    score: float               # -100 ~ +100
    confidence: float          # 0 ~ 1
    label_vote: VoteLabel      # 该分析师的标签投票
    key_findings: list[str]    # ≤3 条
    raw: dict = field(default_factory=dict)
    horizon: str = "long"

    def to_dict(self) -> dict:
        """Serialize report to dictionary."""
        return asdict(self)


@dataclass
class LongTermLabel:
    """长期团聚合后的最终标签（存 DB）"""
    symbol: str
    date: str                  # 生成日 "2026-05-17"
    label: VoteLabel
    score: float
    votes: dict[str, str]      # {role: vote}
    key_findings: list[str]    # 合并后 ≤6 条
    expires_at: str            # "2026-05-27"

    def to_dict(self) -> dict:
        """Serialize label to dictionary."""
        return {
            "symbol": self.symbol,
            "date": self.date,
            "label": self.label,
            "score": self.score,
            "votes": self.votes,
            "key_findings": self.key_findings,
            "expires_at": self.expires_at,
        }
