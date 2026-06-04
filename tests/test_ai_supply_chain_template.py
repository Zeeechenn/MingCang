"""AI supply-chain template helper tests."""
from __future__ import annotations

import pytest


def _payload() -> dict:
    return {
        "new_capability": "推理成本下降带来企业应用调用量上升",
        "new_bottleneck": "HBM 与数据中心电力",
        "payer": "云厂商与企业客户",
        "spend_source": "AI capex 与推理预算",
        "profit_pool": "具备认证与产能约束的上游供应链",
        "pricing_gap": "市场仍按训练算力叙事定价",
        "catalysts_30d": ["云厂商 capex 指引"],
        "catalysts_90d": ["HBM 合约价"],
        "catalysts_180d": ["800G/1.6T 订单兑现"],
        "evidence_cards": [{
            "claim": "HBM 供需继续紧张",
            "source": "company_call",
            "source_date": "2026-06-01",
            "status": "needs_verification",
            "gap": "缺少交期与客户集中度数据",
            "linked_symbols": ["300308"],
        }],
        "evidence_gaps": ["缺少客户订单明细"],
        "invalidation_conditions": ["云厂商下修 capex"],
        "follow_up_metrics": ["HBM contract price"],
        "beneficiary_tiers": [{"symbol": "300308", "tier": 1, "rationale": "直接受益"}],
    }


def test_ai_supply_chain_template_normalizes_payload():
    from backend.research.ai_supply_chain_template import normalize_ai_supply_chain_payload

    result = normalize_ai_supply_chain_payload(_payload())

    assert result["schema_version"] == "ai_supply_chain.v1"
    assert result["observe_only"] is True
    assert result["signal_impact"] == "none"
    assert result["not_a_buy_score"] is True
    assert result["chain"]["new_bottleneck"] == "HBM 与数据中心电力"
    assert result["catalysts"]["90d"] == ["HBM 合约价"]
    assert result["evidence_cards"][0]["linked_symbols"] == ["300308"]


def test_ai_supply_chain_template_rejects_scoring_fields():
    from backend.research.ai_supply_chain_template import normalize_ai_supply_chain_payload

    bad = _payload()
    bad["composite_score"] = 88
    with pytest.raises(ValueError, match="composite_score"):
        normalize_ai_supply_chain_payload(bad)


def test_ai_supply_chain_template_maps_existing_fields():
    from backend.research.ai_supply_chain_template import (
        forward_thesis_fields_from_payload,
        hypothesis_fields_from_payload,
        normalize_ai_supply_chain_payload,
    )

    payload = normalize_ai_supply_chain_payload(_payload())
    hyp_fields = hypothesis_fields_from_payload(payload)
    thesis_fields = forward_thesis_fields_from_payload(payload)

    assert hyp_fields["beneficiary_tiers"][0]["symbol"] == "300308"
    assert "云厂商下修 capex" in hyp_fields["invalidation_conditions"]
    assert "缺少交期与客户集中度数据" in hyp_fields["evidence_gaps"]
    assert thesis_fields["evidence_manifest"][0]["kind"] == "ai_supply_chain_evidence_card"
    assert "HBM contract price" in thesis_fields["follow_up_metrics"]
