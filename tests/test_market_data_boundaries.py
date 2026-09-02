from datetime import date, timedelta

import pandas as pd
import pytest


def test_market_facade_keeps_public_entrypoints():
    from backend.data import market

    public_names = [
        "register_default_market_providers",
        "fetch_daily",
        "fetch_cn_index",
        "load_price_df",
        "sync_index_to_db",
        "backfill_if_needed",
        "fetch_cn_daily",
        "fetch_cn_daily_akshare_em",
        "fetch_cn_daily_akshare_sina",
        "fetch_cn_daily_tushare",
        "fetch_cn_daily_tickflow",
        "fetch_cn_daily_tushare_qfq",
        "fetch_cn_daily_yfinance",
        "fetch_hk_daily",
        "fetch_us_daily",
        "fetch_cn_index_akshare",
        "fetch_cn_index_eastmoney",
        "fetch_cn_index_efinance",
        "fetch_cn_index_yfinance",
        "_normalize_ohlcv",
        "_utcnow_naive",
    ]

    for name in public_names:
        assert callable(getattr(market, name))

    assert market.DAILY_PROVIDER_ADJUSTMENTS["eastmoney_cn"] == "qfq"
    assert market.DAILY_PROVIDER_ADJUSTMENTS["yfinance_hk"] == "auto_adjust"
    assert "yfinance_cn" not in market.DAILY_PROVIDER_ADJUSTMENTS
    assert market.INDEX_PROVIDER_ADJUSTMENTS["eastmoney_index_cn"] == "index_unadjusted"


def test_backfill_write_guard_rejects_hfq_scaled_rows(test_db, monkeypatch):
    from backend.analysis import factors
    from backend.data import market
    from backend.data.database import Price

    latest = date.today() - timedelta(days=2)
    seed_start = latest - timedelta(days=9)
    for offset in range(10):
        day = seed_start + timedelta(days=offset)
        test_db.add(
            Price(
                symbol="600519",
                date=day.isoformat(),
                open=10.0,
                high=11.0,
                low=9.5,
                close=10.0,
                volume=1_000_000,
                source="seed",
                adjustment="qfq",
            )
        )
    test_db.commit()

    contaminated_day = date.today() - timedelta(days=1)
    df = pd.DataFrame(
        [
            {
                "open": 980.0,
                "high": 1020.0,
                "low": 970.0,
                "close": 1000.0,
                "volume": 500_000,
            }
        ],
        index=[contaminated_day.isoformat()],
    )
    df.attrs["source"] = "unit_provider"
    df.attrs["fetched_at"] = market._utcnow_naive()
    df.attrs["adjustment"] = "qfq"

    monkeypatch.setattr(market, "fetch_daily", lambda *args, **kwargs: df)
    monkeypatch.setattr(factors, "add_all_factors", lambda frame: frame.assign(atr14=0.1))

    inserted = market.backfill_if_needed("600519", "CN", test_db, years=1)

    assert inserted == 0
    assert (
        test_db.query(Price)
        .filter(Price.symbol == "600519", Price.date == contaminated_day.isoformat())
        .count()
        == 0
    )
    assert test_db.query(Price).filter(Price.symbol == "600519").count() == 10


def test_strict_basis_guard_blocks_cross_provider_append_without_changing_prices(
    test_db, monkeypatch
):
    from backend.analysis import factors
    from backend.data import market
    from backend.data.database import Price
    from backend.data.market_persistence import PriceBasisWriteBlocked

    stored_days = [date.today() - timedelta(days=offset) for offset in range(6, 1, -1)]
    for day in stored_days:
        test_db.add(Price(
            symbol="600519",
            asset_key="CN:600519",
            market="CN",
            currency="CNY",
            date=day.isoformat(),
            open=10,
            high=11,
            low=9,
            close=10,
            volume=1_000_000,
            source="provider_a",
            adjustment="qfq",
        ))
    test_db.commit()
    before = [
        (row.date, row.source, row.adjustment)
        for row in test_db.query(Price).order_by(Price.date).all()
    ]

    next_day = date.today() - timedelta(days=1)
    frame = pd.DataFrame(
        [
            {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 1_000_000}
            for _ in [*stored_days, next_day]
        ],
        index=[day.isoformat() for day in [*stored_days, next_day]],
    )
    frame.attrs["source"] = "provider_b"
    frame.attrs["fetched_at"] = market._utcnow_naive()
    frame.attrs["adjustment"] = "qfq"
    monkeypatch.setattr(market, "fetch_daily", lambda *args, **kwargs: frame)
    monkeypatch.setattr(factors, "add_all_factors", lambda value: value.assign(atr14=0.1))

    with pytest.raises(PriceBasisWriteBlocked, match="stored_source_mismatch:provider_a"):
        market.backfill_if_needed(
            "600519",
            "CN",
            test_db,
            years=1,
            strict_basis_write_guard=True,
        )

    after = [
        (row.date, row.source, row.adjustment)
        for row in test_db.query(Price).order_by(Price.date).all()
    ]
    assert after == before


def test_strict_basis_guard_is_opt_in_for_current_one_loop_callers() -> None:
    import inspect

    from backend.data import market

    parameter = inspect.signature(market.backfill_if_needed).parameters[
        "strict_basis_write_guard"
    ]
    assert parameter.default is False


def _ifind_response(answer: str, adjustment: str = "前复权") -> dict:
    """Shape a call_ifind_mcp_tool() return value around a Markdown answer table."""
    return {
        "ok": True,
        "parsed": {
            "raw_text": "",
            "json": {
                "answer": answer,
                "indicators_params": {
                    field: {"复权方式": adjustment}
                    for field in ("开盘价", "最高价", "最低价", "收盘价")
                },
            },
            "tables": [],
        },
        "error": None,
    }


_IFIND_ANSWER = (
    "|证券代码|证券简称|日期|最低价（单位：元）|最高价（单位：元）|成交量|开盘价（单位：元）|收盘价（单位：元）|\n"
    "|---|---|---|---|---|---|---|---|\n"
    "|601318.SH|中国平安|20260825|54.65|55.42|7392.9038万|55.06|55.01|\n"
    "|601318.SH|中国平安|20260824|53.3|55.22|1.3076亿|53.34|54.92|\n"
    "|601318.SH|中国平安|20260823|\t|\t|\t|\t|53.35|\n"
    "|601318.SH|中国平安|20260821|52.8|53.59|1.116亿|53.01|53.35|"
)


def test_ifind_daily_maps_by_header_and_drops_non_trading_rows(monkeypatch):
    """列顺序由服务端语义解析决定（此处成交量在第 6 列），只能按表头列名映射。

    08-23 是周日：iFinD 用前一交易日 close 填充、OHLC 与成交量留空，必须丢掉，
    否则会给下游造出一根假 bar。
    """
    from backend.data import market_sources

    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_enabled", True, raising=False
    )
    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_token", "token", raising=False
    )
    monkeypatch.setattr(
        "backend.data.ifind_mcp.call_ifind_mcp_tool",
        lambda *args, **kwargs: _ifind_response(_IFIND_ANSWER),
    )

    frame = market_sources.fetch_cn_daily_ifind("601318", days=10)

    assert list(frame.index) == ["2026-08-21", "2026-08-24", "2026-08-25"]
    assert frame.loc["2026-08-25", "open"] == 55.06
    assert frame.loc["2026-08-25", "high"] == 55.42
    assert frame.loc["2026-08-25", "low"] == 54.65
    assert frame.loc["2026-08-25", "close"] == 55.01
    assert frame.loc["2026-08-25", "volume"] == 73_929_038


def test_ifind_daily_rejects_unadjusted_series(monkeypatch):
    """iFinD 默认「不复权」，与 CN fallback 全链的 qfq 冲突——必须拒绝而非静默混入。"""
    import pytest

    from backend.data import market_sources

    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_enabled", True, raising=False
    )
    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_token", "token", raising=False
    )
    monkeypatch.setattr(
        "backend.data.ifind_mcp.call_ifind_mcp_tool",
        lambda *args, **kwargs: _ifind_response(_IFIND_ANSWER, adjustment="不复权"),
    )

    with pytest.raises(ValueError, match="expected 前复权"):
        market_sources.fetch_cn_daily_ifind("601318", days=10)


def test_ifind_daily_rejects_inconsistent_ohlc(monkeypatch):
    """兜住表头映射错位：high 低于 close 的行不可能合法，宁可让 fallback 继续找。"""
    import pytest

    from backend.data import market_sources

    broken = (
        "|证券代码|日期|开盘价（单位：元）|最高价（单位：元）|最低价（单位：元）|收盘价（单位：元）|成交量|\n"
        "|---|---|---|---|---|---|---|\n"
        "|601318.SH|20260825|55.06|55.01|54.65|55.42|7392.9038万|"
    )
    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_enabled", True, raising=False
    )
    monkeypatch.setattr(
        market_sources.settings, "ifind_mcp_token", "token", raising=False
    )
    monkeypatch.setattr(
        "backend.data.ifind_mcp.call_ifind_mcp_tool",
        lambda *args, **kwargs: _ifind_response(broken),
    )

    with pytest.raises(ValueError, match="OHLC inconsistent"):
        market_sources.fetch_cn_daily_ifind("601318", days=10)


def test_ifind_daily_stays_last_in_cn_fallback_chain():
    """iFinD QPS=1、单次约 10s，做主源会把整池取数拖慢一个数量级——必须排在免费源之后。"""
    from backend.data import market, providers

    market.register_default_market_providers()
    registry = providers._DAILY_PROVIDERS
    entries = registry.values() if hasattr(registry, "values") else registry
    cn = [p for p in entries if "CN" in (getattr(p, "markets", None) or set())]
    assert cn, "CN fallback chain is empty — registration did not run"

    ifind = [p for p in cn if getattr(p, "name", "") == "ifind_cn"]
    if not ifind:  # 未配置 token 的部署不注册该源，行为与接入前一致
        return
    assert len(cn) > 1, "iFinD must not be the only CN source"
    assert max(p.priority for p in cn) == ifind[0].priority
