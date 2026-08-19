"""bind official signals to the owning RunEnvelope — signals.run_id

Revision ID: e6f3c2b81a47
Revises: d4a1b7c9e023
Create Date: 2026-08-19 12:30:00.000000

Background
----------
Until now a signal row could only be attached to a run by matching its trade
date against `job_runs`.  When a trade date carried more than one batch the
attachment was ambiguous, and any writer that bypassed the tracked facade left
no trace at all.  `signals.run_id` makes the binding explicit and additive:
existing rows stay NULL and keep the legacy date-matching path in the
continuity auditor.

Additive only — no score, weight, stop or position column is touched.
"""
import sqlalchemy as sa
from alembic import op

revision = "e6f3c2b81a47"
down_revision = "d4a1b7c9e023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("signals") as batch:
        batch.add_column(sa.Column("run_id", sa.String(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_signals_run_id ON signals (run_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_signals_run_id")
    with op.batch_alter_table("signals") as batch:
        batch.drop_column("run_id")
