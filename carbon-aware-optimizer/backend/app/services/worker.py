"""Simulated job worker.

`tick()` is a plain function (easy to test, and used by the "advance time" control). The async
`WorkerService` just calls it every few hundred ms via `asyncio.to_thread`, so the event loop is
never blocked and there is no busy loop / per-job sleeping. Progress is *computed* from the
simulation clock: progress = (sim_now - sim_start) / duration.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Database
from app.models import ExecutionAttempt, Job
from app.services.emissions import job_emissions
from app.services.event_bus import EventBus
from app.services.jobs import notify_job
from app.services.logging_service import add_log
from app.services.scheduler import run_scheduler
from app.services.settings import SimClock, load_settings
from app.services.state_machine import STATE_LOCK, QUEUED, transition
from app.services.telemetry import list_slots, to_calc_slots
from app.utils.timeutil import utcnow

log = logging.getLogger("worker")
FAIL_AT = 0.6
MILESTONES = (25, 50, 75)


def tick(db: Session, bus: EventBus | None, now: datetime) -> dict:
    """One worker step at simulated time `now`. Returns counters (for tests/diagnostics)."""
    stats = {"started": 0, "completed": 0, "failed": 0}
    settings = load_settings(db)
    slots = to_calc_slots(list_slots(db))
    running = list(db.scalars(select(Job).where(Job.status == "RUNNING")))

    for job in running:
        att = db.scalars(select(ExecutionAttempt).where(
            ExecutionAttempt.job_id == job.id, ExecutionAttempt.state == "RUNNING")
            .order_by(ExecutionAttempt.id.desc())).first()
        if att is None:  # inconsistent row: fail safe rather than pretend completion
            transition(job, "FAILED", "Running job had no active attempt.")
            stats["failed"] += 1
            continue
        total = timedelta(minutes=job.duration_minutes)
        progress = min(1.0, max(0.0, (now - att.sim_started_at) / total))
        if job.simulate_failure and progress >= FAIL_AT:
            att.state, att.sim_finished_at, att.wall_finished_at = "FAILED", now, utcnow()
            att.progress, job.progress = progress, progress
            att.note = job.status_reason = f"Simulated workload failure at {progress*100:.0f}%."
            transition(job, "FAILED", att.note)
            add_log(db, bus, now, f"Attempt #{att.attempt_number} FAILED: {att.note}", job.id, "ERROR")
            notify_job(bus, job)
            stats["failed"] += 1
            continue
        if progress >= 1.0:
            end = att.sim_started_at + total
            em, _avg, covered = job_emissions(att.sim_started_at, job.duration_minutes,
                                              job.estimated_energy_kwh, slots)
            att.state, att.sim_finished_at, att.wall_finished_at = "COMPLETED", end, utcnow()
            att.progress = job.progress = 1.0
            att.emissions_g = job.actual_emissions_g = em if covered else None
            job.actual_end = end
            transition(job, "COMPLETED", "Simulated execution finished.")
            note = (f"{em:.0f} gCO2e (estimated from configured telemetry)" if covered
                    else "emissions unknown (telemetry no longer covers the run)")
            add_log(db, bus, now, f"Attempt #{att.attempt_number} COMPLETED; {note}.", job.id)
            notify_job(bus, job)
            stats["completed"] += 1
            continue
        if progress - att.progress >= 0.01:
            att.progress = job.progress = progress
            if bus:
                bus.publish("progress", {"job_id": job.id, "progress": round(progress, 3),
                                         "sim_time": now.isoformat() + "Z"})
        for m in MILESTONES:
            if progress * 100 >= m > att.last_milestone:
                att.last_milestone = m
                add_log(db, bus, now, f"Progress {m}% (simulated workload '{job.workload_type}').", job.id)

    n_running = sum(1 for j in running if j.status == "RUNNING")
    due = list(db.scalars(select(Job).where(Job.status == "SCHEDULED", Job.scheduled_start <= now)
                          .order_by(Job.scheduled_start, Job.id)))
    for job in due:
        if n_running >= settings.capacity:
            break  # capacity reached; job stays SCHEDULED and starts when a slot frees up
        number = len(job.attempts) + 1
        db.add(ExecutionAttempt(job_id=job.id, attempt_number=number, state="RUNNING", sim_started_at=now))
        transition(job, "RUNNING", f"Attempt #{number} started.")
        job.actual_start, job.progress = now, 0.0
        add_log(db, bus, now, f"Attempt #{number} started (planned {job.scheduled_start:%H:%M}, "
                f"{job.duration_minutes} simulated min).", job.id)
        notify_job(bus, job)
        n_running += 1
        stats["started"] += 1

    db.flush()
    if stats["completed"] or stats["failed"]:
        if db.scalars(select(Job.id).where(Job.status.in_(QUEUED))).first() is not None:
            run_scheduler(db, bus, now, "job_completed")
    return stats


def reconcile_on_startup(db: Session, bus: EventBus | None, now: datetime) -> int:
    """Attempts left RUNNING by a crash/restart are marked INTERRUPTED; we never claim they completed."""
    n = 0
    for att in db.scalars(select(ExecutionAttempt).where(ExecutionAttempt.state == "RUNNING")):
        att.state, att.sim_finished_at, att.wall_finished_at = "INTERRUPTED", now, utcnow()
        att.note = "Interrupted by application restart; computation not completed."
        job = db.get(Job, att.job_id)
        if job and job.status == "RUNNING":
            transition(job, "FAILED", att.note)
            add_log(db, bus, now, f"Attempt #{att.attempt_number} interrupted by restart; job marked FAILED "
                    "(use Retry).", job.id, "WARN")
        n += 1
    return n


class WorkerService:
    def __init__(self, database: Database, bus: EventBus, clock: SimClock, tick_seconds: float) -> None:
        self.database, self.bus, self.clock, self.tick_seconds = database, bus, clock, tick_seconds
        self._task: asyncio.Task | None = None
        self._last_persist = 0.0
        self.running = False
        self.paused = False

    def _once(self) -> None:
        if self.paused:
            return
        with STATE_LOCK, self.database.session() as db:
            tick(db, self.bus, self.clock.now())
            import time
            if time.monotonic() - self._last_persist > 5:
                self.clock.persist_now(db)
                self._last_persist = time.monotonic()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._once)
            except Exception:  # noqa: BLE001 - worker must survive any single failure
                log.exception("worker tick failed")
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        if self._task is None:
            self.running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self.running = False
