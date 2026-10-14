"""REST API. Handlers are sync (`def`) so FastAPI runs them in a threadpool and SQLite work never blocks
the event loop. All writers take STATE_LOCK so API calls and the worker never update jobs concurrently."""
from __future__ import annotations

import asyncio
import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Ctx, get_ctx, get_db
from app.models import ExecutionAttempt, Job, JobLog, SchedulingDecision, SchedulingRun
from app.schemas.api import (AdvanceIn, ConfirmIn, DecisionOut, JobCreate, JobDetail, JobList, JobOut, LogOut,
                             RunOut, SlotIn, SlotOut, SlotPatch, TimelineIn)
from app.services import analytics, demo as demo_svc, jobs as job_svc, telemetry as tele
from app.services.logging_service import add_log
from app.services.scheduler import preview_plan, run_scheduler
from app.services.settings import SettingsModel, SettingsPatch, load_settings, update_settings
from app.services.state_machine import QUEUED, STATE_LOCK
from app.services.worker import tick
from app.utils.timeutil import iso

router = APIRouter(prefix="/api")


def _job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found.")
    return job


def _maybe_reschedule(db: Session, ctx: Ctx, trigger: str) -> None:
    if load_settings(db).auto_schedule:
        run_scheduler(db, ctx.bus, ctx.clock.now(), trigger)


# ------------------------------------------------------------------ health / settings
@router.get("/health")
def health(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)) -> dict:
    db.execute(select(1))
    return {"status": "ok", "database": "ok", "worker_running": bool(ctx.worker and ctx.worker.running),
            "telemetry_mode": "manual_simulated", "sim_time": iso(ctx.clock.now())}


@router.get("/settings", response_model=SettingsModel)
def get_settings(db: Session = Depends(get_db)) -> SettingsModel:
    return load_settings(db)


@router.patch("/settings", response_model=SettingsModel)
def patch_settings(patch: SettingsPatch, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        new = update_settings(db, patch)
        if patch.simulation_speed is not None:
            ctx.clock.set_speed(new.simulation_speed)
        changed = set(patch.model_dump(exclude_unset=True)) - {"simulation_speed", "auto_schedule", "current_intensity_g"}
        if changed:
            _maybe_reschedule(db, ctx, "settings_changed")
        db.commit()
    ctx.bus.publish("settings", new.model_dump())
    return new


# ------------------------------------------------------------------ jobs
@router.post("/jobs", response_model=JobDetail, status_code=201)
def create_job(body: JobCreate, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    """Proxy entry point: validate -> persist -> evaluate/schedule -> record rationale -> return."""
    with STATE_LOCK:
        now = ctx.clock.now()
        job = job_svc.create_job(
            db, ctx.bus, now, name=body.name, description=body.description, workload_type=body.workload_type,
            duration_minutes=body.duration_minutes, energy_kwh=body.estimated_energy_kwh, priority=body.priority,
            deferrable=body.deferrable, earliest_start=body.earliest_start, deadline=body.deadline,
            simulate_failure=body.simulate_failure)
        _maybe_reschedule(db, ctx, "job_submitted")
        db.commit()
        db.refresh(job)
        return job


@router.get("/jobs", response_model=JobList)
def list_jobs(status: str | None = None, priority: str | None = None, q: str | None = None,
              sort: str = Query("id", pattern="^(id|name|priority|status|deadline|scheduled_start|savings_g|duration_minutes|estimated_energy_kwh)$"),
              order: str = Query("desc", pattern="^(asc|desc)$"), limit: int = Query(50, ge=1, le=200),
              offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status.upper())
    if priority:
        stmt = stmt.where(Job.priority == priority.lower())
    if q:
        stmt = stmt.where(Job.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = getattr(Job, sort)
    stmt = stmt.order_by(col.asc() if order == "asc" else col.desc(), Job.id).limit(limit).offset(offset)
    return {"items": list(db.scalars(stmt)), "total": total, "limit": limit, "offset": offset}


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return _job_or_404(db, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobDetail)
def cancel(job_id: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        job = _job_or_404(db, job_id)
        try:
            job_svc.cancel_job(db, ctx.bus, ctx.clock.now(), job)
        except job_svc.JobActionError as e:
            raise HTTPException(e.code, str(e))
        _maybe_reschedule(db, ctx, "job_cancelled")
        db.commit()
        db.refresh(job)
        return job


@router.post("/jobs/{job_id}/retry", response_model=JobDetail)
def retry(job_id: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        job = _job_or_404(db, job_id)
        try:
            job_svc.retry_job(db, ctx.bus, ctx.clock.now(), job)
        except job_svc.JobActionError as e:
            raise HTTPException(e.code, str(e))
        _maybe_reschedule(db, ctx, "job_retried")
        db.commit()
        db.refresh(job)
        return job


@router.get("/jobs/{job_id}/logs", response_model=list[LogOut])
def job_logs(job_id: int, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    return list(db.scalars(select(JobLog).where(JobLog.job_id == job_id).order_by(JobLog.id).limit(limit)))


@router.get("/jobs/{job_id}/decisions", response_model=list[DecisionOut])
def job_decisions(job_id: int, db: Session = Depends(get_db)):
    _job_or_404(db, job_id)
    return list(db.scalars(select(SchedulingDecision).where(SchedulingDecision.job_id == job_id)
                           .order_by(SchedulingDecision.id)))


# ------------------------------------------------------------------ telemetry
def _telemetry_view(db: Session, ctx: Ctx) -> dict:
    now = ctx.clock.now()
    rows = tele.list_slots(db)
    settings = load_settings(db)
    cur = tele.current_reading(rows, now, settings.current_intensity_g)
    return {
        "mode": "manual_simulated",
        "disclaimer": "All values are manually configured simulated readings, not measurements.",
        "sim_time": iso(now),
        "slots": [SlotOut(id=r.id, start_time=r.start_time, end_time=tele.slot_end(r), duration_minutes=r.duration_minutes,
                          intensity_g_per_kwh=r.intensity_g_per_kwh, kind=tele.slot_kind(r, now),
                          source=r.source).model_dump(mode="json") for r in rows],
        "current": cur,
        "manual_current_intensity_g": settings.current_intensity_g,
        "next_cleaner_window": (lambda w: None if w is None else {**w, "start_time": iso(w["start_time"])})(
            tele.next_cleaner_window(rows, now, cur["intensity"])),
        "horizon_end": iso(max((tele.slot_end(r) for r in rows), default=None)),
    }


def _telemetry_changed(db: Session, ctx: Ctx) -> None:
    _maybe_reschedule(db, ctx, "telemetry_changed")
    db.commit()
    ctx.bus.publish("telemetry", {"message": "Telemetry timeline changed"})


def _tele_errors(fn):
    try:
        return fn()
    except tele.TelemetryValidationError as e:
        raise HTTPException(422, detail={"error": "telemetry_validation", "message": "Invalid telemetry.",
                                         "details": e.errors})


@router.get("/telemetry")
def get_telemetry(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return _telemetry_view(db, ctx)


@router.put("/telemetry")
def put_telemetry(body: TimelineIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        _tele_errors(lambda: tele.replace_timeline(
            db, [(s.start_time, s.duration_minutes, s.intensity_g_per_kwh) for s in body.slots]))
        if body.current_intensity_g is not None:
            update_settings(db, SettingsPatch(current_intensity_g=body.current_intensity_g))
        add_log(db, ctx.bus, ctx.clock.now(), f"Telemetry timeline saved ({len(body.slots)} slots, simulated values).")
        _telemetry_changed(db, ctx)
    return _telemetry_view(db, ctx)


@router.post("/telemetry/slots", status_code=201)
def add_slot(body: SlotIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        _tele_errors(lambda: tele.add_slot(db, body.start_time, body.duration_minutes, body.intensity_g_per_kwh))
        _telemetry_changed(db, ctx)
    return _telemetry_view(db, ctx)


@router.patch("/telemetry/slots/{slot_id}")
def patch_slot(slot_id: int, body: SlotPatch, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        row = _tele_errors(lambda: tele.update_slot(db, slot_id, body.start_time, body.duration_minutes,
                                                    body.intensity_g_per_kwh))
        if row is None:
            raise HTTPException(404, f"Slot {slot_id} not found.")
        _telemetry_changed(db, ctx)
    return _telemetry_view(db, ctx)


@router.delete("/telemetry/slots/{slot_id}")
def del_slot(slot_id: int, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        if not tele.delete_slot(db, slot_id):
            raise HTTPException(404, f"Slot {slot_id} not found.")
        _telemetry_changed(db, ctx)
    return _telemetry_view(db, ctx)


@router.post("/telemetry/demo")
def telemetry_demo(body: ConfirmIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    """Reset ONLY the timeline to the demo curve (jobs untouched). Requires confirm=true."""
    if not body.confirm:
        raise HTTPException(400, "Resetting the timeline replaces all slots; send {\"confirm\": true}.")
    with STATE_LOCK:
        now = ctx.clock.now()
        anchor = now.replace(second=0, microsecond=0)
        anchor -= timedelta(minutes=anchor.minute % 15)
        tele.replace_timeline(db, demo_svc.build_timeline(anchor))
        add_log(db, ctx.bus, now, "Telemetry timeline reset to the demo scenario (simulated values).")
        _telemetry_changed(db, ctx)
    return _telemetry_view(db, ctx)


# ------------------------------------------------------------------ scheduler
@router.post("/scheduler/run", response_model=RunOut)
def scheduler_run(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        run = run_scheduler(db, ctx.bus, ctx.clock.now(), "manual")
        db.commit()
        db.refresh(run)
        return run


@router.get("/scheduler/preview")
def scheduler_preview(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    with STATE_LOCK:
        return preview_plan(db, ctx.clock.now())


@router.get("/scheduler/history", response_model=list[RunOut])
def scheduler_history(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    return list(db.scalars(select(SchedulingRun).order_by(SchedulingRun.id.desc()).limit(limit)))


@router.get("/scheduler/status")
def scheduler_status(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    last = db.scalars(select(SchedulingRun).order_by(SchedulingRun.id.desc())).first()
    s = load_settings(db)
    running = db.scalar(select(func.count()).select_from(Job).where(Job.status == "RUNNING")) or 0
    queued = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(QUEUED))) or 0
    unsched = list(db.scalars(select(Job).where(Job.status.in_(["UNSCHEDULABLE", "WAITING"])).order_by(Job.id)))
    return {"last_run": None if last is None else RunOut.model_validate(last).model_dump(mode="json"),
            "capacity": s.capacity, "running_jobs": running, "available_capacity": max(0, s.capacity - running),
            "queued_jobs": queued, "settings": s.model_dump(),
            "diagnostics": [{"job_id": j.id, "name": j.name, "status": j.status,
                             "explanation": j.scheduling_explanation} for j in unsched]}


# ------------------------------------------------------------------ worker / clock / demo
@router.get("/worker/status")
def worker_status(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    s = load_settings(db)
    return {"running": bool(ctx.worker and ctx.worker.running), "paused": bool(ctx.worker and ctx.worker.paused),
            "sim_time": iso(ctx.clock.now()), "wall_time": iso(__import__("app.utils.timeutil", fromlist=["x"]).utcnow()),
            "simulation_speed": s.simulation_speed, "capacity": s.capacity,
            "label": "Simulation time advances faster than wall-clock time at the configured speed."}


@router.post("/worker/pause")
def worker_pause(ctx: Ctx = Depends(get_ctx)):
    if ctx.worker:
        ctx.worker.paused = True
    return {"paused": True}


@router.post("/worker/resume")
def worker_resume(ctx: Ctx = Depends(get_ctx)):
    if ctx.worker:
        ctx.worker.paused = False
    return {"paused": False}


@router.post("/worker/advance")
def worker_advance(body: AdvanceIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    """Jump the simulation clock forward in 1-minute steps, running the worker at each step so jobs start
    and finish at their correct simulated instants."""
    with STATE_LOCK:
        steps = int(body.minutes)
        remainder = body.minutes - steps
        for _ in range(steps):
            tick(db, ctx.bus, ctx.clock.advance(1))
        if remainder > 0:
            tick(db, ctx.bus, ctx.clock.advance(remainder))
        add_log(db, ctx.bus, ctx.clock.now(), f"Simulation clock advanced by {body.minutes:g} min.")
        db.commit()
    return {"sim_time": iso(ctx.clock.now())}


@router.post("/demo/load")
def demo_load(body: ConfirmIn, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "Loading the demo replaces the telemetry timeline and removes previous DEMO jobs "
                                 "(your own jobs are kept). Send {\"confirm\": true}.")
    with STATE_LOCK:
        ctx.clock.reset_to_wall()
        res = demo_svc.load_demo(db, ctx.bus, ctx.clock.now())
        db.commit()
    ctx.bus.publish("telemetry", {"message": "Demo scenario loaded"})
    return {**res, "timeline_start": iso(res["timeline_start"])}


# ------------------------------------------------------------------ analytics / logs / events
@router.get("/analytics/summary")
def a_summary(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return analytics.summary(db, ctx.clock.now())


@router.get("/analytics/emissions")
def a_emissions(db: Session = Depends(get_db)):
    return analytics.per_job_emissions(db)


@router.get("/analytics/savings")
def a_savings(db: Session = Depends(get_db)):
    return analytics.savings_report(db)


def _log_query(job_id, level, since_id, limit):
    stmt = select(JobLog)
    if job_id is not None:
        stmt = stmt.where(JobLog.job_id == job_id)
    if level:
        stmt = stmt.where(JobLog.level == level.upper())
    if since_id:
        stmt = stmt.where(JobLog.id > since_id)
    return stmt.order_by(JobLog.id.desc()).limit(limit)


@router.get("/logs", response_model=list[LogOut])
def logs(job_id: int | None = None, level: str | None = None, since_id: int = 0,
         limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)):
    return list(reversed(list(db.scalars(_log_query(job_id, level, since_id, limit)))))


@router.get("/logs/export.csv")
def logs_csv(job_id: int | None = None, level: str | None = None, db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "sim_time_utc", "wall_time_utc", "job_id", "level", "message"])
    for r in reversed(list(db.scalars(_log_query(job_id, level, 0, 5000)))):
        w.writerow([r.id, iso(r.sim_time), iso(r.wall_time), r.job_id or "", r.level, r.message])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=logs.csv"})


@router.get("/analytics/export.csv")
def jobs_csv(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["job_id", "name", "status", "priority", "baseline_g", "planned_g", "actual_g", "savings_g", "savings_pct"])
    for r in analytics.per_job_emissions(db):
        w.writerow([r["job_id"], r["name"], r["status"], "", r["baseline_g"], r["planned_g"], r["actual_g"],
                    r["savings_g"], r["savings_pct"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=emissions.csv"})


@router.get("/events")
async def events(request: Request, ctx: Ctx = Depends(get_ctx), last_event_id: int | None = Query(None),
                 last_event_id_header: str | None = Header(None, alias="Last-Event-ID")):
    """Server-Sent Events. Resume via Last-Event-ID header (or ?last_event_id=). Heartbeat every 15 s."""
    after = last_event_id if last_event_id is not None else int(last_event_id_header or 0)
    ctx.bus.bind_loop(asyncio.get_running_loop())
    q = ctx.bus.subscribe()

    async def stream():
        try:
            yield "retry: 3000\n\n"
            for evt in ctx.bus.recent(after, 100):  # bounded replay
                yield ctx.bus.format_sse(evt)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield ctx.bus.format_sse(evt)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            ctx.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
