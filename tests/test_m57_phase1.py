from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def test_evolution_trace_records_namespace_and_as_of(test_db):
    from backend.memory.evolution_trace import NAMESPACE_RESEARCH_THESIS, record_trace

    row = record_trace(
        test_db,
        trace_type="unit.hit",
        namespace=NAMESPACE_RESEARCH_THESIS,
        subject="300308",
        symbols=["300308"],
        themes=["CPO"],
        content="召回了 CPO 研究论点",
        as_of="2026-07-05",
        stale_after="2026-08-05",
        event_time="2026-07-05T15:00:00",
    )

    stored = test_db.execute(text("SELECT * FROM evolution_traces WHERE id = :id"), {"id": row["id"]}).mappings().one()
    assert stored["namespace"] == "研究论点"
    assert stored["as_of"] == "2026-07-05"
    assert stored["stale_after"] == "2026-08-05"
    assert stored["event_time"] == "2026-07-05T15:00:00"
    assert stored["ingestion_time"]
    assert stored["invalidated_at"] is None


def test_task_capsule_write_latest_roundtrip(test_db):
    from backend.memory.task_capsule import latest_task_capsule, write_task_capsule

    written = write_task_capsule(
        test_db,
        capsule_id="unit:capsule",
        task_type="research",
        symbols=["300308"],
        themes=["CPO"],
        goal="复核 CPO 业绩兑现",
        confirmed_facts=[str(idx) for idx in range(8)],
        decisions=["保持观察"],
        open_loops=["等待财报"],
        next_actions=["读取最新研报"],
        used_memory_refs=["stock:1"],
        artifact_refs=["paper_trading/m63_out/research_300308.md"],
        trust_state="pending",
        as_of="2026-07-05",
    )
    latest = latest_task_capsule(test_db)

    assert written["capsule_id"] == "unit:capsule"
    assert latest is not None
    assert latest["goal"] == "复核 CPO 业绩兑现"
    assert latest["symbols_json"] == ["300308"]
    assert latest["themes_json"] == ["CPO"]
    assert latest["confirmed_facts"] == ["0", "1", "2", "3", "4"]
    assert latest["trust_state"] == "pending"


def test_context_governor_packs_layers_dedups_clips_and_traces(test_db):
    from backend.memory.context_governor import ContextBudget, build_agent_context
    from backend.memory.stock_memory import create_stock_memory

    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="CPO 论点一。" * 80,
        source_type="unit",
        source_ref="m57:1",
        importance=5,
    )
    create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="thesis",
        summary="CPO 论点重复项。",
        source_type="unit",
        source_ref="m57:2",
        importance=4,
    )

    packed = build_agent_context(
        test_db,
        task_type="m59_discretion",
        query="CPO 复核",
        symbol="300308",
        budget=ContextBudget(total=400, resident=120, retrieval=180),
    )

    assert "【常驻记忆块】" in packed["text"]
    assert "【检索记忆块】" in packed["text"]
    assert packed["token_estimate"] <= 410
    assert packed["omitted"]
    assert packed["trace_id"]
    trace = test_db.execute(
        text("SELECT trace_type, payload_json FROM evolution_traces WHERE id = :id"),
        {"id": packed["trace_id"]},
    ).mappings().one()
    payload = json.loads(trace["payload_json"])
    assert trace["trace_type"] == "context_governor.pack"
    assert payload["omitted"]
    assert payload["token_estimate"] == packed["token_estimate"]


def _run_cli(repo: Path, db_url: str, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "backend.agent.cli", *args],
        cwd=repo,
        env={"PYTHONPATH": str(repo), "DATABASE_URL": db_url, "MINGCANG_AGENT_MODE": "local"},
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_memory_correct_archive_action_dry_run_and_confirm_paths(tmp_path, test_db):
    from backend.agent.action_registry import execute_registered_action
    from backend.memory.stock_memory import create_stock_memory

    row = create_stock_memory(
        test_db,
        symbol="300308",
        memory_type="risk",
        summary="旧风险文本",
        source_type="unit",
        source_ref="m57:correct",
    )
    repo = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / f'm57-{uuid.uuid4().hex}.db'}"
    dry = _run_cli(
        repo,
        db_url,
        "action",
        "memory.correct",
        "--payload-json",
        '{"id":1,"text":"修正后文本"}',
    )
    assert dry.returncode == 0, dry.stderr
    dry_payload = json.loads(dry.stdout)
    assert dry_payload["dry_run"] is True
    assert dry_payload["requires_confirmation"] is True

    corrected = execute_registered_action(
        "memory.correct",
        {"id": row["id"], "text": "修正后风险文本", "reason": "用户纠正"},
        test_db,
    )
    archived = execute_registered_action(
        "memory.archive",
        {"id": row["id"], "reason": "过期"},
        test_db,
    )
    stored = test_db.execute(
        text("SELECT summary, status FROM stock_memory_items WHERE id = :id"),
        {"id": row["id"]},
    ).mappings().one()
    traces = test_db.execute(text("SELECT trace_type FROM evolution_traces ORDER BY id")).scalars().all()

    assert corrected["summary"] == "修正后风险文本"
    assert archived["status"] == "archived"
    assert stored["summary"] == "修正后风险文本"
    assert stored["status"] == "archived"
    assert {"memory.correct", "memory.archive"} <= set(traces)


def test_m63_postmarket_writes_task_capsule_with_fake_steps(tmp_path):
    from backend.tools import m63_daily

    db_path = tmp_path / "m63.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE signals(id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, rule_version TEXT)")
        con.commit()

    report = m63_daily.build_postmarket_report(
        db_path=db_path,
        as_of="2026-07-05",
        no_llm=True,
        queue_path=tmp_path / "queue.json",
        history_path=tmp_path / "history.json",
        step_overrides={
            "m61_backfill_drip": lambda: {},
            "m60_watchtower": lambda: {"summary": {"text": "观察哨完成"}, "triggers": []},
            "m60_second_entry": lambda: {},
            "m54_daily_accrual": lambda: {"skipped": True, "reason": "--no-llm"},
            "m58_exit_shadow": lambda: {"meta": {"window": {}}, "no_divergence_yet": True, "open_position_count": 0},
            "m59_panel": lambda: {"summary": {"text": "面板"}, "position_health": {"items": []}, "risk_warnings": {"event_warnings": {"items": []}}},
            "trigger_router": lambda: {
                "queue_path": str(tmp_path / "queue.json"),
                "history_path": str(tmp_path / "history.json"),
                "pending": [{"target": "300308", "reason": "复核", "trigger_rule": "unit"}],
            },
        },
    )

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        row = db.execute(text("SELECT * FROM task_capsules WHERE capsule_id = 'm63_postmarket:2026-07-05'")).mappings().one()
    finally:
        db.close()
        engine.dispose()

    assert "task_capsule:OK" in report["text"]
    assert row["task_type"] == "data_refresh"
    assert json.loads(row["symbols_json"]) == ["300308"]
    assert "M63 postmarket finished" in row["goal"]
