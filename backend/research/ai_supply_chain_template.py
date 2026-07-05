"""[ATLAS-dormant] [dormant] 消费者: backend/api/routes/research.py, backend/research/theme_hypothesis_engine.py; 归 M57 记忆基础设施保留,勿在新功能中引用.
AI supply-chain theme template helpers.

Pure structure layer for Atlas theme hypotheses.  No LLM calls, no network
calls, no scoring writes, and no production-signal side effects.
"""
from __future__ import annotations

from typing import Any

from backend.research.research_evidence_defs import SourceTier

SCHEMA_VERSION = "ai_supply_chain.v1"
TEMPLATE_NAME = "ai_supply_chain"
SIGNAL_IMPACT_NONE = "none"

FORBIDDEN_TEMPLATE_KEYS = {
    "buy_score",
    "composite_score",
    "direction",
    "entry_signal",
    "position_pct",
    "predicted_move",
    "price_target",
    "recommendation",
    "signal_score",
    "target_position_pct",
}

CHAIN_FIELDS = (
    "new_capability",
    "new_bottleneck",
    "payer",
    "spend_source",
    "profit_pool",
    "pricing_gap",
)
SOURCE_TIER_VALUES = {tier.value for tier in SourceTier}
SOURCE_TIER_ALIASES = {
    "social": SourceTier.social_lead.value,
}


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in _as_list(values):
        text = _as_str(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _normalize_source_tier(value: Any, *, field: str = "source_tier") -> str | None:
    text = _as_str(value).lower()
    if not text:
        return None
    text = SOURCE_TIER_ALIASES.get(text, text)
    if text not in SOURCE_TIER_VALUES:
        raise ValueError(
            f"{field} must be one of {sorted(SOURCE_TIER_VALUES)}; got {value!r}"
        )
    return text


def _normalize_optional_bool(raw: dict[str, Any], field: str) -> bool | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"chain_layers.{field} must be a boolean")
    return value


def _normalize_chain_layers(layers: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in _as_list(layers):
        if not isinstance(raw, dict):
            continue
        layer = _as_str(raw.get("layer"))
        if not layer:
            continue
        item: dict[str, Any] = {"layer": layer}
        for field in ("forced_demand", "size_mismatch", "no_substitute"):
            value = _normalize_optional_bool(raw, field)
            if value is not None:
                item[field] = value
        outside_voice = _as_str(raw.get("outside_voice"))
        if outside_voice:
            item["outside_voice"] = outside_voice
        evidence = _as_str(raw.get("evidence"))
        if evidence:
            item["evidence"] = evidence
        linked_symbols = _unique_strings(raw.get("linked_symbols"))
        if linked_symbols:
            item["linked_symbols"] = linked_symbols
        source_tier = _normalize_source_tier(raw.get("source_tier"), field="chain_layers.source_tier")
        if source_tier:
            item["source_tier"] = source_tier
        normalized.append(item)
    return normalized


def _normalize_source_freshness(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("source_freshness must be an object")
    normalized: dict[str, Any] = {}
    for field in ("as_of", "latest_source_date", "status", "notes"):
        text = _as_str(value.get(field))
        if text:
            normalized[field] = text
    for field in ("max_source_age_days", "stale_source_count"):
        if value.get(field) is None:
            continue
        if not isinstance(value[field], int) or value[field] < 0:
            raise ValueError(f"source_freshness.{field} must be a non-negative integer")
        normalized[field] = value[field]
    return normalized


def _ensure_no_forbidden_keys(value: Any, *, path: str = "template_payload") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in FORBIDDEN_TEMPLATE_KEYS:
                raise ValueError(f"{path}.{key_text} is not allowed in {TEMPLATE_NAME}")
            _ensure_no_forbidden_keys(nested, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _ensure_no_forbidden_keys(nested, path=f"{path}[{index}]")


def _normalize_evidence_cards(cards: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in _as_list(cards):
        if not isinstance(raw, dict):
            continue
        claim = _as_str(raw.get("claim"))
        if not claim:
            continue
        normalized.append({
            "claim": claim,
            "source": _as_str(raw.get("source")) or None,
            "source_tier": _normalize_source_tier(
                raw.get("source_tier"),
                field="evidence_cards.source_tier",
            ),
            "source_date": _as_str(raw.get("source_date")) or None,
            "status": _as_str(raw.get("status")) or "unverified",
            "gap": _as_str(raw.get("gap")) or None,
            "linked_symbols": _unique_strings(raw.get("linked_symbols")),
        })
    return normalized


def _normalize_beneficiary_tiers(tiers: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in _as_list(tiers):
        if not isinstance(raw, dict):
            continue
        symbol = _as_str(raw.get("symbol"))
        if not symbol:
            continue
        tier = raw.get("tier")
        if tier not in (1, 2, 3):
            raise ValueError(f"beneficiary tier must be 1, 2, or 3; got {tier!r}")
        normalized.append({
            "symbol": symbol,
            "tier": tier,
            "rationale": _as_str(raw.get("rationale")),
        })
    return normalized


def normalize_ai_supply_chain_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a user/API payload into the Atlas AI supply-chain contract."""
    raw = dict(payload or {})
    _ensure_no_forbidden_keys(raw)

    raw_chain_value = raw.get("chain")
    raw_chain: dict[str, Any] = raw_chain_value if isinstance(raw_chain_value, dict) else {}
    chain = {
        field: _as_str(raw.get(field) or raw_chain.get(field))
        for field in CHAIN_FIELDS
    }
    catalysts_value = raw.get("catalysts")
    catalysts: dict[str, Any] = catalysts_value if isinstance(catalysts_value, dict) else {}
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "template": TEMPLATE_NAME,
        "observe_only": True,
        "signal_impact": SIGNAL_IMPACT_NONE,
        "not_a_buy_score": True,
        "chain": chain,
        "chain_layers": _normalize_chain_layers(raw.get("chain_layers")),
        "source_tier": _normalize_source_tier(raw.get("source_tier")),
        "substitute_risk": _as_str(raw.get("substitute_risk")) or None,
        "source_freshness": _normalize_source_freshness(raw.get("source_freshness")),
        "catalysts": {
            "30d": _unique_strings(catalysts.get("30d") or raw.get("catalysts_30d")),
            "90d": _unique_strings(catalysts.get("90d") or raw.get("catalysts_90d")),
            "180d": _unique_strings(catalysts.get("180d") or raw.get("catalysts_180d")),
        },
        "evidence_cards": _normalize_evidence_cards(raw.get("evidence_cards")),
        "evidence_gaps": _unique_strings(raw.get("evidence_gaps")),
        "invalidation_conditions": _unique_strings(raw.get("invalidation_conditions")),
        "follow_up_metrics": _unique_strings(raw.get("follow_up_metrics")),
        "beneficiary_tiers": _normalize_beneficiary_tiers(raw.get("beneficiary_tiers")),
    }
    return normalized


def hypothesis_fields_from_payload(payload: dict[str, Any]) -> dict[str, list]:
    """Map a normalized template payload into existing ThemeHypothesis fields."""
    evidence_gaps = list(payload.get("evidence_gaps") or [])
    for card in payload.get("evidence_cards") or []:
        gap = card.get("gap")
        if gap and gap not in evidence_gaps:
            evidence_gaps.append(gap)
    return {
        "beneficiary_tiers": list(payload.get("beneficiary_tiers") or []),
        "evidence_gaps": evidence_gaps,
        "invalidation_conditions": list(payload.get("invalidation_conditions") or []),
    }


def forward_thesis_fields_from_payload(payload: dict[str, Any]) -> dict[str, list]:
    """Map a normalized template payload into existing ForwardThesis fields."""
    manifest = []
    for card in payload.get("evidence_cards") or []:
        manifest.append({
            "kind": "ai_supply_chain_evidence_card",
            "ref": card.get("source") or card.get("claim"),
            "as_of": card.get("source_date"),
            "summary": card.get("claim"),
            "source_tier": card.get("source_tier") or payload.get("source_tier"),
        })
    return {
        "evidence_manifest": manifest,
        "follow_up_metrics": list(payload.get("follow_up_metrics") or []),
        "invalidation_conditions": list(payload.get("invalidation_conditions") or []),
    }
