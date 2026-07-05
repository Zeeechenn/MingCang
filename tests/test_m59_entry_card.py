from __future__ import annotations

import json
import sqlite3


def _init_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
        """
    )
    return con


def _insert_prices(con, symbol: str, closes: list[float], volumes: list[float] | None = None) -> None:
    for idx, close in enumerate(closes, start=1):
        volume = volumes[idx - 1] if volumes is not None else 100000.0
        con.execute(
            """
            INSERT INTO prices(symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, f"2026-01-{idx:02d}", close, close + 1.0, close - 1.0, close, volume),
        )


def test_entry_card_calculates_three_rules_and_sizing(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.tools.m59_entry_card import build_entry_card

    old_size = settings.entry_account_size
    old_budget = settings.entry_risk_budget_pct
    old_max = settings.max_position_per_stock
    monkeypatch.setattr(settings, "entry_account_size", 100000.0)
    monkeypatch.setattr(settings, "entry_risk_budget_pct", 1.5)
    monkeypatch.setattr(settings, "max_position_per_stock", 0.15)
    try:
        db_path = tmp_path / "entry.sqlite"
        with _init_db(db_path) as con:
            _insert_prices(con, "600001", [100.0 + i for i in range(15)], volumes=[100000, 200000, 300000, 400000, 500000] * 3)
            card = build_entry_card("600001", "2026-01-15", con)
    finally:
        monkeypatch.setattr(settings, "entry_account_size", old_size)
        monkeypatch.setattr(settings, "entry_risk_budget_pct", old_budget)
        monkeypatch.setattr(settings, "max_position_per_stock", old_max)

    assert card["status"] == "ok"
    assert card["price_date"] == "2026-01-15"
    assert card["atr14"] == 2.0
    assert card["variants"][0]["trigger_price"] == 114.0
    assert card["variants"][0]["stop_price"] == 111.0
    assert card["variants"][1]["trigger_price"] == 112.0
    assert card["variants"][1]["stop_price"] == 109.0
    assert card["variants"][2]["volume_threshold"] == 450000.0
    assert card["variants"][2]["volume_threshold_display"] == "45.00万"
    assert card["variants"][2]["stand_above_price"] == 115.0
    assert card["variants"][0]["sizing"]["reference_shares"] == 500
    assert card["variants"][0]["sizing"]["reference_amount"] == 57000.0
    assert card["variants"][0]["sizing"]["position_limit_hint"] is not None


def test_entry_card_degrades_when_atr_missing(tmp_path):
    from backend.tools.m59_entry_card import build_entry_card

    db_path = tmp_path / "entry-missing.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "600001", [100.0 + i for i in range(5)])
        card = build_entry_card("600001", "2026-01-05", con)

    assert card == {
        "symbol": "600001",
        "as_of": "2026-01-05",
        "status": "missing_data",
        "message": "数据缺失,无法算条件卡",
        "missing": ["atr14"],
    }


def test_entry_card_sizing_formula_without_account_amount(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.tools.m59_entry_card import build_entry_card

    old_size = settings.entry_account_size
    old_budget = settings.entry_risk_budget_pct
    monkeypatch.setattr(settings, "entry_account_size", None)
    monkeypatch.setattr(settings, "entry_risk_budget_pct", 1.5)
    try:
        db_path = tmp_path / "entry-formula.sqlite"
        with _init_db(db_path) as con:
            _insert_prices(con, "600001", [100.0 + i for i in range(15)])
            card = build_entry_card("600001", "2026-01-15", con)
    finally:
        monkeypatch.setattr(settings, "entry_account_size", old_size)
        monkeypatch.setattr(settings, "entry_risk_budget_pct", old_budget)

    sizing = card["variants"][0]["sizing"]
    assert sizing["account_size"] is None
    assert sizing["formula"] == "资金×0.015/3.00(向下取百股)"
    assert sizing["reference_shares"] is None


def test_entry_card_marks_ledger_winner_only_after_sample_gate(tmp_path):
    from backend.tools.m59_entry_card import build_entry_card

    ledger_path = tmp_path / "second_entry_ledger.json"
    entries = []
    for idx in range(20):
        for variant in ("v1_immediate", "v2_pullback", "v3_confirm"):
            entries.append({"symbol": f"S{idx:02d}", "trigger_date": "2026-01-01", "variant": variant})
    ledger_path.write_text(
        json.dumps({"entries": entries, "summary": {"winning_variant": "v2_pullback"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    db_path = tmp_path / "entry-ledger.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "600001", [100.0 + i for i in range(15)])
        card = build_entry_card("600001", "2026-01-15", con, ledger_path=ledger_path)

    assert card["ledger"]["sample_count"] == 20
    assert card["ledger"]["recommended_variant"] == "v2_pullback"
    notes = {variant["variant"]: variant["validation_note"] for variant in card["variants"]}
    assert notes["v2_pullback"].startswith("影子验证中,样本满20后推荐")
    assert notes["v1_immediate"] == "影子验证中"


def test_entry_card_render_passes_strict_language_guard(tmp_path):
    from backend.tools.m59_entry_card import build_entry_card, render_entry_card_compact
    from backend.tools.m63_render import assert_no_trade_words

    db_path = tmp_path / "entry-guard.sqlite"
    with _init_db(db_path) as con:
        _insert_prices(con, "600001", [100.0 + i for i in range(15)])
        card = build_entry_card("600001", "2026-01-15", con)

    text = "\n".join(render_entry_card_compact(card))
    assert_no_trade_words(text)
