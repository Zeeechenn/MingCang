from __future__ import annotations


def _case():
    return {
        "id": "case-1",
        "symbol": "000001",
        "industry": "行业一",
        "as_of": "2026-07-15",
        "question": "证据支持什么？",
        "evidence_snapshot": {"digest": "abc", "text": "冻结证据正文"},
        "memory_context": "[stock_memory_items:1] 历史记忆",
        "memory_refs": ["stock_memory_items:1"],
        "output_template_version": "m65_research_answer.v1",
        "arms": {
            arm: {"response": f"{arm} response", "cost_units": 100}
            for arm in ("base", "memory", "serenity", "both")
        },
    }


def test_evidence_extraction_excludes_prior_conclusions():
    from backend.tools.m65_phase2_run import _extract_sections

    report = """# 报告

## 核心结论
不应回灌的旧结论

## 个股快照
收盘价证据

## 来源审计
- 来源标题｜2026-07-14
"""
    evidence = _extract_sections(report)

    assert "旧结论" not in evidence
    assert "收盘价证据" in evidence
    assert "来源标题" in evidence


def test_arm_prompts_change_only_permitted_context():
    from backend.tools.m65_phase2_run import _research_prompt

    case = _case()
    base = _research_prompt(case, "base")
    memory = _research_prompt(case, "memory")
    serenity = _research_prompt(case, "serenity")
    both = _research_prompt(case, "both")

    assert "冻结证据正文" in base
    assert "历史记忆" not in base
    assert "历史记忆" in memory
    assert "供应链瓶颈方法镜头" in serenity
    assert "历史记忆" in both
    assert "供应链瓶颈方法镜头" in both


def test_factorial_effects_separate_memory_serenity_and_interaction():
    import pytest

    from backend.tools.m65_phase2_run import _factorial_effects

    case = _case()
    fixture = {"cases": [case]}
    metrics = (
        "source_fidelity",
        "key_fact_coverage",
        "contradiction_handling",
        "falsifiability",
        "hallucination_error_rate",
    )
    values = {"base": 0.4, "memory": 0.5, "serenity": 0.6, "both": 0.8}
    scores = {
        "cases": [{
            "case_id": "case-1",
            "arms": {
                arm: {metric: value for metric in metrics}
                for arm, value in values.items()
            },
        }],
    }

    result = _factorial_effects(fixture, scores)

    effects = result["averages"]["source_fidelity"]
    assert effects["serenity_main"] == pytest.approx(0.25)
    assert effects["memory_main"] == pytest.approx(0.15)
    assert effects["interaction"] == pytest.approx(0.1)


def test_codex_command_is_isolated_read_only_and_schema_bound(tmp_path):
    from backend.tools.m65_phase2_run import _codex_command

    schema = tmp_path / "schema.json"
    command = _codex_command(schema)

    assert "read-only" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--output-schema" in command
    assert str(schema) in command
    assert command.count("--disable") >= 6


def test_runner_has_no_production_or_retired_serenity_imports():
    import inspect

    import backend.tools.m65_phase2_run as module

    source = inspect.getsource(module)
    assert "backend.scheduler" not in source
    assert "serenity_chokepoint" not in source
    assert "SessionLocal" not in source
