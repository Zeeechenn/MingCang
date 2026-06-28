import json
from datetime import datetime, timedelta

from backend.data.database import NewsItem, Price


class _MockLLMProvider:
    def complete_structured(
        self,
        prompt: str,
        tool: dict,
        system: str = "",
        max_tokens: int = 400,
        model_tier: str = "fast",
    ) -> dict:
        sentiment = 0.2
        if "利空" in prompt or "处罚" in prompt:
            sentiment = -0.4
        elif "利好" in prompt or "中标" in prompt:
            sentiment = 0.6
        return {
            "relevance": 0.9,
            "sentiment": sentiment,
            "materiality": 0.9,
            "horizon": "short",
            "event_type": "contract",
            "catalysts": ["mock"],
            "risks": [],
            "confidence": 0.8,
        }


def _add_price_bars(db, symbols: list[str], start: str, days: int = 12) -> None:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    for sym_index, symbol in enumerate(symbols):
        for offset in range(days):
            day = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            close = 10.0 + sym_index + offset * (sym_index + 1)
            db.add(
                Price(
                    symbol=symbol,
                    date=day,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1000,
                )
            )
    db.commit()


def _add_news(db, symbol: str, date: str, title: str, content: str) -> None:
    db.add(
        NewsItem(
            symbol=symbol,
            title=title,
            url=f"https://example.test/{symbol}/{date}/{abs(hash(title))}",
            published_at=datetime.strptime(f"{date} 10:00:00", "%Y-%m-%d %H:%M:%S"),
            source="mock",
            provider="mock",
            content=content,
        )
    )


def test_m54_news_v2_oos_mock_smoke_excludes_degraded(test_db, tmp_path, monkeypatch):
    from backend.tools import m54_news_v2_oos as tool

    symbols = ["000001", "000002", "000003"]
    _add_price_bars(test_db, symbols, "2026-01-05")
    for date in ("2026-01-05", "2026-01-06"):
        _add_news(test_db, "000001", date, "000001 中标 利好", "full content 利好")
        _add_news(test_db, "000002", date, "000002 处罚 利空", "full content 利空")
    test_db.commit()

    monkeypatch.setattr(
        "backend.data.news_extraction.get_provider",
        lambda: _MockLLMProvider(),
    )
    monkeypatch.delenv("SENTIMENT_CACHE_NS", raising=False)

    out = tmp_path / "m54-oos.json"
    result = tool.run_oos(
        symbols,
        "2026-01-05",
        "2026-01-06",
        lookback_days=1,
        tier="capable",
        out=out,
        db=test_db,
        session_factory=lambda: test_db,
    )

    assert result["status"] in {"ok", "gate_blocked"}
    assert result["n_symbols"] == 3
    assert result["n_windows"] == 4
    assert result["skipped_degraded"] == 2
    assert result["meta"]["oos_namespace"] == "oos_news_v2"
    assert set(result["metrics"]) == {"h3d", "h5d"}
    assert result["metrics"]["h3d"]["ic_days"] == 0
    assert result["metrics"]["h3d"]["quantile"]["monotonic"] is False
    assert result["gate_blockers"]

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["n_windows"] == 4
    assert written["skipped_degraded"] == 2
