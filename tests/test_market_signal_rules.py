import pandas as pd


def _technical_frame() -> pd.DataFrame:
    close = [100 + i * 0.5 for i in range(80)]
    volume = [1000.0] * 75 + [1250.0] * 5
    return pd.DataFrame({
        "open": close,
        "high": [value + 1 for value in close],
        "low": [value - 1 for value in close],
        "close": close,
        "volume": volume,
    }, index=[f"2026-01-{(i % 28) + 1:02d}-{i:02d}" for i in range(80)])


def test_market_technical_rules_are_distinct_and_versioned():
    from backend.analysis.technical import market_technical_rule, technical_score

    cn = market_technical_rule("CN")
    hk = market_technical_rule("HK")
    us = market_technical_rule("US")
    assert cn["weights"] != hk["weights"] != us["weights"]
    assert {cn["version"], hk["version"], us["version"]} == {
        "cn-current",
        "hk-m67-gray-v1",
        "us-m67-gray-v1",
    }
    assert technical_score(_technical_frame(), market="HK")["market_rule"] == "hk-m67-gray-v1"


def test_hk_us_gray_policies_are_shadow_only_and_different():
    from backend.decision.market_signal_policy import apply_market_signal_policy

    base = {
        "breakdown": {"quant": 40, "technical": 30, "sentiment": 10},
        "composite_score": 30,
        "recommendation": "可关注",
        "confidence": "中",
        "stop_loss": 95,
        "take_profit": 110,
        "position_pct": 0.12,
        "rule_version": "aggregate_v1:test",
    }
    hk = apply_market_signal_policy(dict(base), market="HK", close=100, atr=2)
    us = apply_market_signal_policy(dict(base), market="US", close=100, atr=2)

    assert hk["execution_mode"] == us["execution_mode"] == "gray_shadow_only"
    assert hk["position_pct"] == us["position_pct"] == 0
    assert hk["model_position_pct"] == us["model_position_pct"] == 0.12
    assert hk["composite_score"] != us["composite_score"]
    assert hk["stop_loss"] != us["stop_loss"]
    assert hk["market_rule_version"] == "hk-m67-gray-v2"
    assert us["market_rule_version"] == "us-m67-gray-v2"
    assert hk["market_policy"]["weights"]["quant"] == 0
    assert us["market_policy"]["weights"]["quant"] == 0
