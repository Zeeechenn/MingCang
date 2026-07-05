"""Golden schema guard for the init_db authority path."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.data.database import Base, _ensure_runtime_schema

SNAPSHOT_PATH = Path(__file__).parent / "data" / "schema_authority_snapshot.json"


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _build_schema_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    _ensure_runtime_schema(runtime_engine=engine)
    return engine


def _snapshot_schema(engine) -> dict:
    with engine.connect() as conn:
        table_names = [
            row[0]
            for row in conn.execute(text("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)).fetchall()
        ]

        snapshot = {}
        for table_name in table_names:
            quoted_table = _quote_identifier(table_name)
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "notnull": row[3],
                    "default": row[4],
                    "pk": row[5],
                }
                for row in conn.execute(text(f"PRAGMA table_info({quoted_table})")).fetchall()
            ]

            indexes = []
            for row in conn.execute(text(f"PRAGMA index_list({quoted_table})")).fetchall():
                index_name = row[1]
                quoted_index = _quote_identifier(index_name)
                index_columns = [
                    index_row[2]
                    for index_row in conn.execute(
                        text(f"PRAGMA index_info({quoted_index})")
                    ).fetchall()
                ]
                indexes.append(
                    {
                        "name": index_name,
                        "unique": row[2],
                        "columns": index_columns,
                    }
                )

            snapshot[table_name] = {
                "columns": columns,
                "indexes": sorted(indexes, key=lambda item: item["name"]),
            }

    return dict(sorted(snapshot.items()))


def _format_schema_drift_message(current: dict, golden: dict) -> str:
    current_tables = set(current)
    golden_tables = set(golden)
    added_tables = sorted(current_tables - golden_tables)
    missing_tables = sorted(golden_tables - current_tables)
    return (
        "schema 漂移：若这是有意的 schema 变更，跑 "
        "`REGEN_SCHEMA_GOLDEN=1 PYTHONPATH=. pytest tests/test_schema_authority.py` "
        "重生成 golden 并复审 diff；否则说明有人无意改了 schema。"
        f" 新增表: {added_tables}; 缺失表: {missing_tables}"
    )


def test_init_db_schema_matches_golden():
    current = _snapshot_schema(_build_schema_engine())

    if os.environ.get("REGEN_SCHEMA_GOLDEN"):
        SNAPSHOT_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip("regenerated golden")

    golden = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert current == golden, _format_schema_drift_message(current, golden)


def test_snapshot_is_deterministic():
    first = _snapshot_schema(_build_schema_engine())
    second = _snapshot_schema(_build_schema_engine())
    assert first == second
