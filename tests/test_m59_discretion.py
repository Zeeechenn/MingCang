from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.tools import m59_discretion, m63_daily
from backend.tools.m63_render import assert_no_trade_words


class FakeProvider:
    name = "fake-provider"

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.payload is not None:
            return self.payload
        prompt = kwargs["prompt"]
        stance = "持有倾向" if "slot=holding_decision" in prompt else "观望"
        return {
            "stance": stance,
            "timing_note": "等待公告或量能确认",
            "rationale": "price.last_close 与 long_term_label.label 显示证据仍需确认",
            "confidence": "med",
            "reevaluation_trigger": "收盘价重新站上20日均线且公告风险解除",
        }


def _db(path: Path) -> Path:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            CREATE TABLE signals(
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                date TEXT,
                rule_version TEXT
            )
            """
        )
        con.execute(
            "INSERT INTO signals(symbol, date, rule_version) VALUES ('C0', '2026-07-05', 'aggregate_v1:test')"
        )
        con.commit()
    finally:
        con.close()
    return path


def _patch_context(monkeypatch) -> None:
    def fake_context(symbol: str, db_path, as_of: str):
        pack = {
            "symbol": symbol,
            "as_of": as_of,
            "price": {"last_close": 10, "dist_from_20d_ma": 1.2},
            "long_term_label": {"label": "观望", "score": 0.2},
        }
        return pack, "价格 last_close=10; 长期标签 label=观望"

    monkeypatch.setattr(m59_discretion, "_build_context", fake_context)


def _candidate(symbol: str) -> dict:
    return {"symbol": symbol, "rank": symbol, "quality_flags": []}


def _holding(symbol: str, flags: int) -> dict:
    return {
        "symbol": symbol,
        "protective_action": "需要盘后复核" if flags >= 1 else "",
        "stop_flags": [f"stop-{idx}" for idx in range(max(0, flags - 1))],
        "quality_flags": [],
    }


def test_schema_validation_failure_degrades_without_raising(tmp_path, monkeypatch):
    _patch_context(monkeypatch)
    db_path = _db(tmp_path / "m59.sqlite")
    panel = {"buy_candidates": {"items": [_candidate("C0")]}, "position_health": {"items": []}}
    provider = FakeProvider(payload={"stance": "非法", "confidence": "med", "rationale": "x", "reevaluation_trigger": "公告变化"})

    result = m59_discretion.build_discretion_cards(panel, db_path=db_path, as_of="2026-07-05", provider=provider)

    assert result["cards"] == []
    assert result["skipped"] == 1
    assert "裁量层降级" in result["text"]
    assert provider.calls


def test_budget_caps_at_five_candidates_plus_three_flagged_holdings(tmp_path, monkeypatch):
    _patch_context(monkeypatch)
    db_path = _db(tmp_path / "m59.sqlite")
    panel = {
        "buy_candidates": {"items": [_candidate(f"C{idx}") for idx in range(10)]},
        "position_health": {"items": [_holding(f"H{idx}", idx + 1) for idx in range(5)]},
    }
    provider = FakeProvider()

    result = m59_discretion.build_discretion_cards(panel, db_path=db_path, as_of="2026-07-05", provider=provider)

    assert len(provider.calls) == 8
    assert len(result["cards"]) == 8
    assert [card["slot"] for card in result["cards"]].count("candidate_selection") == 5
    assert [card["slot"] for card in result["cards"]].count("holding_decision") == 3
    assert {card["symbol"] for card in result["cards"] if card["slot"] == "holding_decision"} == {"H2", "H3", "H4"}


def test_stance_render_escape_passes_strict_language_guard():
    result = {
        "cards": [
            {
                "symbol": "H1",
                "stance": "清仓倾向",
                "confidence": "low",
                "rationale": "price.last_close 跌破均线且公告风险未解除",
                "timing_note": "等待盘后复核",
                "reevaluation_trigger": "公告风险解除且收盘重新站上均线",
            },
            {
                "symbol": "H2",
                "stance": "减仓倾向",
                "confidence": "med",
                "rationale": "fund_flow.recent5_main_net 连续转弱",
                "timing_note": "",
                "reevaluation_trigger": "主力净流入连续两日转正",
            },
        ],
        "degradations": [],
    }

    text = "\n".join(m59_discretion.render_card_lines(result))

    assert "清仓倾向" not in text
    assert "减仓倾向" not in text
    assert "离场倾向" in text
    assert "降仓倾向" in text
    assert_no_trade_words(text)


def test_card_upsert_is_idempotent(tmp_path, monkeypatch):
    _patch_context(monkeypatch)
    db_path = _db(tmp_path / "m59.sqlite")
    panel = {"buy_candidates": {"items": [_candidate("C0")]}, "position_health": {"items": []}}

    first = m59_discretion.build_discretion_cards(panel, db_path=db_path, as_of="2026-07-05", provider=FakeProvider())
    second = m59_discretion.build_discretion_cards(panel, db_path=db_path, as_of="2026-07-05", provider=FakeProvider())

    with sqlite3.connect(db_path) as con:
        rows = con.execute("SELECT card_json FROM m59_discretion_cards").fetchall()

    assert len(first["cards"]) == 1
    assert len(second["cards"]) == 1
    assert len(rows) == 1
    card = json.loads(rows[0][0])
    assert card["symbol"] == "C0"
    assert card["reference_only"] is True
    assert card["rule_profile_version"] == "aggregate_v1:test"


def test_m59_discretion_disabled_postmarket_has_no_step(tmp_path, monkeypatch):
    monkeypatch.delenv("M59_DISCRETION_ENABLED", raising=False)
    db_path = _db(tmp_path / "m63.sqlite")

    report = m63_daily.build_postmarket_report(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        step_overrides={
            "m61_backfill_drip": lambda: {},
            "m60_watchtower": lambda: {"summary": {"text": "观察哨完成"}, "triggers": []},
            "m60_second_entry": lambda: {},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {}}, "no_divergence_yet": True, "open_position_count": 1},
            "m59_panel": lambda: {"summary": {"text": "面板"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {"queue_path": str(tmp_path / "queue.json"), "history_path": str(tmp_path / "history.json"), "pending": []},
        },
    )

    assert "m59_discretion" not in [step["name"] for step in report["steps"]]
    assert "m59_discretion:OK" not in report["text"]
