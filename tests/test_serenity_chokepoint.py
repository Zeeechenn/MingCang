"""Tests for backend/research/serenity_chokepoint.py — M50 Phase 1 / M55 retirement.

M55 retired the independent LLM-driven pipeline (`_SERENITY_TOOL` schema +
the structured-LLM body of `analyze()`) per
`docs/dev/M55_SERENITY_CONVERGENCE_PLAN.md` section ④. What is validated
here now:

- `SerenityChokepointReport` has no score/label_vote/trading fields and is
  not a `LongTermReport` subclass (isolation invariants carried forward
  unchanged from M50).
- `analyze()` is a deprecated no-op: it always returns None and never
  touches settings, LLM readiness, providers, or the DB, regardless of the
  `long_term_serenity_enabled` flag.
- No forbidden aggregation/signal imports.
- SKILL.md loader / `_PROJECT_ROOT` plumbing still resolves correctly.
"""
from unittest.mock import MagicMock

import pytest


class TestSerenityReportNoTradingFields:
    """Serenity report dataclass must not contain scoring / trading fields."""

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


class TestSerenityAnalyzeRetired:
    """M55: analyze() is a deprecated no-op — always None, never touches LLM/DB."""

    def test_analyze_returns_none_when_disabled(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", False)

        from backend.research.serenity_chokepoint import analyze
        with pytest.deprecated_call():
            result = analyze("光模块供应链", ["300308"], db=None)
        assert result is None

    def test_analyze_returns_none_even_when_enabled(self, monkeypatch):
        """Retired: flag no longer matters — analyze() always returns None."""
        from backend.config import settings
        monkeypatch.setattr(settings, "long_term_serenity_enabled", True)

        from backend.research.serenity_chokepoint import analyze
        with pytest.deprecated_call():
            result = analyze("光模块供应链", ["300308"], db=None)
        assert result is None

    def test_analyze_does_not_call_llm(self, monkeypatch):
        call_tracker = []

        def fake_get_provider():
            call_tracker.append("called")
            return MagicMock()

        monkeypatch.setattr("backend.llm.get_provider", fake_get_provider)

        from backend.research.serenity_chokepoint import analyze
        with pytest.deprecated_call():
            analyze("光模块供应链", ["300308"], db=None)
        assert not call_tracker, "get_provider must never be called — analyze() is retired"

    def test_analyze_does_not_write_db(self, monkeypatch):
        """analyze() must not write anything to DB — it is a pure no-op."""
        mock_db = MagicMock()

        from backend.research.serenity_chokepoint import analyze
        with pytest.deprecated_call():
            result = analyze("光模块供应链", [], db=mock_db)

        assert result is None
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_analyze_emits_deprecation_warning(self):
        from backend.research.serenity_chokepoint import analyze

        with pytest.warns(DeprecationWarning):
            analyze("光模块供应链", ["300308"], db=None)


class TestSerenityIndependentPipelineRemoved:
    """M55: the duplicate independent-analyzer pipeline must be gone."""

    def test_serenity_tool_schema_removed(self):
        import backend.research.serenity_chokepoint as sc_mod

        assert not hasattr(sc_mod, "_SERENITY_TOOL"), (
            "_SERENITY_TOOL (independent structured-LLM schema) must be "
            "removed per M55 retirement — it duplicated the ATLAS spine"
        )


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
