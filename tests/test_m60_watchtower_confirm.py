from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _no_real_usage_log(monkeypatch):
    """Keep unit tests from writing llm_usage_log rows into the real MingCang DB."""
    import backend.ops.llm_usage as llm_usage

    monkeypatch.setattr(llm_usage, "log_llm_usage", lambda *args, **kwargs: None)


def _mock_provider(payload: dict) -> MagicMock:
    provider = MagicMock()
    provider.complete_structured.return_value = payload
    return provider


def _valid_llm_payload(**overrides) -> dict:
    payload = {
        "stance": "跟进关注",
        "reasoning": "板块共振叠加公司公告,主因判断为公司事件驱动。",
        "risks": ["追高风险", "板块整体回调风险"],
        "validation_question": "后续两日板块共振是否维持,单股是否伴随放量?",
        "thesis_status": "论点仍成立",
    }
    payload.update(overrides)
    return payload


def _write_watchlist(tmp_path, entry, filename="theme.json"):
    watchlist_dir = tmp_path / "watchlists"
    watchlist_dir.mkdir(exist_ok=True)
    (watchlist_dir / filename).write_text(json.dumps(entry), encoding="utf-8")
    return watchlist_dir


def _innovative_drug_entry(symbols):
    return {
        "theme_key": "innovative_drug",
        "title": "创新药",
        "thesis": "owner 前期板块研究,细节待 owner 补充",
        "symbols": symbols,
        "validation_conditions": ["清单内成员被 M60 观察哨触发"],
        "invalidation_conditions": ["owner 前期板块研究判断被证伪"],
        "created_at": "2026-07-03",
        "source_ref": "pending",
    }


def _init_minimal_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE long_term_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            label TEXT,
            score REAL,
            expires_at TEXT,
            quality TEXT,
            created_at DATETIME
        );
        CREATE TABLE stock_memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            memory_type TEXT,
            summary TEXT NOT NULL,
            created_at DATETIME,
            updated_at DATETIME
        );
        """
    )
    con.commit()
    con.close()


def _one_trigger(symbol, trigger_type="price_z_anomaly", value=2.7, themes=("innovative_drug",)):
    return {
        "symbol": symbol,
        "themes": list(themes),
        "trigger_type": trigger_type,
        "value": value,
        "detail": {"daily_return_pct": 8.2, "z_score": value},
        "price": {"date": "2026-07-03", "close": 100.0},
    }


# ── confirm_symbol: schema + degrade paths ──────────────────────────────────


def test_confirm_symbol_degrades_when_no_provider():
    from backend.research.watchtower_confirm import (
        FLAG_NO_PROVIDER,
        STANCE_INSUFFICIENT,
        THESIS_UNKNOWN,
        confirm_symbol,
    )

    card = confirm_symbol(
        symbol="603259",
        themes=["innovative_drug"],
        symbol_triggers=[_one_trigger("603259")],
        watchlist_entries=[_innovative_drug_entry(["603259"])],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=False,
    )

    assert card["stance"] == STANCE_INSUFFICIENT
    assert card["thesis_status"] == THESIS_UNKNOWN
    assert card["used_llm"] is False
    assert card["flags"] == [FLAG_NO_PROVIDER]
    assert card["disclaimer"] == "跟进关注≠买入建议"


def test_confirm_symbol_degrades_when_no_watchlist_entry(monkeypatch):
    from backend.research import watchtower_confirm as wc

    provider = _mock_provider(_valid_llm_payload())
    monkeypatch.setattr(wc, "get_provider", lambda: provider)

    card = wc.confirm_symbol(
        symbol="999999",
        themes=[],
        symbol_triggers=[_one_trigger("999999", themes=())],
        watchlist_entries=[],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=True,
    )

    assert card["stance"] == wc.STANCE_INSUFFICIENT
    assert card["flags"] == [wc.FLAG_NO_WATCHLIST_ENTRY]
    assert card["used_llm"] is False
    provider.complete_structured.assert_not_called()


def test_confirm_symbol_degrades_on_empty_llm_response(monkeypatch):
    from backend.research import watchtower_confirm as wc

    provider = _mock_provider({})
    monkeypatch.setattr(wc, "get_provider", lambda: provider)

    card = wc.confirm_symbol(
        symbol="603259",
        themes=["innovative_drug"],
        symbol_triggers=[_one_trigger("603259")],
        watchlist_entries=[_innovative_drug_entry(["603259"])],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=True,
    )

    assert card["stance"] == wc.STANCE_INSUFFICIENT
    assert card["flags"] == [wc.FLAG_EMPTY_LLM_RESPONSE]
    assert card["used_llm"] is False
    provider.complete_structured.assert_called_once()


def test_confirm_symbol_builds_valid_card_from_mock_llm(monkeypatch):
    from backend.research import watchtower_confirm as wc

    provider = _mock_provider(_valid_llm_payload())
    monkeypatch.setattr(wc, "get_provider", lambda: provider)

    card = wc.confirm_symbol(
        symbol="603259",
        themes=["innovative_drug"],
        symbol_triggers=[_one_trigger("603259")],
        watchlist_entries=[_innovative_drug_entry(["603259"])],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=True,
    )

    assert card["used_llm"] is True
    assert card["stance"] in wc.VALID_STANCES
    assert card["thesis_status"] in wc.VALID_THESIS_STATUSES
    assert len(card["risks"]) <= 2
    assert card["symbol"] == "603259"
    assert card["theme"] == "innovative_drug"
    assert card["disclaimer"] == "跟进关注≠买入建议"
    # Wording redline: no stance/thesis_status enum member is "买入", and no target-price field exists
    # (the schema's free-text descriptions may still *mention* "买入" only to forbid it).
    stance_enum = wc._CONFIRM_TOOL["input_schema"]["properties"]["stance"]["enum"]
    assert "买入" not in stance_enum and "卖出" not in stance_enum
    assert "target_price" not in wc._CONFIRM_TOOL["input_schema"]["properties"]
    assert not any("价" in key for key in wc._CONFIRM_TOOL["input_schema"]["properties"])
    for text_value in (card["reasoning"], card["validation_question"], *card["risks"]):
        assert "买入" not in text_value
        assert "目标价" not in text_value


def test_confirm_symbol_wording_redline_strips_banned_terms_even_if_llm_violates(monkeypatch):
    from backend.research import watchtower_confirm as wc

    provider = _mock_provider(
        _valid_llm_payload(reasoning="建议买入,目标价看到120元", risks=["建议买入过快", "目标价过于乐观"])
    )
    monkeypatch.setattr(wc, "get_provider", lambda: provider)

    card = wc.confirm_symbol(
        symbol="603259",
        themes=["innovative_drug"],
        symbol_triggers=[_one_trigger("603259")],
        watchlist_entries=[_innovative_drug_entry(["603259"])],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=True,
    )

    assert "买入" not in card["reasoning"]
    assert "目标价" not in card["reasoning"]
    for risk in card["risks"]:
        assert "买入" not in risk
        assert "目标价" not in risk


def test_confirm_symbol_invalid_enum_from_llm_falls_back_to_safe_defaults(monkeypatch):
    """If the LLM ever returns an out-of-schema stance/thesis_status, never propagate it raw."""
    from backend.research import watchtower_confirm as wc

    provider = _mock_provider(_valid_llm_payload(stance="强烈买入", thesis_status="未知状态"))
    monkeypatch.setattr(wc, "get_provider", lambda: provider)

    card = wc.confirm_symbol(
        symbol="603259",
        themes=["innovative_drug"],
        symbol_triggers=[_one_trigger("603259")],
        watchlist_entries=[_innovative_drug_entry(["603259"])],
        research_reference={"long_term_label": {"status": "missing"}, "research_pointer": {"status": "missing"}},
        memory_recall={"text": "", "status": "missing:no_db_session"},
        provider_available=True,
    )

    assert card["stance"] == wc.STANCE_INSUFFICIENT
    assert card["thesis_status"] == wc.THESIS_UNKNOWN


# ── build_confirmation_report: LLM call count bound + orchestration ────────


def test_build_confirmation_report_calls_llm_once_per_unique_symbol(tmp_path, monkeypatch):
    from backend.research import watchtower_confirm as wc

    db_path = tmp_path / "confirm.sqlite"
    _init_minimal_db(db_path)
    watchlist_dir = _write_watchlist(tmp_path, _innovative_drug_entry(["002821", "300759", "603259"]))

    # Mirrors the real 2026-07-03 scan: 002821 fires 4 trigger rows, 300759 fires 1, 603259 fires 2 —
    # 7 trigger rows total across 3 unique symbols.
    triggers = (
        [_one_trigger("002821", tt) for tt in ("news_trigger", "price_percentile_anomaly", "price_z_anomaly", "sector_resonance")]
        + [_one_trigger("300759", "sector_resonance")]
        + [_one_trigger("603259", tt) for tt in ("news_trigger", "sector_resonance")]
    )
    watchtower_report = {"as_of": "2026-07-03", "triggers": triggers}

    provider = _mock_provider(_valid_llm_payload())
    monkeypatch.setattr(wc, "get_provider", lambda: provider)
    monkeypatch.setattr(wc, "has_runtime_llm_provider", lambda _=None: True)

    report = wc.build_confirmation_report(
        watchtower_report=watchtower_report, db_path=db_path, watchlist_dir=watchlist_dir, db=None
    )

    assert report["n_triggered_symbols"] == 3
    assert report["n_llm_calls"] == 3
    assert provider.complete_structured.call_count == 3
    assert {card["symbol"] for card in report["cards"]} == {"002821", "300759", "603259"}
    assert all(card["stance"] in wc.VALID_STANCES for card in report["cards"])
    # LLM call count is bounded by the deduplicated trigger symbol count (never per trigger row).
    assert report["n_llm_calls"] <= report["n_triggered_symbols"]


def test_build_confirmation_report_degrades_without_raising_when_no_provider(tmp_path, monkeypatch):
    from backend.research import watchtower_confirm as wc

    db_path = tmp_path / "confirm.sqlite"
    _init_minimal_db(db_path)
    watchlist_dir = _write_watchlist(tmp_path, _innovative_drug_entry(["603259"]))
    watchtower_report = {"as_of": "2026-07-03", "triggers": [_one_trigger("603259")]}

    monkeypatch.setattr(wc, "has_runtime_llm_provider", lambda _=None: False)

    report = wc.build_confirmation_report(
        watchtower_report=watchtower_report, db_path=db_path, watchlist_dir=watchlist_dir, db=None
    )

    assert report["provider_available"] is False
    assert report["n_llm_calls"] == 0
    assert len(report["cards"]) == 1
    assert report["cards"][0]["stance"] == wc.STANCE_INSUFFICIENT
    assert report["cards"][0]["flags"] == [wc.FLAG_NO_PROVIDER]


def test_build_confirmation_report_no_triggers_produces_no_cards(tmp_path, monkeypatch):
    from backend.research import watchtower_confirm as wc

    db_path = tmp_path / "confirm.sqlite"
    _init_minimal_db(db_path)
    watchlist_dir = _write_watchlist(tmp_path, _innovative_drug_entry(["603259"]))
    watchtower_report = {"as_of": "2026-07-03", "triggers": []}

    monkeypatch.setattr(wc, "has_runtime_llm_provider", lambda _=None: True)

    report = wc.build_confirmation_report(
        watchtower_report=watchtower_report, db_path=db_path, watchlist_dir=watchlist_dir, db=None
    )

    assert report["n_triggered_symbols"] == 0
    assert report["n_llm_calls"] == 0
    assert report["cards"] == []
    assert "无需确认" in wc.render_markdown(report)


def test_build_confirmation_report_rejects_non_dict_input(tmp_path):
    from backend.research.watchtower_confirm import (
        WatchtowerConfirmInputError,
        build_confirmation_report,
    )

    with pytest.raises(WatchtowerConfirmInputError):
        build_confirmation_report(watchtower_report=["not", "a", "dict"])
