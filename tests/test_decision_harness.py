from backend.data.database import Price, Signal


def test_record_decision_run_and_research_state(test_db):
    from backend.decision.harness import (
        get_decision_evidence,
        get_research_state,
        record_decision_run,
    )

    result = {
        "rule_version": "multi_agent_v2:new_framework",
        "recommendation": "可小仓试错",
        "confidence": "中",
        "composite_score": 31.5,
        "breakdown": {"quant": 0, "technical": 30, "sentiment": 60},
        "risk_notes": ["单股仓位上限 15%"],
        "stop_loss": 10.0,
        "take_profit": 14.0,
        "position_pct": 0.05,
    }

    run = record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-15",
        result=result,
        input_snapshot={"data_timestamp": "2026-05-15"},
    )

    evidence = get_decision_evidence(test_db, "600519")
    state = get_research_state(test_db, "600519")

    assert run.run_id.startswith("postmarket:600519:2026-05-15")
    assert evidence[0]["profile"] == "new_framework"
    assert evidence[0]["agent_outputs"]["breakdown"]["technical"] == 30
    assert state["last_signal_summary"].startswith("可小仓试错")


def test_review_latest_signal_updates_run_and_state(test_db):
    from backend.decision.harness import (
        get_decision_evidence,
        get_research_state,
        record_decision_run,
        review_latest_signal,
    )

    test_db.add(Signal(
        symbol="600519",
        date="2026-05-15",
        technical_score=-10,
        quant_score=0,
        sentiment_score=80,
        composite_score=30,
        recommendation="可小仓试错",
        confidence="中",
    ))
    test_db.add(Price(symbol="600519", date="2026-05-15", open=10, high=10, low=10, close=10, volume=1))
    test_db.add(Price(symbol="600519", date="2026-05-16", open=9, high=9, low=9, close=9, volume=1))
    test_db.commit()

    record_decision_run(
        test_db,
        run_type="postmarket",
        symbol="600519",
        as_of="2026-05-15",
        result={"rule_version": "multi_agent_v2:new_framework", "recommendation": "可小仓试错", "composite_score": 30},
    )
    review = review_latest_signal(test_db, "600519")

    assert review["correct"] is False
    assert "情感偏乐观" in review["attribution"][0]
    assert get_research_state(test_db, "600519")["last_review"]["next_day_return"] == -10.0
    assert get_decision_evidence(test_db, "600519")[0]["eval_result"]["correct"] is False

