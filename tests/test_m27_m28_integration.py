import pandas as pd
import pytest


def test_m27_alpha_features_are_in_training_panel():
    from backend.data.qlib_data import FEATURE_COLS, _build_features

    df = pd.DataFrame({
        "open": range(1, 301),
        "high": range(2, 302),
        "low": range(0, 300),
        "close": range(1, 301),
        "volume": [1000 + i * 3 for i in range(300)],
    })
    features = _build_features(df)

    for col in [
        "rev_mom_12_1_z",
        "turnover_anomaly_z",
        "price_volume_divergence_z",
        "sector_rel_strength_20_z",
    ]:
        assert col in FEATURE_COLS
        assert col in features.columns


def test_event_taxonomy_overrides_sentiment_when_event_matches():
    from backend.analysis.event_taxonomy import apply_event_score

    result = apply_event_score(
        {"sentiment": -0.2, "key_events": ["公司获得重大合同订单"]},
        [],
        enable_override=True,  # override is opt-in (default OFF per M27 IC diagnosis)
    )

    assert result["event_score_mode"] == "event_override"
    assert result["event_score"] > 0
    assert result["event_types"][0]["code"] == "major_contract"


def test_test3_universe_builder_selects_diversified_rows(test_db):
    from backend.data.database import Price, Stock
    from backend.tools.m27_build_test3_universe import build_universe

    for idx, sector in enumerate(["电子", "银行", "医药"], 1):
        symbol = f"30000{idx}"
        test_db.add(Stock(symbol=symbol, name=symbol, market="CN", industry=sector, active=True))
        for i in range(6):
            price = 10 + i + idx
            test_db.add(Price(
                symbol=symbol,
                date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1000 * idx,
            ))
    test_db.commit()

    payload = build_universe(test_db, target_size=3, min_bars=5, max_per_sector=1)

    assert payload["coverage"]["selected_count"] == 3
    assert payload["coverage"]["sector_count"] == 3


def test_m27_kronos_windows_respect_split_and_horizon():
    from backend.tools.m27_kronos_finetune_data import build_windows_for_symbol

    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "open": range(10, 20),
            "high": range(11, 21),
            "low": range(9, 19),
            "close": range(10, 20),
            "volume": [1000] * 10,
        },
        index=idx,
    )

    windows = build_windows_for_symbol(
        "300001",
        df,
        split="train",
        split_start="2026-01-03",
        split_end="2026-01-08",
        context=3,
        pred_len=2,
    )

    assert windows
    assert windows[0].context_start == "2026-01-01"
    assert windows[0].anchor_date == "2026-01-03"
    assert windows[0].label_end == "2026-01-05"


def test_kronos_path_a_listmle_prefers_correct_order():
    torch = pytest.importorskip("torch")
    from backend.analysis.kronos_losses import listmle_loss

    target = torch.tensor([[0.3, 0.1, -0.2]])
    good = torch.tensor([[3.0, 1.0, -1.0]])
    bad = torch.tensor([[-1.0, 1.0, 3.0]])

    assert listmle_loss(good, target) < listmle_loss(bad, target)


def test_m28_seed_queries_use_pure_memory_web_results(monkeypatch):
    from backend.research import deep_research

    monkeypatch.setattr(
        deep_research,
        "_tavily_web_search",
        lambda queries: [{
            "title": "AI算力订单更新",
            "url": "https://example.com/a",
            "published_date": "2026-05-17",
            "source": "tavily_web",
        }],
    )

    result = deep_research._execute_plan(
        {"action": "web_search", "search_queries": ["AI算力订单"]},
        db=None,
        symbols=["300308"],
        topic="AI算力",
    )
    news = deep_research._web_results_to_news(result["results"], fallback_dt=pd.Timestamp("2026-05-17").to_pydatetime())

    assert result["fetched"] == 1
    assert news[0].source == "tavily_web"


def test_m28_research_context_extracts_sections():
    from backend.agents.pipeline import build_research_context

    context = build_research_context(
        research_context={
            "sections": [{
                "role": "research_writer",
                "catalysts": ["订单兑现"],
                "risks": ["估值拥挤"],
                "evidence_snippets": ["订单证据片段"],
                "stance": "中性",
                "confidence": 0.7,
            }]
        }
    )

    assert context["catalysts"] == ["订单兑现"]
    assert context["risks"] == ["估值拥挤"]
    assert context["confidence"] == 0.7
