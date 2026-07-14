import json

from sqlalchemy import text


def _insert_run(test_db, run_id: int, *, report_path: str, symbol: str = "600183") -> None:
    test_db.execute(text("""
        INSERT INTO decision_runs(
            id, run_id, run_type, symbol, as_of, profile, rule_version,
            input_snapshot_json, notes, created_at
        ) VALUES(
            :id, :run_id, 'deep_research', :symbol, '2026-07-15',
            'deep_research_v1', 'deep_research_v1', :snapshot, :notes,
            '2026-07-15 09:00:00'
        )
    """), {
        "id": run_id,
        "run_id": f"deep_research:{symbol}:2026-07-15:{run_id}",
        "symbol": symbol,
        "snapshot": json.dumps({
            "report_path": report_path,
            "topic": "覆铜板研究",
            "symbols": [symbol],
            "gate_status": "pass",
            "source_count": 8,
            "sections": [{"role": "source_auditor"}],
        }, ensure_ascii=False),
        "notes": "真实报告已完成，仅用于研究 trace。",
    })
    test_db.commit()


def test_capture_is_dry_run_idempotent_and_deduplicates_reports(test_db):
    from backend.memory.evolution_trace import ensure_schema
    from backend.tools.m57_trace_capture import capture_decision_runs

    ensure_schema(test_db)
    _insert_run(test_db, 91001, report_path="/tmp/report-a.md")
    _insert_run(test_db, 91002, report_path="/tmp/report-a.md")

    dry_run = capture_decision_runs(test_db, [91001, 91002])
    assert dry_run["created"] == 0
    assert dry_run["unique_reports"] == 1
    assert test_db.execute(text("SELECT COUNT(*) FROM evolution_traces")).scalar() == 0

    applied = capture_decision_runs(test_db, [91001, 91002], apply=True)
    assert applied["created"] == 1
    again = capture_decision_runs(test_db, [91001, 91002], apply=True)
    assert again["created"] == 0
    row = test_db.execute(text("SELECT * FROM evolution_traces")).mappings().one()
    payload = json.loads(row["payload_json"])
    assert row["source_type"] == "decision_run_report"
    assert payload["decision_run_ids"] == [91001, 91002]
    assert "source_auditor" in payload["section_roles"]
    assert test_db.execute(text(
        "SELECT COUNT(*) FROM memory_promotion_candidates WHERE source_trust='trusted'"
    )).scalar() == 0
