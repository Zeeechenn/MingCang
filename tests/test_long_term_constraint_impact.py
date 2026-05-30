"""Read-only long-term linkage impact report tests."""
from __future__ import annotations

from backend.data.database import LongTermLabel, Signal, Stock
from backend.tools.long_term_constraint_impact import (
    build_impact_report,
    report_to_json,
    report_to_markdown,
)


def _add_stock(db, symbol: str, name: str) -> None:
    db.add(Stock(symbol=symbol, name=name, market="CN", active=True))


def _add_signal(
    db,
    symbol: str,
    *,
    recommendation: str = "可小仓试错",
    score: float = 66.0,
    confidence: str = "中",
) -> None:
    db.add(
        Signal(
            symbol=symbol,
            date="2026-05-27T16:10+08:00",
            quant_score=0.0,
            technical_score=80.0,
            sentiment_score=0.5,
            composite_score=score,
            recommendation=recommendation,
            confidence=confidence,
        )
    )


def _add_label(
    db,
    symbol: str,
    *,
    label: str,
    quality: str = "trusted",
    eligible: bool = True,
) -> None:
    db.add(
        LongTermLabel(
            symbol=symbol,
            date="2026-05-27",
            label=label,
            score=-50.0 if label == "规避" else 30.0,
            votes_json='{"track": "test"}',
            key_findings_json='["测试长期标签"]',
            expires_at="2099-01-01",
            quality=quality,
            constraint_eligible=eligible,
            quality_notes_json='["test"]',
        )
    )


def test_long_term_constraint_impact_report_is_read_only_and_compares_modes(
    test_db,
    monkeypatch,
):
    from backend.config import settings

    monkeypatch.setattr(settings, "long_term_team_enabled", True)
    monkeypatch.setattr(settings, "long_term_constraints_enabled", False)
    symbols = ["300001", "300002", "300003", "300004", "300005"]
    for symbol in symbols:
        _add_stock(test_db, symbol, f"测试{symbol}")
    _add_signal(test_db, "300001")
    _add_signal(test_db, "300002")
    _add_signal(test_db, "300003")
    _add_signal(test_db, "300004")
    _add_label(test_db, "300001", label="规避")
    _add_label(test_db, "300002", label="估值偏高")
    _add_label(test_db, "300003", label="规避", quality="degraded", eligible=False)
    _add_label(test_db, "300005", label="规避")
    test_db.commit()

    before = (
        test_db.query(Signal).count(),
        test_db.query(LongTermLabel).count(),
    )
    report = build_impact_report(test_db, symbols=",".join(symbols))
    after = (
        test_db.query(Signal).count(),
        test_db.query(LongTermLabel).count(),
    )

    assert before == after
    assert settings.long_term_constraints_enabled is False
    assert report.summary["total"] == 5
    assert report.summary["changed_if_enforced"] == 2
    assert report.summary["blocked_entries"] == 1
    assert report.summary["reduced_positions"] == 1
    assert report.summary["missing_signal"] == 1
    assert report.summary["missing_label"] == 1

    by_symbol = {row.symbol: row for row in report.rows}
    avoid = by_symbol["300001"]
    assert avoid.shadow_recommendation == "可小仓试错"
    assert avoid.shadow_position_pct and avoid.shadow_position_pct > 0.0
    assert any("验证模式" in note for note in avoid.shadow_notes)
    assert avoid.enforced_recommendation == "观望"
    assert avoid.enforced_position_pct == 0.0
    assert avoid.impact_type == "blocked_entry"

    overvalued = by_symbol["300002"]
    assert overvalued.impact_type == "position_reduced"
    assert overvalued.enforced_position_pct < overvalued.estimated_base_position_pct

    ineligible = by_symbol["300003"]
    assert ineligible.impact_type == "ineligible_label"
    assert ineligible.enforced_recommendation == "可小仓试错"

    missing_label = by_symbol["300004"]
    assert missing_label.impact_type == "missing_label"
    assert missing_label.changed is False

    missing_signal = by_symbol["300005"]
    assert missing_signal.impact_type == "missing_signal"


def test_long_term_constraint_impact_report_serializes_markdown_and_json(
    test_db,
    monkeypatch,
):
    from backend.config import settings

    monkeypatch.setattr(settings, "long_term_team_enabled", True)
    monkeypatch.setattr(settings, "long_term_constraints_enabled", False)
    _add_stock(test_db, "300001", "测试300001")
    _add_signal(test_db, "300001")
    _add_label(test_db, "300001", label="规避")
    test_db.commit()

    report = build_impact_report(test_db, symbols="300001")
    markdown = report_to_markdown(report)
    json_text = report_to_json(report)

    assert "长期标签联动只读影响报告" in markdown
    assert "不是收益回测" in markdown
    assert "blocked_entry" in markdown
    assert '"changed_if_enforced": 1' in json_text
    assert '"impact_type": "blocked_entry"' in json_text
