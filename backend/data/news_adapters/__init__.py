"""M54 source-agnostic news adapters."""
from backend.data.news_adapters.anspire import AnspireAdapter
from backend.data.news_adapters.eastmoney import EastmoneyAdapter
from backend.data.news_adapters.registry import get_enabled_adapters, registered_adapter_names

__all__ = [
    "AnspireAdapter",
    "EastmoneyAdapter",
    "get_enabled_adapters",
    "registered_adapter_names",
]
