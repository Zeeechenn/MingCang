"""
M37 Review Loop — idempotent schema migration.

Creates review_cases and memory_promotion_candidates tables.
No existing tables are altered.

Execute:
  PYTHONPATH=. python -m backend.data.migrations.add_review_loop
"""
import logging

from backend.data.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    """Apply M37 Review Loop schema (idempotent)."""
    init_db()  # runs Base.metadata.create_all — stamps review_cases + memory_promotion_candidates
    logger.info("review_cases and memory_promotion_candidates tables ready")


if __name__ == "__main__":
    run()
