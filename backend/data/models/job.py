"""Persistent operational job-run ledger."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.orm import Base, _utcnow


class JobRun(Base):
    """One scheduler or manual workflow execution and its evidence envelope."""

    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_job_runs_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    job_name: Mapped[str] = mapped_column(String, index=True)
    trigger_source: Mapped[str] = mapped_column(String, index=True)
    as_of: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_coverage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    degradation_reasons_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_version: Mapped[str] = mapped_column(String)
    build_commit: Mapped[str] = mapped_column(String)
    db_role: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
