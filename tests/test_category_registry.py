from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture(autouse=True)
def reset_category_registry():
    from backend.data import category_registry

    category_registry.reset_category_registry()
    yield
    category_registry.reset_category_registry()


def _request():
    from backend.data.category_registry import FetchRequest

    return FetchRequest(symbol="600519", start=date(2026, 1, 1), end=date(2026, 1, 2))


def test_register_requires_probe_and_known_category():
    from backend.data.category_registry import CategoryProvider, register_category_provider

    with pytest.raises(TypeError):
        CategoryProvider(
            name="bad",
            category="quotes",
            fetch=lambda request: [],
            probe=None,
        )

    with pytest.raises(ValueError):
        register_category_provider(
            CategoryProvider(
                name="bad-category",
                category="not_a_category",
                fetch=lambda request: [],
                probe=lambda: True,
            )
        )


def test_first_provider_raises_then_second_serves_and_records_degradation(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    def failing_fetch(request):
        raise RuntimeError("source offline")

    register_category_provider(
        CategoryProvider(
            name="primary",
            category="sector",
            fetch=failing_fetch,
            probe=lambda: True,
            priority=1,
        )
    )
    register_category_provider(
        CategoryProvider(
            name="backup",
            category="sector",
            fetch=lambda request: [{"symbol": request.symbol, "name": "食品饮料"}],
            probe=lambda: True,
            priority=2,
        )
    )

    result = fetch_by_category("sector", _request(), db=test_db)

    assert result.ok is True
    assert result.provider == "backup"
    assert result.rows == [{"symbol": "600519", "name": "食品饮料"}]
    assert len(result.degradations) == 1
    event = test_db.query(DegradationEvent).one()
    assert event.component == "category_registry"
    assert event.category == "sector"
    assert event.provider == "primary"
    assert event.error == "failure:source offline"


def test_all_providers_fail_without_exception():
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )

    register_category_provider(
        CategoryProvider(
            name="primary",
            category="sector",
            fetch=lambda request: (_ for _ in ()).throw(RuntimeError("primary down")),
            probe=lambda: True,
            priority=1,
        )
    )
    register_category_provider(
        CategoryProvider(
            name="backup",
            category="sector",
            fetch=lambda request: (_ for _ in ()).throw(RuntimeError("backup down")),
            probe=lambda: True,
            priority=2,
        )
    )

    result = fetch_by_category("sector", _request())

    assert result.ok is False
    assert result.rows == []
    assert result.provider is None
    assert len(result.degradations) == 2
    assert [row["provider"] for row in result.degradations] == ["primary", "backup"]


def test_contract_validation_drops_bad_rows_and_records_degradation(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    register_category_provider(
        CategoryProvider(
            name="quote-provider",
            category="quotes",
            fetch=lambda request: [
                {
                    "symbol": "600519",
                    "price": 100.0,
                    "volume": 1000,
                    "as_of": "2026-01-02",
                    "source": "fake",
                    "fetched_at": "2026-01-02T15:00:00",
                },
                {
                    "symbol": "600519",
                    "price": 101.0,
                    "volume": 1000,
                    "as_of": "",
                    "source": "fake",
                    "fetched_at": "2026-01-02T15:00:00",
                },
            ],
            probe=lambda: True,
        )
    )

    result = fetch_by_category("quotes", _request(), db=test_db)

    assert result.ok is True
    assert len(result.rows) == 1
    assert result.degradations[0]["error"] == "failure:contract_violation"
    assert result.degradations[0]["dropped"] == 1
    event = test_db.query(DegradationEvent).one()
    assert event.error == "failure:contract_violation"


def test_all_rows_bad_falls_through_to_next_provider(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )

    register_category_provider(
        CategoryProvider(
            name="bad-contract",
            category="quotes",
            fetch=lambda request: [{"symbol": "600519", "price": 100.0}],
            probe=lambda: True,
            priority=1,
        )
    )
    register_category_provider(
        CategoryProvider(
            name="good-contract",
            category="quotes",
            fetch=lambda request: [
                {
                    "symbol": "600519",
                    "price": 100.0,
                    "volume": 1000,
                    "as_of": "2026-01-02",
                    "source": "fake",
                    "fetched_at": "2026-01-02T15:00:00",
                }
            ],
            probe=lambda: True,
            priority=2,
        )
    )

    result = fetch_by_category("quotes", _request(), db=test_db)

    assert result.ok is True
    assert result.provider == "good-contract"
    assert len(result.rows) == 1
    assert result.degradations[0]["error"] == "failure:contract_violation"
    assert result.degradations[0]["dropped"] == 1


def test_empty_provider_records_coverage_gap_not_failure(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    register_category_provider(
        CategoryProvider(
            name="empty-provider",
            category="quotes",
            fetch=lambda request: [],
            probe=lambda: True,
        )
    )

    result = fetch_by_category("quotes", _request(), db=test_db)

    assert result.ok is False
    assert result.degradations[0]["error"] == "coverage_gap:empty"
    event = test_db.query(DegradationEvent).one()
    assert event.error == "coverage_gap:empty"


def test_exception_provider_records_failure_prefix(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    register_category_provider(
        CategoryProvider(
            name="broken-provider",
            category="quotes",
            fetch=lambda request: (_ for _ in ()).throw(RuntimeError("source offline")),
            probe=lambda: True,
        )
    )

    result = fetch_by_category("quotes", _request(), db=test_db)

    assert result.ok is False
    assert result.degradations[0]["error"] == "failure:source offline"
    event = test_db.query(DegradationEvent).one()
    assert event.error == "failure:source offline"


@pytest.mark.parametrize(
    ("category", "row"),
    [
        ("research_reports", {"symbol": "600519", "title": "报告", "provider": "unit"}),
        ("lhb", {"symbol": "600519", "provider": "unit"}),
        ("corporate_events", {"symbol": "600519", "title": "事件", "provider": "unit"}),
        ("holders", {"symbol": "600519", "provider": "unit"}),
        ("overseas", {"symbol": "HSI", "name": "恒指", "provider": "unit"}),
    ],
)
def test_new_m61_categories_enforce_contracts(category, row, test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    register_category_provider(
        CategoryProvider(
            name="bad-contract",
            category=category,
            fetch=lambda request: [row],
            probe=lambda: True,
        )
    )

    result = fetch_by_category(category, _request(), db=test_db)

    assert result.ok is False
    assert result.degradations[0]["error"] == "failure:contract_violation"
    event = test_db.query(DegradationEvent).one()
    assert event.error == "failure:contract_violation"


def test_fund_flow_uses_fetch_contract_shape(test_db):
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )

    register_category_provider(
        CategoryProvider(
            name="fund-flow-fetch",
            category="fund_flow",
            fetch=lambda request: [
                {
                    "symbol": "600519",
                    "trade_date": "2026-01-02",
                    "metric": "main_net",
                    "value": 100.0,
                    "currency": "CNY",
                    "source": "unit",
                    "fetched_at": "2026-01-02T15:00:00",
                }
            ],
            probe=lambda: True,
        )
    )

    result = fetch_by_category("fund_flow", _request(), db=test_db)

    assert result.ok is True
    assert result.degradations == []


def test_missing_schema_records_coverage_gap(monkeypatch, test_db):
    from backend.data import category_registry
    from backend.data.category_registry import (
        CategoryProvider,
        fetch_by_category,
        register_category_provider,
    )
    from backend.data.degradation import DegradationEvent

    monkeypatch.setitem(category_registry._CATEGORY_SCHEMA_KEYS, "news", "missing_unit_schema")
    register_category_provider(
        CategoryProvider(
            name="news-provider",
            category="news",
            fetch=lambda request: [{"symbol": "600519", "title": "新闻", "provider": "unit"}],
            probe=lambda: True,
        )
    )

    result = fetch_by_category("news", _request(), db=test_db)

    assert result.ok is False
    assert result.degradations[0]["error"] == "coverage_gap:schema_missing"
    event = test_db.query(DegradationEvent).one()
    assert event.error == "coverage_gap:schema_missing"


def test_list_capability_gaps_returns_all_categories():
    from backend.data.category_registry import (
        CATEGORIES,
        CategoryProvider,
        list_capability_gaps,
        register_category_provider,
    )

    register_category_provider(
        CategoryProvider(
            name="sector-provider",
            category="sector",
            fetch=lambda request: [],
            probe=lambda: True,
        )
    )

    gaps = list_capability_gaps()

    assert set(gaps) == CATEGORIES
    assert len(gaps) == 12
    assert gaps["sector"] == {"providers": ["sector-provider"], "has_provider": True}
    assert gaps["fund_flow"] == {"providers": [], "has_provider": False}
