from __future__ import annotations

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
