from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_runtime_schema_migrates_forward_theses_unique_key(tmp_path):
    from backend.data.database import Base, _ensure_runtime_schema

    db_path = tmp_path / "legacy-forward-theses.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE forward_theses"))
        conn.execute(text("""
            CREATE TABLE forward_theses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                statement TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                horizon_date TEXT,
                confidence_low REAL,
                confidence_high REAL,
                evidence_manifest_json TEXT,
                invalidation_conditions_json TEXT,
                follow_up_metrics_json TEXT,
                next_review_date TEXT,
                review_cadence_days INTEGER,
                thesis_id INTEGER,
                theme_hypothesis_id INTEGER,
                universe_snapshot_id INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                UNIQUE(statement, horizon_date)
            )
        """))
        conn.execute(text("""
            INSERT INTO forward_theses (
                symbol,
                statement,
                horizon_date,
                status,
                confidence_low,
                confidence_high,
                evidence_manifest_json,
                review_cadence_days,
                thesis_id,
                created_at
            )
            VALUES (
                '600519',
                'same thesis',
                '2026-12-31',
                'draft',
                0.2,
                0.8,
                '[]',
                30,
                42,
                '2026-06-01 00:00:00'
            )
        """))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO forward_theses (symbol, statement, horizon_date, status)
                VALUES ('300308', 'same thesis', '2026-12-31', 'draft')
            """))

    _ensure_runtime_schema(engine)

    with engine.begin() as conn:
        migrated_sql = conn.execute(text("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'forward_theses'
        """)).scalar_one()
        assert 'UNIQUE("symbol", "statement", "horizon_date")' in migrated_sql

        preserved = conn.execute(text("""
            SELECT
                symbol,
                statement,
                horizon_date,
                status,
                confidence_low,
                confidence_high,
                evidence_manifest_json,
                review_cadence_days,
                thesis_id,
                created_at
            FROM forward_theses
        """)).fetchall()
        assert preserved == [(
            "600519",
            "same thesis",
            "2026-12-31",
            "draft",
            0.2,
            0.8,
            "[]",
            30,
            42,
            "2026-06-01 00:00:00",
        )]

        conn.execute(text("""
            INSERT INTO forward_theses (symbol, statement, horizon_date, status)
            VALUES ('300308', 'same thesis', '2026-12-31', 'draft')
        """))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO forward_theses (symbol, statement, horizon_date, status)
                VALUES (NULL, 'global thesis', '2026-12-31', 'draft')
            """))
            conn.execute(text("""
                INSERT INTO forward_theses (symbol, statement, horizon_date, status)
                VALUES (NULL, 'global thesis', '2026-12-31', 'draft')
            """))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO forward_theses (symbol, statement, horizon_date, status)
                VALUES ('600519', 'null horizon thesis', NULL, 'draft')
            """))
            conn.execute(text("""
                INSERT INTO forward_theses (symbol, statement, horizon_date, status)
                VALUES ('600519', 'null horizon thesis', NULL, 'draft')
            """))

    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT symbol, statement, horizon_date
            FROM forward_theses
            ORDER BY symbol
        """)).fetchall()
        assert rows == [
            ("300308", "same thesis", "2026-12-31"),
            ("600519", "same thesis", "2026-12-31"),
        ]


def test_runtime_schema_reports_existing_forward_theses_normalized_duplicates(tmp_path):
    from backend.data.database import Base, _ensure_runtime_schema

    db_path = tmp_path / "duplicate-forward-theses.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO forward_theses (symbol, statement, horizon_date, status, created_at, updated_at)
            VALUES ('600519', 'duplicate null horizon', NULL, 'draft', '2026-06-01 00:00:00', '2026-06-01 00:00:00')
        """))
        conn.execute(text("""
            INSERT INTO forward_theses (symbol, statement, horizon_date, status, created_at, updated_at)
            VALUES ('600519', 'duplicate null horizon', NULL, 'draft', '2026-06-02 00:00:00', '2026-06-02 00:00:00')
        """))

    with pytest.raises(RuntimeError) as exc:
        _ensure_runtime_schema(engine)

    message = str(exc.value)
    assert "forward_theses has duplicate normalized keys" in message
    assert "duplicate null horizon" in message
    assert "ids=1,2" in message


def test_runtime_schema_adds_theme_hypothesis_ai_supply_chain_column(tmp_path):
    from backend.data.database import Base, _ensure_runtime_schema

    db_path = tmp_path / "legacy-theme-hypotheses.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE theme_hypotheses"))
        conn.execute(text("""
            CREATE TABLE theme_hypotheses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                theme_id INTEGER,
                statement TEXT,
                status TEXT DEFAULT 'proposed',
                beneficiary_tiers_json TEXT,
                evidence_gaps_json TEXT,
                invalidation_conditions_json TEXT,
                forward_evidence_ref_json TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        before_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(theme_hypotheses)")).fetchall()
        ]
        assert "ai_supply_chain_json" not in before_cols

    _ensure_runtime_schema(engine)

    with engine.begin() as conn:
        after_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(theme_hypotheses)")).fetchall()
        ]
        assert "ai_supply_chain_json" in after_cols
