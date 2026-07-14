

def test_positions_crud_and_summary(test_db):
    from backend.api.routes.dashboard import dashboard_summary
    from backend.api.routes.positions import (
        close_position,
        create_position,
        delete_closed_position,
        list_positions,
        update_position,
    )
    from backend.api.schemas import PositionClose, PositionCreate, PositionUpdate
    from backend.data.database import Price, Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", industry="通信设备", active=True))
    test_db.add(Price(symbol="300308", date="2026-05-18", open=100, high=110, low=99, close=108, volume=1))
    test_db.commit()

    created = create_position(
        PositionCreate(symbol="300308", quantity=100, avg_cost=100, opened_at="2026-05-18"),
        db=test_db,
    )
    assert created.name == "中际旭创"
    assert created.pnl_pct == 8.0

    updated = update_position(created.id, PositionUpdate(note="核心持仓"), db=test_db)
    assert updated.note == "核心持仓"

    positions = list_positions(db=test_db)
    assert len(positions) == 1
    assert positions[0].market_value == 10800

    closed = close_position(
        created.id,
        PositionClose(status="closed", note="止盈平仓"),
        close_price=112,
        closed_at="2026-05-19",
        db=test_db,
    )
    assert closed.status == "closed"
    assert closed.realized_pnl == 1200
    assert closed.realized_pnl_pct == 12.0
    assert closed.close_price == 112
    assert list_positions(db=test_db) == []
    assert delete_closed_position(created.id, db=test_db)["status"] == "deleted"
    assert list_positions(status="all", db=test_db) == []

    summary = dashboard_summary(as_of="2026-05-18", db=test_db)
    assert summary["positions"]["count"] == 0


def test_stock_search_uses_local_rows_first(test_db):
    from backend.api.routes.stocks import search_stocks
    from backend.data.database import Stock

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", active=True))
    test_db.commit()

    results = search_stocks(q="茅台", market="CN", limit=5, db=test_db)

    assert results[0]["symbol"] == "600519"
    assert results[0]["name"] == "贵州茅台"
    assert results[0]["source"] == "local"


def test_daily_review_ensure_runs_once_after_1500(test_db, tmp_path, monkeypatch, sample_stocks):
    from backend.api.routes.reviews import ensure_daily_review, get_review, list_reviews
    from backend.data.database import Signal

    monkeypatch.setattr("backend.skills.daily_review.default_output_dir", lambda: tmp_path)
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-18",
        composite_score=35.0,
        recommendation="可小仓试错",
        confidence="中",
    ))
    test_db.commit()

    first = ensure_daily_review(
        as_of="2026-05-18",
        now="2026-05-18T15:10:00+08:00",
        db=test_db,
    )
    second = ensure_daily_review(
        as_of="2026-05-18",
        now="2026-05-18T15:30:00+08:00",
        db=test_db,
    )

    assert first["status"] == "created"
    assert second["status"] == "existing"
    rows = list_reviews(kind="daily", db=test_db)
    assert len(rows) == 1
    detail = get_review(rows[0]["id"], db=test_db)
    assert "# MingCang 每日复盘" in detail["content"]
    assert "当日信号" in detail["content"]


def test_runtime_config_updates_weights_positions_data_and_review_times():
    from backend.api.routes.system import get_runtime_config, update_runtime_config

    original = get_runtime_config()
    updated = update_runtime_config({
        "weight_quant": 0.1,
        "weight_technical": 0.55,
        "weight_sentiment": 0.35,
        "max_position_per_stock": 0.2,
        "max_total_equity_pct": 0.7,
        "tavily_supplement_threshold": 4,
        "anspire_news_max_add": 3,
        "long_term_constraints_enabled": True,
        "schedule_daily_review_time": "15:30",
        "schedule_longterm_monday_dow": "tue",
        "schedule_longterm_monday_time": "09:30",
        "schedule_longterm_friday_dow": "thu",
        "schedule_longterm_friday_time": "15:30",
    })
    assert updated["raw_weights"]["weight_quant"] == 0.1
    assert updated["max_position_per_stock"] == 0.2
    assert updated["max_total_equity_pct"] == 0.7
    assert updated["data_draft"]["tavily_supplement_threshold"] == 4
    assert updated["long_term_constraints_enabled"] is True
    assert updated["schedule"]["daily_review_time"] == "15:30"
    assert updated["schedule"]["longterm_monday_dow"] == "tue"
    assert updated["schedule"]["longterm_friday_dow"] == "thu"
    assert updated["schedule"]["longterm_friday_time"] == "15:30"

    update_runtime_config({
        "weight_quant": original["raw_weights"]["weight_quant"],
        "weight_technical": original["raw_weights"]["weight_technical"],
        "weight_sentiment": original["raw_weights"]["weight_sentiment"],
        "max_position_per_stock": original["max_position_per_stock"],
        "max_total_equity_pct": original["max_total_equity_pct"],
        "tavily_supplement_threshold": original["data_draft"]["tavily_supplement_threshold"],
        "anspire_news_max_add": original["data_draft"]["anspire_news_max_add"],
        "long_term_constraints_enabled": original["long_term_constraints_enabled"],
        "schedule_daily_review_time": original["schedule"]["daily_review_time"],
        "schedule_longterm_monday_dow": original["schedule"]["longterm_monday_dow"],
        "schedule_longterm_monday_time": original["schedule"]["longterm_monday_time"],
        "schedule_longterm_friday_dow": original["schedule"]["longterm_friday_dow"],
        "schedule_longterm_friday_time": original["schedule"]["longterm_friday_time"],
    })


def test_ai_chat_creates_pending_action_and_confirm_adds_stock(test_db, monkeypatch):
    from backend.api.routes.ai import (
        archive_chat_session,
        chat,
        confirm_action,
        create_chat_session,
        list_chat_messages,
        list_chat_sessions,
    )
    from backend.api.schemas import AIChatRequest
    from backend.data.database import Stock

    response = chat(
        AIChatRequest(message="帮我添加自选股 600519 贵州茅台", mode="general"),
        db=test_db,
    )

    assert response.pending_action is not None
    assert response.pending_action["action"] == "watchlist.add"

    result = confirm_action(response.pending_action["id"], db=test_db)
    assert result["status"] == "executed"
    assert test_db.query(Stock).filter(Stock.symbol == "600519", Stock.active).count() == 1

    session = create_chat_session({"title": "测试窗口"}, db=test_db)
    chat(
        AIChatRequest(message="记住这个窗口关注 600519", mode="general", session_id=session["id"]),
        db=test_db,
    )
    messages = list_chat_messages(session["id"], db=test_db)
    assert len(messages) == 2
    assert list_chat_sessions(db=test_db)[0]["id"] == session["id"]
    assert archive_chat_session(session["id"], db=test_db)["status"] == "archived"
    assert all(row["id"] != session["id"] for row in list_chat_sessions(db=test_db))


def test_ai_long_term_team_mode_runs_for_symbol(test_db, monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.api.routes.ai import chat
    from backend.api.schemas import AIChatRequest
    from backend.data.database import Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", active=True))
    test_db.commit()

    def fake_run(self, symbol, name, db):
        return LongTermLabel(
            symbol=symbol,
            date="2026-05-19",
            label="值得持有",
            score=72.0,
            votes={"fake": "buy"},
            key_findings=["测试长期观点"],
            expires_at="2026-05-29",
        )

    monkeypatch.setattr("backend.agents.long_term.team.LongTermTeam.run", fake_run)

    response = chat(
        AIChatRequest(message="研究 300308", mode="long_term_team"),
        db=test_db,
    )

    assert "值得持有" in response.answer
    assert response.used_resources == ["long_term_team"]


def test_prepare_symbol_research_returns_dossier_and_missing_items(test_db, monkeypatch):
    from backend.api.routes.research import prepare_symbol_research

    monkeypatch.setattr("backend.data.market.backfill_if_needed", lambda *args, **kwargs: 0)
    monkeypatch.setattr("backend.data.fundamentals.sync_financial_metrics", lambda *args, **kwargs: 0)

    response = prepare_symbol_research(
        "300308",
        name="中际旭创",
        market="CN",
        db=test_db,
    )

    assert response["status"] == "prepared"
    assert response["dossier"]["symbol"] == "300308"
    assert "latest_signal" in response["missing"]
    assert response["steps"]["prices"]["ok"] is True


def test_prepare_symbol_research_accepts_hk_without_cn_financial_sync(test_db, monkeypatch):
    from backend.api.routes.research import prepare_symbol_research
    from backend.data.database import Stock

    monkeypatch.setattr("backend.data.market.backfill_if_needed", lambda *args, **kwargs: 0)

    def fail_cn_financials(*args, **kwargs):
        raise AssertionError("HK prepare should not call CN fundamentals sync")

    monkeypatch.setattr("backend.data.fundamentals.sync_financial_metrics", fail_cn_financials)

    response = prepare_symbol_research(
        "700",
        name="腾讯控股",
        market="HK",
        db=test_db,
    )

    assert response["status"] == "prepared"
    assert response["symbol"] == "700"
    assert response["signal_scope"] == "observe_only"
    assert response["steps"]["prices"]["ok"] is True
    assert "financials" not in response["steps"]
    stock = test_db.query(Stock).filter(Stock.symbol == "700").one()
    assert stock.market == "HK"
    assert stock.active is False


def test_single_symbol_long_term_run_rejects_hk_observe_only(test_db):
    import pytest
    from fastapi import HTTPException

    from backend.api.routes.watchlist import run_long_term_label
    from backend.data.database import Stock

    test_db.add(Stock(symbol="700", name="腾讯控股", market="HK", active=True))
    test_db.commit()

    with pytest.raises(HTTPException) as exc:
        run_long_term_label("700", db=test_db)

    assert exc.value.status_code == 400
    assert "CN-only" in exc.value.detail


def test_watchlist_hides_hk_us_legacy_signals_and_long_term_labels(test_db):
    import json

    from backend.api.routes.watchlist import get_watchlist
    from backend.data.database import LongTermLabel, Signal, Stock

    test_db.add(Stock(symbol="600519", name="贵州茅台", market="CN", active=True))
    test_db.add(Stock(symbol="700", name="腾讯控股", market="HK", active=True))
    test_db.add(Signal(symbol="700", date="2026-06-01", composite_score=99, recommendation="买入", confidence="高"))
    test_db.add(
        LongTermLabel(
            symbol="700",
            date="2026-06-01",
            label="值得持有",
            score=80,
            votes_json=json.dumps({"legacy": "值得持有"}),
            key_findings_json=json.dumps(["旧标签"]),
            expires_at="2999-01-01",
            quality="trusted",
            constraint_eligible=True,
        )
    )
    test_db.commit()

    rows = {item.symbol: item for item in get_watchlist(db=test_db)}

    assert rows["700"].latest_signal is None
    assert rows["700"].long_term_label is None
def test_single_symbol_long_term_run_returns_quality_metadata(test_db, monkeypatch):
    from backend.agents.long_term.base import LongTermLabel
    from backend.api.routes.watchlist import run_long_term_label
    from backend.data.database import Stock

    test_db.add(Stock(symbol="300308", name="中际旭创", market="CN", active=True))
    test_db.commit()

    def fake_run(self, symbol, name, db):
        return LongTermLabel(
            symbol=symbol,
            date="2026-05-26",
            label="值得持有",
            score=72.0,
            votes={"track": "值得持有"},
            key_findings=["测试长期观点"],
            expires_at="2999-01-01",
            quality="trusted",
            constraint_eligible=True,
            quality_notes=["长期标签通过质量门"],
        )

    monkeypatch.setattr("backend.agents.long_term.team.LongTermTeam.run", fake_run)

    response = run_long_term_label("300308", db=test_db)

    assert response.quality == "trusted"
    assert response.constraint_eligible is True


def test_deep_research_response_includes_readiness(test_db, monkeypatch):
    from backend.api.routes.research import run_deep_research_endpoint
    from backend.api.schemas import DeepResearchRequest
    from backend.research.deep_research import DeepResearchReport

    def fake_run_deep_research(**kwargs):
        return DeepResearchReport(
            topic=kwargs["topic"],
            symbols=kwargs["symbols"],
            as_of="2026-05-26",
            summary="专题调研摘要",
            path=None,
            source_count=0,
            risk_flags=[],
        )

    monkeypatch.setattr("backend.research.deep_research.run_deep_research", fake_run_deep_research)
    response = run_deep_research_endpoint(
        DeepResearchRequest(topic="AI算力", symbols=["300308"]),
        db=test_db,
    )

    assert response.readiness["search_configured"] in {True, False}
    assert "llm" in response.readiness
