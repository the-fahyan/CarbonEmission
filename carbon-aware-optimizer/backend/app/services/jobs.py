"""Job-level operations: create (the 'proxy' entry point), cancel, retry, serialisation helpers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExecutionAttempt, Job
from app.services.event_bus import EventBus
from app.services.logging_service import add_log
from app.services.state_machine import CANCELLABLE, RETRYABLE, InvalidTransition, transition
from app.utils.timeutil import iso


class JobActionError(Exception):
    def __init__(self, message: str, code: int = 409) -> None:
        super().__init__(message)
        self.code = code


def notify_job(bus: EventBus | None, job: Job) -> None:
    if bus:
        bus.publish("job_update", {
            "id": job.id, "name": job.name, "status": job.status, "progress": round(job.progress, 3),
            "scheduled_start": iso(job.scheduled_start), "reason": job.status_reason})


def create_job(db: Session, bus: EventBus | None, now: datetime, *, name: str, description: str,
               workload_type: str, duration_minutes: int, energy_kwh: float, priority: str,
               deferrable: bool, earliest_start: datetime | None, deadline: datetime | None,
               simulate_failure: bool = False, is_demo: bool = False) -> Job:
    job = Job(name=name, description=description, workload_type=workload_type,
              duration_minutes=duration_minutes, estimated_energy_kwh=energy_kwh, priority=priority,
              deferrable=deferrable, earliest_start=earliest_start, deadline=deadline,
              simulate_failure=simulate_failure, is_demo=is_demo, submitted_at=now, status="PENDING",
              status_reason="Received by the scheduler proxy; awaiting scheduling.")
    db.add(job)
    db.flush()
    add_log(db, bus, now, f"Job '{name}' received by proxy and persisted (priority={priority}, "
            f"{duration_minutes} min, {energy_kwh} kWh, deferrable={deferrable}).", job.id)
    notify_job(bus, job)
    return job


def cancel_job(db: Session, bus: EventBus | None, now: datetime, job: Job) -> Job:
    if job.status not in CANCELLABLE:
        raise JobActionError(f"Job {job.id} is {job.status} and cannot be cancelled.")
    was_running = job.status == "RUNNING"
    if was_running:
        att = db.scalars(select(ExecutionAttempt).where(
            ExecutionAttempt.job_id == job.id, ExecutionAttempt.state == "RUNNING")).first()
        if att:
            att.state, att.sim_finished_at = "CANCELLED", now
            att.note = "Cancelled by user while running."
    transition(job, "CANCELLED", "Cancelled by user.")
    job.scheduled_start = job.scheduled_end = None
    add_log(db, bus, now, "Job cancelled by user" + (" while running (attempt stopped)." if was_running else "."),
            job.id, "WARN")
    notify_job(bus, job)
    return job


def retry_job(db: Session, bus: EventBus | None, now: datetime, job: Job) -> Job:
    if job.status not in RETRYABLE:
        raise JobActionError(f"Job {job.id} is {job.status}; only FAILED, CANCELLED or UNSCHEDULABLE jobs can be retried.")
    try:
        transition(job, "PENDING", "Retry requested; awaiting scheduling.")
    except InvalidTransition as exc:  # pragma: no cover - guarded above
        raise JobActionError(str(exc)) from exc
    # Previous ExecutionAttempt rows are kept; only the "current run" fields are reset.
    job.progress = 0.0
    job.scheduled_start = job.scheduled_end = job.scheduled_intensity = None
    job.actual_start = job.actual_end = job.actual_emissions_g = None
    job.baseline_start = job.baseline_emissions_g = job.scheduled_emissions_g = None
    job.savings_g = job.savings_pct = job.added_wait_minutes = None
    job.simulate_failure = False
    job.scheduling_explanation = ""
    add_log(db, bus, now, f"Retry requested ({len(job.attempts)} previous attempt(s) preserved).", job.id)
    notify_job(bus, job)
    return job
