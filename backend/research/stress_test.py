"""M34 Evidence-Bounded Stress Test — single-pass red-team review of a ResearchCase."""
from __future__ import annotations

import json
from datetime import datetime

from jsonschema import ValidationError, validate

from backend.config import settings
from backend.llm import get_provider, has_runtime_llm_provider


class StressTestUnavailable(RuntimeError):
    """Raised when the runtime LLM provider is not configured."""


class StressTestInputError(RuntimeError):
    """Raised when the case dict is missing required keys."""


# ── Tool schema constants (Anthropic input_schema convention) ─────────────────

_EVIDENCE_AUDITOR_TOOL = {
    "name": "evidence_auditor",
    "description": "Audit quality_gate and validity_card for structural gaps",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One item per failing check or structural gap; cite the check key and its value. Max 6 items.",
            },
        },
        "required": ["findings"],
    },
}

_BEAR_FALSIFIER_TOOL = {
    "name": "bear_falsifier",
    "description": "Identify the most damaging contradiction between evidence and current recommendation",
    "input_schema": {
        "type": "object",
        "properties": {
            "challenges": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Named contradictions between evidence fields and recommendation. Max 3 items.",
            },
            "severity": {
                "type": "string",
                "enum": ["critical", "elevated", "moderate"],
                "description": "Severity of the most damaging challenge.",
            },
        },
        "required": ["challenges", "severity"],
    },
}

_EXECUTION_RISK_REVIEWER_TOOL = {
    "name": "execution_risk_reviewer",
    "description": "Flag execution-level reliability risks from provenance and constraint fields",
    "input_schema": {
        "type": "object",
        "properties": {
            "execution_risks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Each item links a provenance/constraint field name to its implication. Max 3 items.",
            },
        },
        "required": ["execution_risks"],
    },
}

_METHODOLOGY_REVIEWER_TOOL = {
    "name": "methodology_base_rate_reviewer",
    "description": "Assess calibration quality and base-rate concerns",
    "input_schema": {
        "type": "object",
        "properties": {
            "methodology_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Calibration and base-rate concerns that inflate confidence. Max 3 items.",
            },
            "confidence_adjustment": {
                "type": "number",
                "description": "Downward confidence nudge in [-0.3, 0.0]. May not be positive.",
            },
        },
        "required": ["methodology_flags", "confidence_adjustment"],
    },
}

_ADJUDICATOR_TOOL = {
    "name": "stress_test_adjudicator",
    "description": "Synthesize the four specialist outputs into a final stress-test verdict",
    "input_schema": {
        "type": "object",
        "properties": {
            "blockers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Merged, deduplicated blockers ranked by severity.",
            },
            "decision_deltas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Advisory changes a human reviewer should consider. Max 4 items.",
            },
            "follow_up_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Questions a human reviewer should answer before acting. Max 4 items.",
            },
            "confidence_adjustments": {
                "type": "object",
                "description": "Dict keyed by aspect (methodology/execution/evidence); values in [-0.3, 0.0].",
            },
            "overall_severity": {
                "type": "string",
                "enum": ["critical", "elevated", "moderate", "low"],
            },
            "verdict": {
                "type": "string",
                "description": "One-sentence synthesis.",
            },
        },
        "required": ["blockers", "decision_deltas", "follow_up_questions",
                     "confidence_adjustments", "overall_severity", "verdict"],
    },
}


def _validate_tool_output(data: dict | None, tool: dict) -> tuple[bool, str | None]:
    """Validate LLM response against tool input_schema. Returns (valid, err_str|None)."""
    if not isinstance(data, dict):
        return False, "missing_or_non_dict_output"
    try:
        validate(instance=data, schema=tool["input_schema"])
    except ValidationError as exc:
        path = ".".join(str(p) for p in exc.path) or "<root>"
        return False, f"schema:{tool.get('name', '?')}:{path}:{exc.message}"
    return True, None


def _structural_fallback(case: dict, fallback_reason: str) -> dict:
    """Return a structural-only stress result derived from quality_gate/validity_card."""
    qg = case.get("quality_gate") or {}
    vc = case.get("validity_card") or {}
    blockers = list(qg.get("blockers") or []) + list(vc.get("missing_provenance") or [])
    blockers = list(dict.fromkeys(blockers))  # deduplicate, preserve order
    warnings = qg.get("warnings") or []
    if blockers:
        severity = "critical"
    elif warnings:
        severity = "elevated"
    else:
        severity = "low"
    return {
        "symbol": case.get("symbol", ""),
        "as_of": case.get("as_of"),
        "used_llm": False,
        "llm_valid": False,
        "overall_severity": severity,
        "blockers": blockers,
        "decision_deltas": [],
        "follow_up_questions": [],
        "confidence_adjustments": {},
        "role_outputs": {},
        "fallback_reason": fallback_reason,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _resolve_provider(provider):
    """Return injected provider or lazily resolve the global singleton."""
    return provider if provider is not None else get_provider()


def _build_case_context_prompt(case: dict) -> str:
    """Serialise the ResearchCase envelope into a compact LLM-readable context block."""
    qg = case.get("quality_gate") or {}
    vc = case.get("validity_card") or {}
    # Keep prompt size bounded: only surface the fields each role needs
    payload = {
        "symbol": case.get("symbol"),
        "as_of": case.get("as_of"),
        "ready": case.get("ready"),
        "quality_gate": {
            "checks": qg.get("checks"),
            "blockers": qg.get("blockers"),
            "warnings": qg.get("warnings"),
            "gate_pass": qg.get("gate_pass"),
        },
        "validity_card": {
            "status": vc.get("status"),
            "missing_provenance": vc.get("missing_provenance"),
            "card_pass": vc.get("card_pass"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


_SYSTEM_PROMPT = (
    "你是 StockSage 的红队审核员。你的输出仅为咨询意见，"
    "不得直接修改官方信号、信号数据库或任何受信内存。"
)


def run_stress_test(case: dict, *, provider=None) -> dict:
    """Red-team review of a ResearchCase envelope. Advisory only — never writes to DB.

    Parameters
    ----------
    case:
        The dict produced by build_case(dossier).  Must have keys
        'symbol', 'quality_gate', 'validity_card'.
    provider:
        Optional LLMProvider instance for injection in tests.  If None,
        get_provider() is called lazily inside the function after all guards.
    """
    if not case or "quality_gate" not in case or "validity_card" not in case:
        raise StressTestInputError("case dict must contain quality_gate and validity_card")

    if not settings.stress_test_enabled:
        return _structural_fallback(case, fallback_reason="stress_test_disabled")

    if not has_runtime_llm_provider(settings):
        return _structural_fallback(case, fallback_reason="no_llm_provider")

    _provider = _resolve_provider(provider)
    context = _build_case_context_prompt(case)

    role_outputs: dict[str, dict] = {}
    all_valid = True

    _ROLES = [
        ("evidence_auditor",               _EVIDENCE_AUDITOR_TOOL,        400),
        ("bear_falsifier",                 _BEAR_FALSIFIER_TOOL,          350),
        ("execution_risk_reviewer",        _EXECUTION_RISK_REVIEWER_TOOL, 350),
        ("methodology_base_rate_reviewer", _METHODOLOGY_REVIEWER_TOOL,    350),
    ]

    for role_name, tool, max_tokens in _ROLES:
        prompt = (
            f"ResearchCase 摘要：\n{context}\n\n"
            f"你是 {role_name} 角色，请严格按工具 schema 输出。"
        )
        data = _provider.complete_structured(
            prompt=prompt, tool=tool,
            system=_SYSTEM_PROMPT,
            max_tokens=max_tokens, model_tier="fast",
        )
        try:
            from backend.ops.llm_usage import log_llm_usage
            log_llm_usage("red_team_review", prompt, json.dumps(data or {}))
        except Exception:
            pass
        valid, _err = _validate_tool_output(data, tool)
        if not valid or not data:
            all_valid = False
            role_outputs[role_name] = {}
        else:
            role_outputs[role_name] = data

    if not any(role_outputs.values()):
        return _structural_fallback(case, fallback_reason="llm_returned_empty")

    # Build adjudicator prompt from role outputs collected so far
    specialist_summary = json.dumps(role_outputs, ensure_ascii=False, sort_keys=True)
    adj_prompt = (
        f"ResearchCase 摘要：\n{context}\n\n"
        f"四位专家审核输出：\n{specialist_summary}\n\n"
        "你是最终裁定者，请综合以上内容输出最终红队审核结果。"
    )
    adj_data = _provider.complete_structured(
        prompt=adj_prompt, tool=_ADJUDICATOR_TOOL,
        system=_SYSTEM_PROMPT,
        max_tokens=600, model_tier="capable",
    )
    try:
        from backend.ops.llm_usage import log_llm_usage
        log_llm_usage("red_team_review", adj_prompt, json.dumps(adj_data or {}))
    except Exception:
        pass
    adj_valid, _adj_err = _validate_tool_output(adj_data, _ADJUDICATOR_TOOL)
    if not adj_valid or not adj_data:
        # Adjudicator failed: assemble structurally from specialist outputs
        all_valid = False
        blockers: list[str] = []
        for role_name in ("evidence_auditor", "bear_falsifier", "execution_risk_reviewer", "methodology_base_rate_reviewer"):
            rd = role_outputs.get(role_name) or {}
            blockers += rd.get("findings", []) + rd.get("challenges", []) + rd.get("execution_risks", []) + rd.get("methodology_flags", [])
        blockers = list(dict.fromkeys(blockers))
        severity = "elevated" if blockers else "low"
        adj_data = {
            "blockers": blockers,
            "decision_deltas": [],
            "follow_up_questions": [],
            "confidence_adjustments": {},
            "overall_severity": severity,
            "verdict": "adjudicator call failed; severity estimated from specialist outputs",
        }
    role_outputs["adjudicator"] = adj_data

    # Clamp confidence_adjustments to (-0.3, 0.0] — stress test must not raise scores
    raw_adj = dict(adj_data.get("confidence_adjustments") or {})
    clamped = {k: max(-0.3, min(0.0, float(v))) for k, v in raw_adj.items() if isinstance(v, (int, float))}

    return {
        "symbol": case.get("symbol", ""),
        "as_of": case.get("as_of"),
        "used_llm": True,
        "llm_valid": all_valid and adj_valid,
        "overall_severity": adj_data.get("overall_severity", "low"),
        "blockers": list(adj_data.get("blockers") or []),
        "decision_deltas": list(adj_data.get("decision_deltas") or []),
        "follow_up_questions": list(adj_data.get("follow_up_questions") or []),
        "confidence_adjustments": clamped,
        "role_outputs": role_outputs,
        "fallback_reason": None,
        "generated_at": datetime.utcnow().isoformat(),
    }
