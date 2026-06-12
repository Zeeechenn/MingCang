"""Tests for backend/research/serenity_chokepoint.py — M50 Phase 1.

Validates:
- SerenityChokepointReport has no score/label_vote/trading fields
- No LongTermTeam aggregation path is called
- flag default False → analyze() returns None without calling LLM or writing DB
- Schema tool definition has no forbidden keys
"""
from unittest.mock import MagicMock

import pytest


class TestSerenitySchemaNoTradingFields:
    """Serenity tool schema must not contain scoring / trading fields."""

    def test_tool_schema_has_no_forbidden_keys(self):
        from backend.research.serenity_chokepoint import _SERENITY_TOOL

        schema_props = set(
            _SERENITY_TOOL["input_schema"]["properties"].keys()
        )
        forbidden = {
            "score", "label_vote", "buy_score", "position_pct",
            "price_target", "stop_loss", "take_profit", "composite_score",
            "direction", "entry_signal", "recommendation",
        }
        overlap = forbidden & schema_props
        assert not overlap, f"Serenity schema must not contain: {overlap}"

    def test_report_dataclass_has_no_trading_fields(self):
        from dataclasses import fields

        from backend.research.serenity_chokepoint import SerenityChokepointReport

        field_names = {f.name for f in fields(SerenityChokepointReport)}
        forbidden = {
            "score", "label_vote", "buy_score", "position_pct",
            "price_target", "stop_loss", "take_profit", "composite_score",
            "direction", "entry_signal",
        }
        overlap = forbidden & field_names
        assert not overlap, f"SerenityChokepointReport must not contain: {overlap}"

    def test_report_is_not_long_term_report(self):
        """SerenityChokepointReport must NOT be a subclass of LongTermReport."""
        from backend.agents.long_term.base import LongTermReport
        from backend.research.serenity_chokepoint import SerenityChokepointReport

        assert not issubclass(SerenityChokepointReport, LongTermReport), (
            "SerenityChokepointReport must not inherit LongTermReport"
        )


class TestSerenityDisabledByDefault:
    """When long_term_serenity_enabled=False, analyze() returns None, no LLM, no DB."""

    def test_analyze_returns_none_when_disabled(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", False)

        from backend.research.serenity_chokepoint import analyze
        result = analyze("光模块供应链", ["300308"], db=None)
        assert result is None

    def test_analyze_does_not_call_llm_when_disabled(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", False)

        # Patch get_provider at the module where serenity_chokepoint resolves it
        call_tracker = []

        def fake_get_provider():
            call_tracker.append("called")
            return MagicMock()

        monkeypatch.setattr("backend.llm.get_provider", fake_get_provider)

        from backend.research.serenity_chokepoint import analyze
        analyze("光模块供应链", ["300308"], db=None)
        # If disabled, get_provider should never be called
        assert not call_tracker, "get_provider should not be called when disabled"

    def test_analyze_does_not_write_db_when_disabled(self, monkeypatch):
        """When disabled, analyze() must not write anything to DB."""
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", False)

        mock_db = MagicMock()

        from backend.research.serenity_chokepoint import analyze
        result = analyze("光模块供应链", [], db=mock_db)

        assert result is None
        # DB should have no writes
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()


class TestSerenityEnabledWithLLMUnavailable:
    """When enabled but LLM unavailable, analyze() returns None."""

    def test_returns_none_when_llm_not_usable(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", True)

        # runtime_readiness is imported inside the function from backend.llm
        # patch at the module level where it gets resolved
        monkeypatch.setattr(
            "backend.llm.runtime_readiness",
            lambda s: {"usable": False, "reason": "no API key"},
        )
        monkeypatch.setattr(
            "backend.llm.get_provider",
            lambda: MagicMock(),
        )

        import backend.research.serenity_chokepoint as sc_mod
        result = sc_mod.analyze("光模块供应链", ["300308"], db=None)
        assert result is None


class TestSerenityNoAggregationImports:
    """Serenity module must not import aggregation / signal paths."""

    def test_no_forbidden_imports(self):
        import ast
        from pathlib import Path

        path = Path(__file__).parent.parent / "backend/research/serenity_chokepoint.py"
        tree = ast.parse(path.read_text())
        forbidden_names = {
            "LongTermTeam", "_aggregate_score", "aggregate",
            "aggregate_v2", "run_pipeline", "apply_research_constraints",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        assert alias.name not in forbidden_names, (
                            f"serenity_chokepoint.py must not import {alias.name}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in forbidden_names, (
                            f"serenity_chokepoint.py must not import {alias.name}"
                        )


class TestSerenityReportConstruction:
    """Test direct construction of SerenityChokepointReport dataclass."""

    def test_construct_minimal_report(self):
        from backend.research.serenity_chokepoint import SerenityChokepointReport

        report = SerenityChokepointReport(
            topic="光模块供应链",
            as_of="2026-06-09",
            chokepoint_layer="800G光模块封装",
            chain_layers=[{"layer": "下游", "description": "AI训练集群"}],
            scarce_layer="800G光模块封装",
            quick_filter_by_layer=[{
                "layer": "800G光模块封装",
                "forced_demand": True,
                "size_mismatch": True,
                "no_substitute": True,
                "outside_voice": "Lumentum订单待核验",
            }],
            quick_filter_pass=True,
            evidence_tier="industry",
            source_refs=[],
            substitute_risk="暂未发现明显替代路径",
            bayesian={
                "prior": "供给紧张",
                "key_update_triggers": ["产能扩张公告"],
                "current_posterior": "证据待补充",
            },
            bear_case="产能扩张超预期",
            falsification_questions=["若扩产提速则论题失效"],
            research_priority_band="够查",
        )
        assert report.topic == "光模块供应链"
        assert report.quick_filter_pass is True
        assert report.research_priority_band == "够查"
        # Verify frozen — direct attribute assignment should raise FrozenInstanceError
        import dataclasses
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.topic = "changed"  # type: ignore[misc]


class TestSerenityProjectRootPath:
    """F6 fix: _PROJECT_ROOT must resolve to the repo root, not home dir."""

    def test_project_root_is_repo_root(self):
        from pathlib import Path

        from backend.research.serenity_chokepoint import _PROJECT_ROOT

        # Repo root should contain pyproject.toml or AGENTS.md, NOT be home dir
        assert _PROJECT_ROOT != Path.home(), (
            "_PROJECT_ROOT must not be home directory (parents[3] was wrong for backend/research/)"
        )
        # parents[2] from backend/research/serenity_chokepoint.py => repo root
        # Verify it points to MingCang repo root (has AGENTS.md or backend/ subdir)
        assert (_PROJECT_ROOT / "backend").is_dir(), (
            f"_PROJECT_ROOT={_PROJECT_ROOT} does not contain 'backend/' — parents[2] may be wrong"
        )

    def test_skill_md_candidate_is_reachable(self):
        from backend.research.serenity_chokepoint import SKILL_MD_CANDIDATES

        # First candidate should point into the repo .pi/ tree
        first = SKILL_MD_CANDIDATES[0]
        assert first.exists(), (
            f"Primary SKILL.md candidate not found at {first} — check _PROJECT_ROOT"
        )


class TestSerenityEvidenceTierFromSourceTier:
    """F10 fix: evidence_tier schema enum must be derived from SourceTier."""

    def test_evidence_tier_enum_matches_source_tier(self):
        from backend.research.research_evidence_defs import SourceTier
        from backend.research.serenity_chokepoint import _SERENITY_TOOL

        schema_enum = _SERENITY_TOOL["input_schema"]["properties"]["evidence_tier"]["enum"]
        expected = [t.value for t in SourceTier]
        assert schema_enum == expected, (
            f"evidence_tier enum {schema_enum!r} must equal SourceTier values {expected!r}"
        )


class TestSerenityLLMOrderingF7:
    """F7 fix: runtime_readiness must be checked before get_provider is called."""

    def test_get_provider_not_called_when_llm_not_usable(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", True)

        monkeypatch.setattr(
            "backend.llm.runtime_readiness",
            lambda s: {"usable": False, "reason": "no API key"},
        )

        get_provider_calls = []

        def fake_get_provider():
            get_provider_calls.append("called")
            return MagicMock()

        monkeypatch.setattr("backend.llm.get_provider", fake_get_provider)

        import backend.research.serenity_chokepoint as sc_mod
        result = sc_mod.analyze("光模块供应链", ["300308"], db=None)
        assert result is None
        assert not get_provider_calls, (
            "get_provider must NOT be called when runtime_readiness reports not usable"
        )
