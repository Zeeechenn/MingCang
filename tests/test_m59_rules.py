from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _file_db(tmp_path: Path):
    from backend.data.database import Base

    db_path = tmp_path / "m59_rules.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    return db_path, engine, db


def _add_prices(db, symbol: str, *, start_close: float = 100.0, step: float = 0.0, days: int = 21) -> None:
    from backend.data.database import Price

    start = datetime(2026, 6, 15)
    for idx in range(days):
        close = start_close + step * idx
        db.add(
            Price(
                symbol=symbol,
                date=(start + timedelta(days=idx)).date().isoformat(),
                open=close,
                high=close + 5,
                low=close - 5,
                close=close,
                volume=1000,
            )
        )


def _seed_stock(db, symbol: str, name: str = "测试股") -> None:
    from backend.data.database import Stock

    db.add(Stock(symbol=symbol, name=name, market="CN", industry="测试", active=True))


def _write_universe(tmp_path: Path, symbols: list[str]) -> Path:
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps({"stocks": [{"symbol": symbol, "name": f"测试{symbol}"} for symbol in symbols]}),
        encoding="utf-8",
    )
    return path


def test_r1_event_warnings_always_include_protective_action(tmp_path):
    from backend.data.database import CorporateEvent
    from backend.tools.m59_panel import build_panel, render_markdown
    from backend.tools.m63_render import assert_no_trade_words

    db_path, engine, db = _file_db(tmp_path)
    try:
        _seed_stock(db, "600001")
        _seed_stock(db, "600002")
        _add_prices(db, "600001", start_close=100, days=21)
        for symbol in ("600001", "600002"):
            db.add(
                CorporateEvent(
                    symbol=symbol,
                    event_type="解禁",
                    title="限售股解禁",
                    event_date=datetime(2026, 7, 5),
                    detail="测试事件",
                    provider="unit",
                )
            )
        db.commit()

        panel = build_panel(
            db_path=db_path,
            as_of="2026-07-05",
            universe_path=_write_universe(tmp_path, ["600001", "600002"]),
            watchtower_output_dir=tmp_path,
        )
    finally:
        db.close()
        engine.dispose()

    items = {item["symbol"]: item for item in panel["risk_warnings"]["event_warnings"]["items"]}
    assert "止损上移至 85.0" in items["600001"]["protective_action"]
    assert "事件日前评估降仓" in items["600001"]["protective_action"]
    assert_no_trade_words(items["600001"]["protective_action"])
    assert items["600002"]["protective_action"].startswith("数据不足,无法给出动作")
    assert "缺:price,atr14" in items["600002"]["protective_action"]
    assert "→ 动作:" in render_markdown(panel)
    assert panel["summary"]["action_missing_count"] == 1


def test_r3_position_health_flags_tight_stops_and_static_take_profit(tmp_path):
    from backend.data.database import Position
    from backend.tools.m59_panel import build_panel, render_markdown

    db_path, engine, db = _file_db(tmp_path)
    try:
        for symbol, stop_loss, take_profit, step in (
            ("600010", 90.0, None, 0.0),
            ("600011", 80.0, None, 0.0),
            ("600012", 100.0, 150.0, 1.0),
        ):
            _seed_stock(db, symbol)
            _add_prices(db, symbol, start_close=100, step=step, days=21)
            db.add(
                Position(
                    symbol=symbol,
                    name=f"测试{symbol}",
                    quantity=100,
                    avg_cost=90,
                    opened_at="2026-06-01",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    status="open",
                )
            )
        db.commit()

        panel = build_panel(
            db_path=db_path,
            as_of="2026-07-05",
            universe_path=_write_universe(tmp_path, ["600010", "600011", "600012"]),
            watchtower_output_dir=tmp_path,
        )
    finally:
        db.close()
        engine.dispose()

    items = {item["symbol"]: item for item in panel["position_health"]["items"]}
    assert items["600010"]["stop_gap_atr"] == 1.0
    assert "止损贴身(<1.5×ATR,易被正常波动洗出)" in items["600010"]["stop_flags"]
    assert items["600011"]["stop_gap_atr"] == 2.0
    assert not any("止损贴身" in flag for flag in items["600011"]["stop_flags"])
    assert any("ATR追踪" in flag for flag in items["600012"]["stop_flags"])
    assert panel["summary"]["tight_stop_count"] == 1
    assert "止损/ATR" in render_markdown(panel)


def test_r4_quality_flags_reduce_candidate_position_ceiling(tmp_path):
    from backend.data.database import FinancialMetric, Signal
    from backend.tools.m59_panel import build_panel, render_markdown

    db_path, engine, db = _file_db(tmp_path)
    try:
        _seed_stock(db, "600020")
        _add_prices(db, "600020", start_close=100, days=21)
        db.add(
            Signal(
                symbol="600020",
                date="2026-07-05",
                composite_score=80,
                recommendation="买入",
                confidence="高",
                stop_loss=90,
                take_profit=120,
            )
        )
        db.add(
            FinancialMetric(
                symbol="600020",
                report_date="2026-03-31",
                period_type="Q1",
                revenue=100,
                net_profit=10,
                operating_cf=5,
                current_ratio=2,
                gross_margin=30,
            )
        )
        db.add(
            FinancialMetric(
                symbol="600020",
                report_date="2025-03-31",
                period_type="Q1",
                revenue=90,
                net_profit=8,
                operating_cf=12,
                current_ratio=1.5,
                gross_margin=25,
            )
        )
        db.commit()

        panel = build_panel(
            db_path=db_path,
            as_of="2026-07-05",
            universe_path=_write_universe(tmp_path, ["600020"]),
            watchtower_output_dir=tmp_path,
        )
    finally:
        db.close()
        engine.dispose()

    item = panel["buy_candidates"]["items"][0]
    assert "CFO<净利" in item["quality_flags"]
    assert "建议仓位上限减半" in render_markdown(panel)


def test_r2_copilot_prompt_schema_and_degraded_observe_trigger(test_db, monkeypatch):
    from backend.data.database import Signal, Stock
    from backend.research import copilot

    test_db.add(Stock(symbol="600030", name="测试股", market="CN", active=True))
    test_db.add(
        Signal(
            symbol="600030",
            date="2026-07-05",
            composite_score=50,
            recommendation="观望",
            confidence="中",
            stop_loss=90,
            take_profit=120,
        )
    )
    test_db.commit()

    provider = MagicMock()
    provider.complete_structured.return_value = {
        "stance": "中性",
        "event_read": "事件一般。",
        "technical_read": "等待更清晰信号。",
        "risks": ["兑现不足"],
        "validation_questions": ["是否放量？"],
        "summary_opinion": "继续观望。",
        "shadow_position_pct": 0.0,
        "position_note": "等待标签更新。",
    }
    monkeypatch.setattr(copilot, "has_runtime_llm_provider", lambda settings: True)
    monkeypatch.setattr(copilot, "get_provider", lambda: provider)

    card = copilot.generate_symbol_copilot("600030", test_db)

    assert "可独立观测的触发条件" in copilot._SYSTEM_PROMPT
    assert "1.5×ATR14" in copilot._SYSTEM_PROMPT
    assert "CFO<净利" in copilot._SYSTEM_PROMPT
    assert "reentry_trigger" in copilot._COPILOT_TOOL["input_schema"]["properties"]
    assert card["trigger_quality"] == "degraded"


def test_r2_m59_panel_surfaces_degraded_copilot_trigger_quality(tmp_path):
    from backend.data.database import ResearchState, Signal
    from backend.tools.m59_panel import build_panel, render_markdown

    db_path, engine, db = _file_db(tmp_path)
    try:
        _seed_stock(db, "600031")
        _add_prices(db, "600031", start_close=100, days=21)
        db.add(
            Signal(
                symbol="600031",
                date="2026-07-05",
                composite_score=80,
                recommendation="买入",
                confidence="中",
                stop_loss=90,
                take_profit=120,
            )
        )
        db.add(
            ResearchState(
                symbol="600031",
                risks_json="[]",
                open_questions_json="[]",
                copilot_json=json.dumps(
                    {
                        "stance": "观望",
                        "summary_opinion": "继续观察。",
                        "reentry_trigger": "等待更清晰信号",
                        "trigger_quality": "degraded",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

        panel = build_panel(
            db_path=db_path,
            as_of="2026-07-05",
            universe_path=_write_universe(tmp_path, ["600031"]),
            watchtower_output_dir=tmp_path,
        )
    finally:
        db.close()
        engine.dispose()

    item = panel["buy_candidates"]["items"][0]
    assert item["research_reference"]["copilot"]["trigger_quality"] == "degraded"
    assert "⚠️ 触发条件质量降级(需人工补可观测触发)" in render_markdown(panel)
