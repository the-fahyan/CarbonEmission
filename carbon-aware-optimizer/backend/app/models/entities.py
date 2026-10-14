"""SQLAlchemy models. All datetimes are naive UTC *simulation-clock* times unless named wall_*."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import utcnow

PRIORITIES = ["low", "normal", "high", "critical"]
STATUSES = ["PENDING", "SCHEDULED", "WAITING", "RUNNING", "COMPLETED", "CANCELLED", "FAILED",
            "UNSCHEDULABLE"]
WORKLOAD_TYPES = ["ml_training", "batch_etl", "video_render", "report_generation", "data_backup",
                  "security_scan"]


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_job_duration"),
        CheckConstraint("estimated_energy_kwh >= 0", name="ck_job_energy"),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    workload_type: Mapped[str] = mapped_column(String(32), default="batch_etl")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    estimated_energy_kwh: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    deferrable: Mapped[bool] = mapped_column(Boolean, default=True)
    simulate_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    earliest_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    status_reason: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Planned results (recomputed on every scheduling run)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    baseline_emissions_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    scheduled_emissions_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    added_wait_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    scheduling_explanation: Mapped[str] = mapped_column(Text, default="")

    # Actual (simulated) execution results
    actual_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_emissions_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_wall: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    attempts: Mapped[list["ExecutionAttempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="ExecutionAttempt.id")
    logs: Mapped[list["JobLog"]] = relationship(cascade="all, delete-orphan")
    decisions: Mapped[list["SchedulingDecision"]] = relationship(
        cascade="all, delete-orphan", order_by="SchedulingDecision.id")


class TelemetrySlot(Base):
    __tablename__ = "telemetry_slots"
    __table_args__ = (
        UniqueConstraint("start_time", name="uq_slot_start"),
        CheckConstraint("intensity_g_per_kwh >= 0", name="ck_slot_intensity"),
        CheckConstraint("duration_minutes > 0", name="ck_slot_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    intensity_g_per_kwh: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="manual_simulated")


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (Index("ix_attempt_job", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="RUNNING")  # RUNNING/COMPLETED/FAILED/CANCELLED/INTERRUPTED
    sim_started_at: Mapped[datetime] = mapped_column(DateTime)
    sim_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    wall_started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    wall_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    last_milestone: Mapped[int] = mapped_column(Integer, default=0)
    emissions_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    job: Mapped[Job] = relationship(back_populates="attempts")


class JobLog(Base):
    __tablename__ = "job_logs"
    __table_args__ = (Index("ix_log_job_time", "job_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    sim_time: Mapped[datetime] = mapped_column(DateTime)
    wall_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SchedulingRun(Base):
    __tablename__ = "scheduling_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(40))
    sim_time: Mapped[datetime] = mapped_column(DateTime)
    wall_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    solver_status: Mapped[str] = mapped_column(String(40))
    is_optimal: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(40), default="scipy.optimize.milp")
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    jobs_considered: Mapped[int] = mapped_column(Integer, default=0)
    jobs_scheduled: Mapped[int] = mapped_column(Integer, default=0)
    jobs_waiting: Mapped[int] = mapped_column(Integer, default=0)
    jobs_unschedulable: Mapped[int] = mapped_column(Integer, default=0)
    jobs_changed: Mapped[int] = mapped_column(Integer, default=0)
    variables: Mapped[int] = mapped_column(Integer, default=0)
    solve_ms: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    committed: Mapped[bool] = mapped_column(Boolean, default=True)


class SchedulingDecision(Base):
    __tablename__ = "scheduling_decisions"
    __table_args__ = (Index("ix_decision_job", "job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scheduling_runs.id", ondelete="SET NULL"), nullable=True)
    sim_time: Mapped[datetime] = mapped_column(DateTime)
    previous_status: Mapped[str] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16))
    selected_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    intensity_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    emissions_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
