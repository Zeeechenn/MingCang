"""Daily trade review report built from existing StockSage evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.config import BASE_DIR
from backend.data.database import DecisionRun, NewsItem, Signal, Stock
from backend.skills.vetter import VetterReview, vet_skill_output
from backend.skills.watcher import WatchEvent, scan_watch_events


@dataclass(frozen=True)
class DailyReview:
    """Result of a daily trade review run."""

    skill_name: str
    as_of: str
    summary: str
    path: Path | None
    signal_count: int
    watch_events: list[WatchEvent]
    vetter: VetterReview

    def to_dict(self) -> dict:
        """Serialize the review for API responses."""
        return {
            "skill_name": self.skill_name,
            "as_of": self.as_of,
            "summary": self.summary,
            "path": str(self.path) if self.path else None,
            "signal_count": self.signal_count,
            "watch_events": [event.to_dict() for event in self.watch_events],
            "vetter": self.vetter.to_dict(),
        }


def default_output_dir() -> Path:
    """Return the default daily review directory."""
    return BASE_DIR / "docs" / "reviews"


def _stock_names(db) -> dict[str, str]:
    return {row.symbol: row.name for row in db.query(Stock).all()}


def _news_count(db, symbol: str, day: str) -> int:
    start = datetime.strptime(day, "%Y-%m-%d")
    end = start.replace(hour=23, minute=59, second=59)
    return (
        db.query(NewsItem)
        .filter(NewsItem.symbol == symbol, NewsItem.published_at >= start, NewsItem.published_at <= end)
        .count()
    )


def _risk_notes(db, symbol: str, day: str) -> list[str]:
    import json

    row = (
        db.query(DecisionRun)
        .filter(DecisionRun.symbol == symbol, DecisionRun.as_of == day)
        .order_by(DecisionRun.created_at.desc())
        .first()
    )
    if not row or not row.risk_decision_json:
        return []
    try:
        data = json.loads(row.risk_decision_json)
    except Exception:
        return []
    return data.get("risk_notes", []) or []


def _render_report(
    *,
    day: str,
    signals: list[Signal],
    names: dict[str, str],
    watch_events: list[WatchEvent],
    vetter: VetterReview,
    db,
) -> str:
    lines = [
        f"# StockSage 每日复盘 — {day}",
        "",
        "## 摘要",
        f"- 当日信号：{len(signals)} 条",
        f"- 异动监控：{len(watch_events)} 条",
        f"- 安全审计：{vetter.status}",
        "",
        "## 当日信号",
    ]
    if signals:
        lines.append("| 股票 | 综合分 | 建议 | 置信度 | 技术 | 情感 | 新闻 | 风险 |")
        lines.append("|---|---:|---|---|---:|---:|---:|---|")
        for sig in signals:
            risks = "；".join(_risk_notes(db, sig.symbol, day)) or "-"
            lines.append(
                f"| {sig.symbol} {names.get(sig.symbol, '')} | {sig.composite_score:.1f} | "
                f"{sig.recommendation} | {sig.confidence} | "
                f"{(sig.technical_score or 0):.1f} | {(sig.sentiment_score or 0):.1f} | "
                f"{_news_count(db, sig.symbol, day)} | {risks} |"
            )
    else:
        lines.append("- 今日没有信号。")

    lines.extend(["", "## 异动监控"])
    if watch_events:
        for event in watch_events:
            lines.append(f"- [{event.severity}] {event.event_type}: {event.message}")
    else:
        lines.append("- 未触发异动条件。")

    lines.extend(["", "## 安全审计"])
    lines.append(f"- 状态：{vetter.status}")
    if vetter.risk_flags:
        lines.append(f"- 风险标记：{', '.join(vetter.risk_flags)}")
    if vetter.blocked_actions:
        lines.append(f"- 阻断动作：{', '.join(vetter.blocked_actions)}")

    lines.extend([
        "",
        "## 免责声明",
        "本复盘用于记录和辅助决策，不构成投资建议，不自动触发交易。",
        "",
    ])
    return "\n".join(lines)


def build_daily_review(
    db,
    *,
    as_of: str | None = None,
    output_dir: Path | str | None = None,
    persist: bool = True,
) -> DailyReview:
    """Build and optionally persist a deterministic daily review report."""
    day = as_of or datetime.utcnow().strftime("%Y-%m-%d")
    signals = (
        db.query(Signal)
        .filter(Signal.date == day)
        .order_by(Signal.composite_score.desc())
        .all()
    )
    names = _stock_names(db)
    watch_events = scan_watch_events(db, as_of=day)
    evidence = [f"signal:{sig.symbol}:{sig.date}" for sig in signals]
    evidence.extend(f"watch:{event.symbol}:{event.event_type}" for event in watch_events)
    summary = f"{day} 生成 {len(signals)} 条信号，触发 {len(watch_events)} 条异动监控。"
    vetter = vet_skill_output({
        "skill_name": "Daily-Trade-Review",
        "result": {"summary": summary},
        "evidence": evidence,
        "allowed_actions": ["review_only"],
    })

    path = None
    if persist:
        out_dir = Path(output_dir) if output_dir is not None else default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{day}.md"
        text = _render_report(
            day=day,
            signals=signals,
            names=names,
            watch_events=watch_events,
            vetter=vetter,
            db=db,
        )
        path.write_text(text, encoding="utf-8")

    return DailyReview(
        skill_name="Daily-Trade-Review",
        as_of=day,
        summary=summary,
        path=path,
        signal_count=len(signals),
        watch_events=watch_events,
        vetter=vetter,
    )

