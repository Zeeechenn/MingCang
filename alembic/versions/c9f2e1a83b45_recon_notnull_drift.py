"""reconcile NOT NULL drift — align live nullable cols with ORM NOT NULL declarations

Revision ID: c9f2e1a83b45
Revises: b87a3d661918
Create Date: 2026-06-07 02:10:00.000000

Background
----------
When the production DB was built from legacy runtime SQL (via _ensure_runtime_schema /
schema_runtime.py) instead of Alembic, several columns that the ORM declares NOT NULL
were created without the constraint.  This migration adds NOT NULL to those columns
using batch_alter_table (SQLite-safe table-copy approach).

Columns reconciled
------------------
  chat_messages   : session_id, role, content, created_at
  chat_sessions   : mode, created_at, updated_at
  decision_memory_layered : updated_at
  decision_runs   : run_id, run_type, created_at

Safety: each column was verified to have 0 NULL rows in the production copy before
this migration was written.  If a column has NULLs at upgrade time the batch ALTER
will fail with an integrity error and the upgrade is aborted safely.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9f2e1a83b45"
down_revision: Union[str, Sequence[str], None] = "b87a3d661918"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- chat_messages ----------
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.alter_column(
            "session_id",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "role",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "content",
            existing_type=sa.Text(),
            nullable=False,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )

    # ---------- chat_sessions ----------
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )

    # ---------- decision_memory_layered ----------
    with op.batch_alter_table("decision_memory_layered", schema=None) as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )

    # ---------- decision_runs ----------
    with op.batch_alter_table("decision_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "run_id",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "run_type",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )


def downgrade() -> None:
    # ---------- decision_runs ----------
    with op.batch_alter_table("decision_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=True,
        )
        batch_op.alter_column(
            "run_type",
            existing_type=sa.String(),
            nullable=True,
        )
        batch_op.alter_column(
            "run_id",
            existing_type=sa.String(),
            nullable=True,
        )

    # ---------- decision_memory_layered ----------
    with op.batch_alter_table("decision_memory_layered", schema=None) as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=True,
        )

    # ---------- chat_sessions ----------
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=True,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=True,
        )
        batch_op.alter_column(
            "mode",
            existing_type=sa.String(),
            nullable=True,
        )

    # ---------- chat_messages ----------
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            nullable=True,
        )
        batch_op.alter_column(
            "content",
            existing_type=sa.Text(),
            nullable=True,
        )
        batch_op.alter_column(
            "role",
            existing_type=sa.String(),
            nullable=True,
        )
        batch_op.alter_column(
            "session_id",
            existing_type=sa.String(),
            nullable=True,
        )
