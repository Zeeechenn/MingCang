"""version runtime indexes — bring _ensure_runtime_schema idx_* indexes under Alembic

Revision ID: d4a1b7c9e023
Revises: c9f2e1a83b45
Create Date: 2026-06-07 02:20:00.000000

Background
----------
_ensure_runtime_schema (database.py + schema_runtime.py) creates a set of
idx_* indexes outside Alembic version control.  This migration versions them
so that a fresh Alembic-only setup gets the same indexes as a legacy runtime
setup.

Important: init_db() is NOT changed.  create_all() + _ensure_runtime_schema()
remain the authoritative path for non-Alembic deployments.  This migration
only adds the idx_* family to the Alembic chain so that `alembic upgrade head`
on a fresh DB produces an equivalent index set.

All CREATE INDEX statements use IF NOT EXISTS so the migration is idempotent
with respect to legacy DBs that already have the indexes from _ensure_runtime_schema.

Indexes versioned
-----------------
  universe_snapshots : idx_universe_snapshots_hash, idx_universe_snapshots_cutoff_market
  forward_theses     : idx_forward_theses_symbol, idx_forward_theses_status
                       uq_forward_theses_symbol_statement_horizon_norm (normalised unique)
  gate_b_observations: idx_gate_b_obs_symbol, idx_gate_b_obs_signal_date, idx_gate_b_obs_as_of

  (schema_runtime.py idx_* on ai_memory, stock_memory_items, memory_atoms, etc. are on
  non-ORM tables and intentionally excluded from include_object — they remain runtime-only.)
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4a1b7c9e023"
down_revision: Union[str, Sequence[str], None] = "c9f2e1a83b45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- universe_snapshots ---
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_snapshots_hash
        ON universe_snapshots(universe_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_universe_snapshots_cutoff_market
        ON universe_snapshots(cutoff_date, market_filter)
    """)

    # --- forward_theses ---
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_forward_theses_symbol
        ON forward_theses(symbol)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_forward_theses_status
        ON forward_theses(status)
    """)
    # Normalised unique index — handles NULL symbol / NULL horizon_date correctly.
    # Uses expression index so duplicates with NULLs are caught
    # (SQLite UNIQUE constraint does NOT catch NULL duplicates).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forward_theses_symbol_statement_horizon_norm
        ON forward_theses (
            CASE WHEN symbol IS NULL THEN 1 ELSE 0 END,
            COALESCE(symbol, ''),
            statement,
            CASE WHEN horizon_date IS NULL THEN 1 ELSE 0 END,
            COALESCE(horizon_date, '')
        )
    """)

    # --- gate_b_observations ---
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gate_b_obs_symbol
        ON gate_b_observations(symbol)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gate_b_obs_signal_date
        ON gate_b_observations(signal_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_gate_b_obs_as_of
        ON gate_b_observations(as_of)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_gate_b_obs_as_of")
    op.execute("DROP INDEX IF EXISTS idx_gate_b_obs_signal_date")
    op.execute("DROP INDEX IF EXISTS idx_gate_b_obs_symbol")

    op.execute("DROP INDEX IF EXISTS uq_forward_theses_symbol_statement_horizon_norm")
    op.execute("DROP INDEX IF EXISTS idx_forward_theses_status")
    op.execute("DROP INDEX IF EXISTS idx_forward_theses_symbol")

    op.execute("DROP INDEX IF EXISTS idx_universe_snapshots_cutoff_market")
    op.execute("DROP INDEX IF EXISTS idx_universe_snapshots_hash")
