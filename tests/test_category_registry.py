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
    assert event.error == "source offline"


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
    assert result.degradations[0]["error"] == "contract_violation"
    assert result.degradations[0]["dropped"] == 1
    event = test_db.query(DegradationEvent).one()
    assert event.error == "contract_violation"


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
    assert result.degradations[0]["error"] == "contract_violation"
    assert result.degradations[0]["dropped"] == 1


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
