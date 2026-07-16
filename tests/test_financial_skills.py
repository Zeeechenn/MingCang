from datetime import datetime


def test_skill_vetter_blocks_auto_trade_and_price_prediction():
    from backend.skills.vetter import vet_skill_output

    review = vet_skill_output(
        {
            "skill_name": "Stock-Analyst",
            "result": {
                "summary": "明天一定涨停，系统将自动下单买入。",
                "evidence": ["price_signal"],
            },
            "allowed_actions": ["自动下单"],
        }
    )

    assert review.status == "block"
    assert "auto_trade" in review.blocked_actions
    assert "price_prediction" in review.risk_flags


def test_skill_vetter_warns_when_evidence_is_empty():
    from backend.skills.vetter import vet_skill_output

    review = vet_skill_output(
        {
            "skill_name": "Daily-Trade-Review",
            "result": {"summary": "今日建议关注。"},
            "evidence": [],
            "allowed_actions": ["review_only"],
        }
    )

    assert review.status == "warn"
    assert "missing_evidence" in review.risk_flags


def test_stock_watcher_detects_price_volume_and_risk_events(test_db, sample_stocks):
    from backend.data.database import Price, Signal
    from backend.skills.watcher import scan_watch_events

    prices = [
        Price(symbol="300308", date="2026-05-15", open=98, high=101, low=96, close=100, volume=1000),
        Price(symbol="300308", date="2026-05-18", open=101, high=110, low=100, close=108, volume=2500),
    ]
    test_db.add_all(prices)
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-18",
        composite_score=35.0,
        recommendation="可小仓试错",
        confidence="中",
        stop_loss=107.0,
        take_profit=118.0,
    ))
    test_db.commit()

    events = scan_watch_events(test_db, as_of="2026-05-18")
    event_types = {event.event_type for event in events}

    assert "price_move" in event_types
    assert "volume_spike" in event_types
    assert "near_stop_loss" in event_types


def test_daily_review_builds_report_with_vetter_metadata(test_db, tmp_path, sample_stocks):
    from backend.data.database import DecisionRun, NewsItem, Price, Signal
    from backend.skills.daily_review import build_daily_review

    test_db.add_all([
        Price(symbol="300308", date="2026-05-17", open=100, high=103, low=99, close=100, volume=1000),
        Price(symbol="300308", date="2026-05-18", open=101, high=110, low=100, close=108, volume=2500),
    ])
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-18",
        quant_score=0.0,
        technical_score=42.0,
        sentiment_score=22.0,
        composite_score=35.0,
        recommendation="可小仓试错",
        confidence="中",
        stop_loss=97.0,
        take_profit=130.0,
        rule_version="multi_agent_v2:new_framework",
    ))
    test_db.add(NewsItem(
        symbol="300308",
        title="中际旭创订单增长",
        url="https://example.com/news/1",
        published_at=datetime(2026, 5, 18, 10, 0, 0),
        source="测试源",
    ))
    test_db.add(DecisionRun(
        run_id="postmarket:300308:2026-05-18:test",
        run_type="postmarket",
        symbol="300308",
        as_of="2026-05-18",
        profile="new_framework",
        rule_version="multi_agent_v2:new_framework",
        recommendation="可小仓试错",
        composite_score=35.0,
        input_snapshot_json="{}",
        agent_outputs_json="{}",
        risk_decision_json='{"risk_notes": ["板块集中"]}',
        final_action_json="{}",
    ))
    test_db.commit()

    review = build_daily_review(test_db, as_of="2026-05-18", output_dir=tmp_path)

    assert review.skill_name == "Daily-Trade-Review"
    assert review.as_of == "2026-05-18"
    assert review.path is not None
    assert review.path.exists()
    text = review.path.read_text(encoding="utf-8")
    assert "300308" in text
    assert "可小仓试错" in text
    assert "异动监控" in text
    assert review.vetter.status in {"pass", "warn"}


def test_daily_review_matches_timestamp_batch_signal(test_db, tmp_path, sample_stocks):
    """Signal.date 可能是批次时间戳(YYYY-MM-DDTHH:MM+08:00)，as_of=日前缀也应能命中。"""
    from backend.data.database import Price, Signal
    from backend.skills.daily_review import build_daily_review

    test_db.add_all([
        Price(symbol="300308", date="2026-05-17", open=100, high=103, low=99, close=100, volume=1000),
        Price(symbol="300308", date="2026-05-18", open=101, high=110, low=100, close=108, volume=2500),
    ])
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-18T16:25+08:00",
        composite_score=35.0,
        recommendation="可小仓试错",
        confidence="中",
        stop_loss=97.0,
        take_profit=130.0,
    ))
    test_db.commit()

    review = build_daily_review(test_db, as_of="2026-05-18", output_dir=tmp_path)

    assert review.signal_count == 1
    text = review.path.read_text(encoding="utf-8")
    assert "300308" in text


def test_financial_skill_api_entries_return_daily_review_and_watch_events(
    test_db,
    tmp_path,
    monkeypatch,
    sample_stocks,
):
    from backend.api.routes import get_watch_events_endpoint, run_daily_review_endpoint
    from backend.data.database import Price, Signal

    monkeypatch.setattr("backend.skills.daily_review.default_output_dir", lambda: tmp_path)
    test_db.add_all([
        Price(symbol="300308", date="2026-05-17", open=100, high=101, low=99, close=100, volume=1000),
        Price(symbol="300308", date="2026-05-18", open=101, high=110, low=100, close=108, volume=2500),
    ])
    test_db.add(Signal(
        symbol="300308",
        date="2026-05-18",
        composite_score=35.0,
        recommendation="可小仓试错",
        confidence="中",
        stop_loss=107.0,
        take_profit=118.0,
    ))
    test_db.commit()

    review = run_daily_review_endpoint(as_of="2026-05-18", db=test_db)
    events = get_watch_events_endpoint(as_of="2026-05-18", db=test_db)

    assert review["skill_name"] == "Daily-Trade-Review"
    assert review["signal_count"] == 1
    assert review["path"]
    assert any(event["event_type"] == "price_move" for event in events)
