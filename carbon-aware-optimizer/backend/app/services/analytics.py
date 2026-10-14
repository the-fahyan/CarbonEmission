"""Aggregate numbers. Planned vs completed are kept separate; only jobs that have BOTH a baseline and a
scheduled figure are compared, and everything else is listed as excluded (never silently counted)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Job
from app.services.emissions import savings
from app.services.telemetry import current_reading, list_slots
from app.services.settings import load_settings
from datetime import datetime

PLANNED = ("SCHEDULED", "RUNNING")


def _agg(baseline: float, other: float, n: int) -> dict:
    s, p = savings(baseline, other)
    return {"jobs": n, "baseline_g": round(baseline, 2), "optimized_g": round(other, 2),
            "savings_g": None if s is None else round(s, 2), "savings_pct": None if p is None else round(p, 2)}


def savings_report(db: Session) -> dict:
    jobs = list(db.scalars(select(Job).where(Job.status.in_(["SCHEDULED", "RUNNING", "COMPLETED", "WAITING", "UNSCHEDULABLE"]))))
    planned = [j for j in jobs if j.status in PLANNED and j.baseline_emissions_g is not None and j.scheduled_emissions_g is not None]
    done = [j for j in jobs if j.status == "COMPLETED" and j.baseline_emissions_g is not None and j.actual_emissions_g is not None]
    excluded = []
    for j in jobs:
        if j.status in ("WAITING", "UNSCHEDULABLE"):
            excluded.append({"job_id": j.id, "name": j.name, "reason": f"{j.status}: no schedule to compare"})
        elif j.status in PLANNED and j in jobs and (j.baseline_emissions_g is None or j.scheduled_emissions_g is None):
            excluded.append({"job_id": j.id, "name": j.name, "reason": "baseline not feasible under capacity"})
    return {
        "scope": "aggregate over comparable jobs (same energy assumptions, same capacity, same telemetry)",
        "planned": _agg(sum(j.baseline_emissions_g for j in planned), sum(j.scheduled_emissions_g for j in planned), len(planned)),
        "completed": _agg(sum(j.baseline_emissions_g for j in done), sum(j.actual_emissions_g for j in done), len(done)),
        "excluded": excluded,
        "note": "Estimates from manually configured, simulated telemetry; not measured emissions.",
    }


def summary(db: Session, now: datetime) -> dict:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    rep = savings_report(db)
    cur = current_reading(list_slots(db), now, load_settings(db).current_intensity_g)
    comb_b = rep["planned"]["baseline_g"] + rep["completed"]["baseline_g"]
    comb_o = rep["planned"]["optimized_g"] + rep["completed"]["optimized_g"]
    s, p = savings(comb_b, comb_o)
    return {
        "counts": counts,
        "awaiting": counts.get("PENDING", 0) + counts.get("WAITING", 0) + counts.get("SCHEDULED", 0),
        "running": counts.get("RUNNING", 0), "completed": counts.get("COMPLETED", 0),
        "unschedulable": counts.get("UNSCHEDULABLE", 0),
        "baseline_g": comb_b, "optimized_g": comb_o, "savings_g": s, "savings_pct": p,
        "comparable_jobs": rep["planned"]["jobs"] + rep["completed"]["jobs"],
        "current_intensity": cur, "telemetry_mode": "manual_simulated", "sim_time": now.isoformat() + "Z",
    }


def per_job_emissions(db: Session) -> list[dict]:
    rows = db.scalars(select(Job).where(Job.baseline_emissions_g.is_not(None)).order_by(Job.id))
    return [{"job_id": j.id, "name": j.name, "status": j.status, "baseline_g": j.baseline_emissions_g,
             "planned_g": j.scheduled_emissions_g, "actual_g": j.actual_emissions_g,
             "savings_g": j.savings_g, "savings_pct": j.savings_pct} for j in rows]
