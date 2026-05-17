"""M4.7 news_analyst 修复测试。

覆盖：
  • 无 events → 归零（confidence=0.1）
  • 有 events + 正向 LLM sentiment → 正分
  • 有 events + 负向 LLM sentiment → 负分
  • 关键词命中 → ±10 调整
  • 实际案例回归（300308 突破千元、603986 存储芯片等）
  • 关键词冲突时方向相消
  • 与 sentiment_analyst 在无 events 时区分（一个有分一个无）
  • 极端值不超过 ±100
"""
from __future__ import annotations

from backend.agents.analyst import news_analyst, sentiment_analyst


def _result(sentiment: float, events: list[str], impact: str = "short", summary: str = ""):
    return {
        "sentiment": sentiment,
        "key_events": events,
        "impact": impact,
        "summary": summary,
    }


def test_no_events_returns_zero():
    r = news_analyst(_result(0.8, []))
    assert r.score == 0.0
    assert r.confidence == 0.1
    assert r.key_findings == ["无关键事件"]


def test_no_events_distinguishes_from_sentiment_analyst():
    """no events: news=0 but sentiment_analyst 仍有分 → 两路独立"""
    res = _result(0.8, [])
    n = news_analyst(res)
    s = sentiment_analyst(res)
    assert n.score == 0.0
    assert s.score == 80.0


def test_positive_sentiment_with_events_gives_positive_score():
    r = news_analyst(_result(0.5, ["公司发布利好公告", "机构上调评级"]))
    assert r.score > 0
    # 基线 0.5 × 80 = 40，+10 for 利好 +10 for 上调 = 60
    assert r.score == 60.0


def test_negative_sentiment_with_events_gives_negative_score():
    r = news_analyst(_result(-0.5, ["公司暴跌", "净流出严重"]))
    assert r.score < 0
    # 基线 -40，-10 -10 = -60
    assert r.score == -60.0


def test_extreme_values_clipped_to_100():
    r = news_analyst(_result(1.0, ["利好突破", "上调评级", "签约扩产"]))
    # 基线 80 + 30 = 110 → cap 100
    assert r.score == 100.0


def test_extreme_negative_clipped():
    r = news_analyst(_result(-1.0, ["暴雷退市", "立案处罚", "踩雷违约"]))
    assert r.score == -100.0


def test_keyword_conflict_in_one_event_nets_zero_bonus():
    """同一 event 同时含 pos+neg 关键词 → 该条贡献 0 bonus"""
    r = news_analyst(_result(0.0, ["公司股价上涨但财报亏损"]))
    # 基线 0；上涨 +10、亏损 -10 = 0
    assert r.score == 0.0


def test_regression_300308_breakthrough():
    """300308 突破千元案例（修复前: 20，修复后: ≥75）"""
    events = [
        "中际旭创股价突破千元，成A股第10只千元股，总市值达1.11万亿",
        "盘中涨超7%，创业板诞生第二只千元股，一年内股价涨近十倍",
        "券商看好光互联产业链，通信行业整体资金流出但个股强势分化",
    ]
    r = news_analyst(_result(0.92, events))
    # 基线 73.6；命中 突破/涨/看好/强势/涨 多次 → ≥+20 bonus
    # 但 也命中 "流出" (净流出包含 流出)... 让我们检查实际分数
    assert r.score > 75   # 应远高于修复前 20


def test_regression_600036_high():
    """600036 沪指创新高 + 北向资金流入（修复前: 0，修复后: 应明显为正）"""
    events = [
        "沪指创近11年新高，市场整体强势上行",
        "外资买入热情高涨，北向资金持续流入",
        "52股获机构买入评级，招商银行有望受益",
    ]
    r = news_analyst(_result(0.75, events))
    assert r.score > 50   # 远高于修复前 0


def test_regression_300394_orders():
    """300394 CPO 订单旺盛（修复前: 0，修复后: 应明显为正）"""
    events = [
        "天孚通信CPO配套产品稳定交付、订单旺盛，高速光引擎新产品进展顺利",
        "光通信概念整体强势",
        "机构上调全年业绩预期",
    ]
    r = news_analyst(_result(0.82, events))
    assert r.score > 60


def test_regression_300750_outflow():
    """300750 净流出（修复前: -20，修复后: 应更负或类似）"""
    events = [
        "电力设备行业净流出84.12亿元，宁德时代等44股净流出超亿元",
        "全球动力电池装车增速大跳水，行业景气度承压",
        "控股股东向上海交大捐赠500万股完成过户，短期存在减持压力",
    ]
    r = news_analyst(_result(-0.35, events))
    # 基线 -28；命中 净流出×2 + 减持 = -30 bonus → -58
    assert r.score < -40


def test_confidence_scales_with_score_magnitude():
    """confidence = min(1, |score|/60)"""
    high = news_analyst(_result(1.0, ["突破", "签约"]))
    low = news_analyst(_result(0.1, ["业绩"]))
    assert high.confidence > low.confidence


def test_raw_dict_exposes_breakdown():
    r = news_analyst(_result(0.5, ["突破"]))
    assert "base_from_sentiment" in r.raw
    assert "keyword_bonus" in r.raw
    assert r.raw["base_from_sentiment"] == 40.0
    assert r.raw["keyword_bonus"] == 10
