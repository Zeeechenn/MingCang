"""Registry for M54 news source adapters."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from backend.data.news_adapters.anspire import AnspireAdapter
from backend.data.news_adapters.eastmoney import EastmoneyAdapter
from backend.data.news_evidence import NewsSourceAdapter

AdapterFactory = Callable[[], NewsSourceAdapter]

_ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "eastmoney": EastmoneyAdapter,
    "anspire": AnspireAdapter,
}


def registered_adapter_names() -> list[str]:
    return list(_ADAPTER_FACTORIES)


def get_enabled_adapters(enabled: Sequence[str] | None = None) -> list[NewsSourceAdapter]:
    """Instantiate enabled adapters in priority order.

    Priority is the order of names in ``news_adapters_enabled``.
    """
    if enabled is None:
        from backend.config import settings

        enabled = settings.news_adapters_enabled

    adapters: list[NewsSourceAdapter] = []
    for raw_name in enabled:
        name = raw_name.strip().lower()
        if not name:
            continue
        factory = _ADAPTER_FACTORIES.get(name)
        if factory is None:
            raise ValueError(f"Unknown news adapter: {raw_name}")
        adapters.append(factory())
    return adapters
