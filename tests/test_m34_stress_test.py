"""M34 Evidence-Bounded Stress Test — hermetic tests."""
from __future__ import annotations

from unittest.mock import MagicMock


def _mock_provider(outputs: list[dict]) -> MagicMock:
    """Build a fake LLMProvider with deterministic ordered side_effect."""
    provider = MagicMock()
    provider.complete_structured.side_effect = outputs
    return provider


# Re-use dossier fixtures from M33
def _full_dossier(symbol: str = "600519") -> dict:
    from tests.test_m33_research_case import _full_dossier as _fd
    return _fd(symbol)

def _minimal_dossier(symbol: str = "600519") -> dict:
    from tests.test_m33_research_case import _minimal_dossier as _md
    return _md(symbol)


def _full_case(symbol: str = "600519") -> dict:
    from backend.research.case import build_case
    return build_case(_full_dossier(symbol))


def _minimal_case(symbol: str = "600519") -> dict:
    from backend.research.case import build_case
    return build_case(_minimal_dossier(symbol))


# Deterministic LLM outputs for the five role calls
_FAKE_EVIDENCE_AUDITOR = {"findings": ["signal_fresh=False: signal is 10 days old"]}
_FAKE_BEAR_FALSIFIER = {"challenges": ["label=规避 but recommendation=买入"], "severity": "elevated"}
_FAKE_EXECUTION_RISK = {"execution_risks": ["pit_ok=False: no point-in-time tag on evidence"]}
_FAKE_METHODOLOGY = {"methodology_flags": ["calibration_status=degraded"], "confidence_adjustment": -0.1}
_FAKE_ADJUDICATOR = {
    "blockers": ["signal_fresh=False", "label=规避 but recommendation=买入"],
    "decision_deltas": ["consider reducing position_pct given stale signal"],
    "follow_up_questions": ["Has the long-term label been refreshed in the last 30 days?"],
    "confidence_adjustments": {"methodology": -0.1, "execution": -0.05},
    "overall_severity": "elevated",
    "verdict": "Evidence gaps and label conflict require human review before acting.",
}

_FIVE_FAKE_OUTPUTS = [
    _FAKE_EVIDENCE_AUDITOR,
    _FAKE_BEAR_FALSIFIER,
    _FAKE_EXECUTION_RISK,
    _FAKE_METHODOLOGY,
    _FAKE_ADJUDICATOR,
]


# ── Fallback path tests ──────────────────────────────────────────────────────

def test_structural_fallback_when_disabled(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", False)
    case = _full_case()
    result = run_stress_test(case)
    assert result["used_llm"] is False
    assert result["fallback_reason"] == "stress_test_disabled"
    assert isinstance(result["blockers"], list)
    assert result["decision_deltas"] == []
    assert result["follow_up_questions"] == []


def test_structural_fallback_when_no_provider(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: False)
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    case = _full_case()
    result = run_stress_test(case)
    assert result["used_llm"] is False
    assert result["fallback_reason"] == "no_llm_provider"


def test_structural_fallback_minimal_dossier_is_critical(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: False)
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    case = _minimal_case()
    result = run_stress_test(case)
    assert result["overall_severity"] == "critical"
    assert len(result["blockers"]) > 0


# ── LLM path tests ───────────────────────────────────────────────────────────

def test_full_llm_path_happy(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: True)
    case = _full_case()
    provider = _mock_provider(list(_FIVE_FAKE_OUTPUTS))
    result = run_stress_test(case, provider=provider)
    assert result["used_llm"] is True
    assert result["llm_valid"] is True
    assert result["overall_severity"] == "elevated"
    assert "signal_fresh=False" in result["blockers"]
    assert len(result["follow_up_questions"]) == 1
    assert result["confidence_adjustments"]["methodology"] <= 0.0
    assert provider.complete_structured.call_count == 5


def test_confidence_adjustments_clamped_to_non_positive(monkeypatch):
    """LLM must not be able to raise scores via stress-test output."""
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: True)
    bad_adj = dict(_FAKE_ADJUDICATOR)
    bad_adj["confidence_adjustments"] = {"methodology": 0.5}  # LLM tries to raise score
    outputs = list(_FIVE_FAKE_OUTPUTS[:4]) + [bad_adj]
    case = _full_case()
    result = run_stress_test(case, provider=_mock_provider(outputs))
    assert result["confidence_adjustments"]["methodology"] == 0.0  # clamped to 0


def test_adjudicator_empty_falls_back_to_specialist_aggregate(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: True)
    # Adjudicator returns {} — triggers structural assembly from specialist outputs
    outputs = list(_FIVE_FAKE_OUTPUTS[:4]) + [{}]
    case = _full_case()
    result = run_stress_test(case, provider=_mock_provider(outputs))
    assert result["used_llm"] is True
    assert result["llm_valid"] is False  # adjudicator was invalid
    assert len(result["blockers"]) > 0  # aggregated from specialists


def test_all_roles_empty_returns_structural_fallback(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: True)
    outputs = [{} for _ in range(5)]
    case = _full_case()
    result = run_stress_test(case, provider=_mock_provider(outputs))
    assert result["used_llm"] is False
    assert result["fallback_reason"] == "llm_returned_empty"


def test_invalid_case_raises_input_error():
    import pytest

    from backend.research.stress_test import StressTestInputError, run_stress_test
    with pytest.raises(StressTestInputError):
        run_stress_test({"symbol": "600519"})  # missing quality_gate


def test_role_outputs_keyed_correctly(monkeypatch):
    import backend.research.stress_test as st_mod
    from backend.research.stress_test import run_stress_test
    monkeypatch.setattr(st_mod.settings, "stress_test_enabled", True)
    monkeypatch.setattr(st_mod, "has_runtime_llm_provider", lambda _=None: True)
    case = _full_case()
    result = run_stress_test(case, provider=_mock_provider(list(_FIVE_FAKE_OUTPUTS)))
    assert set(result["role_outputs"].keys()) == {
        "evidence_auditor", "bear_falsifier",
        "execution_risk_reviewer", "methodology_base_rate_reviewer", "adjudicator"
    }
