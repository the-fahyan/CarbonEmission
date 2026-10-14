"""Glue between the database and the pure optimizer: load inputs, solve, persist results + explanations."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, SchedulingDecision, SchedulingRun
from app.services import optimizer as opt
from app.services.event_bus import EventBus
from app.services.jobs import notify_job
from app.services.logging_service import add_log
from app.services.settings import SettingsModel, load_settings
from app.services.state_machine import QUEUED, transition
from app.services.telemetry import list_slots, to_calc_slots
from app.utils.timeutil import iso

TRIGGER_TEXT = {
    "job_submitted": "a new job was submitted",
    "job_cancelled": "a job was cancelled",
    "job_retried": "a job was retried",
    "job_completed": "a job finished and compute capacity became available",
    "telemetry_changed": "the administrator changed the carbon-intensity timeline",
    "settings_changed": "scheduling settings changed",
    "demo_load": "the demo scenario was loaded",
    "manual": "rescheduling was requested explicitly",
}


def policy_from_settings(s: SettingsModel) -> opt.Policy:
    return opt.Policy(capacity=s.capacity, threshold=s.carbon_threshold_g, w_carbon=s.weight_carbon,
                      w_wait=s.weight_wait, w_priority=s.weight_priority, nd_wait=s.nondeferrable_wait_weight,
                      critical_ignores_threshold=s.critical_ignores_threshold)


def _gather(db: Session, now: datetime):
    settings = load_settings(db)
    slots = to_calc_slots(list_slots(db))
    queued = list(db.scalars(select(Job).where(Job.status.in_(QUEUED)).order_by(Job.id)))
    running = list(db.scalars(select(Job).where(Job.status == "RUNNING")))
    reservations = [opt.Reservation(j.actual_start or now, (j.actual_start or now) + timedelta(minutes=j.duration_minutes))
                    for j in running]
    inputs = [opt.JobInput(j.id, j.name, j.duration_minutes, j.estimated_energy_kwh, j.priority, j.deferrable,
                           j.earliest_start, j.deadline) for j in queued]
    return settings, slots, queued, inputs, reservations


def preview_plan(db: Session, now: datetime) -> dict:
    """Dry run: solve but write nothing. Returned as plain JSON-able dict."""
    settings, slots, queued, inputs, reservations = _gather(db, now)
    res = opt.plan(inputs, now, slots, policy_from_settings(settings), reservations, "preview")
    by_id = {j.id: j for j in queued}
    items = []
    for jid, a in res.assignments.items():
        j = by_id[jid]
        items.append({
            "job_id": jid, "name": j.name, "current_status": j.status, "proposed_status": a.status,
            "current_start": iso(j.scheduled_start), "proposed_start": iso(a.start),
            "baseline_start": iso(a.baseline_start), "baseline_emissions_g": a.baseline_emissions,
            "proposed_emissions_g": a.emissions, "savings_g": a.savings_g, "savings_pct": a.savings_pct,
            "explanation": a.explanation})
    return {"ok": res.ok, "solver_status": res.solver_status, "is_optimal": res.is_optimal,
            "objective_value": res.objective, "variables": res.variables, "solve_ms": round(res.solve_ms, 2),
            "message": res.message, "items": items}


def run_scheduler(db: Session, bus: EventBus | None, now: datetime, trigger: str = "manual") -> SchedulingRun:
    """Re-plan all queued jobs. Running jobs are never touched (they only reserve capacity)."""
    settings, slots, queued, inputs, reservations = _gather(db, now)
    result = opt.plan(inputs, now, slots, policy_from_settings(settings), reservations, trigger)
    why = TRIGGER_TEXT.get(trigger, trigger)

    if not result.ok:
        run = SchedulingRun(trigger=trigger, sim_time=now, solver_status=result.solver_status, is_optimal=False,
                            jobs_considered=len(inputs), variables=result.variables, solve_ms=result.solve_ms,
                            summary=result.message, committed=False, details={"reason": why})
        db.add(run)
        db.flush()
        add_log(db, bus, now, f"Optimization failed ({result.solver_status}); existing schedule kept unchanged.",
                None, "ERROR")
        if bus:
            bus.publish("error", {"message": run.summary, "run_id": run.id})
        return run

    run = SchedulingRun(trigger=trigger, sim_time=now, solver_status=result.solver_status,
                        is_optimal=result.is_optimal, objective_value=result.objective,
                        baseline_objective_value=result.baseline_objective, jobs_considered=len(inputs),
                        variables=result.variables, solve_ms=result.solve_ms,
                        details={"reason": why, "capacity": settings.capacity,
                                 "threshold": settings.carbon_threshold_g})
    db.add(run)
    db.flush()

    counts = {"SCHEDULED": 0, "WAITING": 0, "UNSCHEDULABLE": 0}
    changed = 0
    selected: dict[str, str | None] = {}
    for job in queued:
        a = result.assignments[job.id]
        prev_status, prev_start = job.status, job.scheduled_start
        counts[a.status] += 1
        job_changed = (prev_status != a.status) or (prev_start != a.start) or not job.decisions
        # Persist planned fields (recomputed every run so savings follow rescheduling)
        transition(job, a.status, a.explanation.split(". ")[0][:300])
        job.scheduled_start, job.scheduled_end = a.start, a.end
        job.scheduled_intensity, job.scheduled_emissions_g = a.avg_intensity, a.emissions
        job.baseline_start, job.baseline_emissions_g = a.baseline_start, a.baseline_emissions
        job.savings_g, job.savings_pct, job.added_wait_minutes = a.savings_g, a.savings_pct, a.added_wait_min
        job.scheduling_explanation = a.explanation
        selected[str(job.id)] = iso(a.start)
        if job_changed:
            changed += 1
            expl = a.explanation
            if prev_status != "PENDING":
                prev_txt = f"Previously {prev_status}" + (f" at {prev_start:%H:%M}" if prev_start else "")
                expl = f"Schedule updated because {why}. {prev_txt}. " + expl
            db.add(SchedulingDecision(
                job_id=job.id, run_id=run.id, sim_time=now, previous_status=prev_status, new_status=a.status,
                selected_start=a.start, intensity_used=a.avg_intensity, emissions_g=a.emissions,
                explanation=expl, details={**a.details, "trigger": trigger}))
            add_log(db, bus, now, f"Scheduler: {prev_status} → {a.status}"
                    + (f", start {a.start:%H:%M}" if a.start else "") + f" ({why}).", job.id,
                    "WARN" if a.status == "UNSCHEDULABLE" else "INFO")
            notify_job(bus, job)

    run.jobs_scheduled, run.jobs_waiting = counts["SCHEDULED"], counts["WAITING"]
    run.jobs_unschedulable, run.jobs_changed = counts["UNSCHEDULABLE"], changed
    run.details = {**run.details, "selected_starts": selected}
    run.summary = (f"{len(inputs)} job(s) considered: {counts['SCHEDULED']} scheduled, {counts['WAITING']} waiting, "
                   f"{counts['UNSCHEDULABLE']} unschedulable; {changed} changed. Solver {result.solver_status}"
                   f"{'' if result.is_optimal else ' (feasible, not proven optimal)'}; Because {why}.")
    db.flush()
    add_log(db, bus, now, f"Scheduling run #{run.id}: {run.summary}")
    if bus:
        bus.publish("scheduler_run", {"run_id": run.id, "summary": run.summary, "trigger": trigger,
                                      "solver_status": run.solver_status, "jobs_changed": changed})
    return run
