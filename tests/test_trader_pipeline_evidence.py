from backend.agents.analyst import AnalystReport
from backend.agents.researcher import ResearcherConclusion
from backend.agents.trader import propose


def _report(role, score, findings=None, raw=None):
    return AnalystReport(
        role=role,
        score=score,
        confidence=0.8,
        key_findings=findings or [role],
        raw=raw or {},
    )


def _researcher():
    return ResearcherConclusion(
        bull_points=[],
        bear_points=[],
        action_bias="中性",
        rationale="test",
        used_llm=False,
    )


def test_trader_does_not_halve_sentiment_when_news_has_no_events(monkeypatch):
    from backend.agents import trader

    monkeypatch.setattr(trader.settings, "paper_trading_profile", "new_framework")
    reports = {
        "technical": _report("technical", 0),
        "quant": _report("quant", 0),
        "sentiment": _report("sentiment", 80),
        "news": _report("news", 0, findings=["无关键事件"], raw={"events": []}),
    }

    proposal = propose(reports, _researcher(), close=10.0, atr=0.5)

    assert proposal.breakdown["sentiment"] == 80
    assert proposal.breakdown["sentiment_raw"] == 80
    assert proposal.breakdown["news"] == 0
    assert proposal.breakdown["sentiment_mode"] == "sentiment_only_no_news_events"
    assert proposal.composite_score == 32.0


def test_trader_blends_sentiment_and_news_when_events_exist(monkeypatch):
    from backend.agents import trader

    monkeypatch.setattr(trader.settings, "paper_trading_profile", "new_framework")
    reports = {
        "technical": _report("technical", 0),
        "quant": _report("quant", 0),
        "sentiment": _report("sentiment", 80),
        "news": _report("news", 60, findings=["订单旺盛"], raw={"events": ["订单旺盛"]}),
    }

    proposal = propose(reports, _researcher(), close=10.0, atr=0.5)

    assert proposal.breakdown["sentiment"] == 70
    assert proposal.breakdown["sentiment_raw"] == 80
    assert proposal.breakdown["news"] == 60
    assert proposal.breakdown["sentiment_mode"] == "sentiment_news_blend"
    assert proposal.composite_score == 28.0
