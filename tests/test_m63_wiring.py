from __future__ import annotations

from backend.tools.m63_daily import INTRADAY_STEP_MODULES, POSTMARKET_STEP_MODULES
from backend.tools.m63_wiring import WIRING_MAP
from backend.tools.registry import list_tool_entries


def test_m63_wiring_covers_registry_without_orphans_or_ghosts():
    registry = {entry["module"]: entry for entry in list_tool_entries()}
    wiring = set(WIRING_MAP)

    assert wiring == set(registry)

    for module, entry in registry.items():
        target = WIRING_MAP[module]
        assert target["bucket"] in {
            "daily_premarket",
            "daily_intraday",
            "daily_postmarket",
            "research",
            "weekly",
            "trigger",
            "manual_only",
        }
        if entry["category"] == "stable":
            assert target["bucket"] != "manual_only" or target.get("reason")
        if target["bucket"] == "manual_only":
            assert target.get("reason")


def test_daily_postmarket_wiring_is_connected_to_postmarket_steps():
    daily_postmarket = {
        module
        for module, entry in WIRING_MAP.items()
        if entry["bucket"] == "daily_postmarket"
    }

    assert daily_postmarket <= POSTMARKET_STEP_MODULES
    assert "backend.tools.m60_second_entry" in POSTMARKET_STEP_MODULES


def test_daily_intraday_wiring_is_connected_to_intraday_steps():
    daily_intraday = {
        module
        for module, entry in WIRING_MAP.items()
        if entry["bucket"] == "daily_intraday"
    }

    assert daily_intraday <= INTRADAY_STEP_MODULES
