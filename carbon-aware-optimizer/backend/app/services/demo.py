"""Reproducible demo scenario. Only INPUTS are predefined; schedules/savings are computed by the optimizer."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job
from app.services.event_bus import EventBus
from app.services.jobs import create_job
from app.services.logging_service import add_log
from app.services.settings import SettingsPatch, update_settings
from app.services.telemetry import replace_timeline

# (offset_hours, gCO2e/kWh) anchor points; linearly interpolated per 15-min slot (illustrative values).
ANCHORS = [(0, 700), (1, 600), (2, 420), (3, 150), (5, 100), (6, 250), (7, 480), (8, 560), (10, 650)]

# name, workload, minutes, kWh, priority, deferrable, deadline_h (None = open), failure, description
DEMO_JOBS = [
    ("Production API Reindex", "batch_etl", 20, 1.2, "high", False, 2.0, False, "Non-deferrable: must run ASAP."),
    ("ML Model Training", "ml_training", 90, 6.0, "normal", True, 8.0, False, "Large deferrable job that benefits from waiting."),
    ("Nightly Backup", "data_backup", 30, 1.5, "low", True, 9.0, False, "Low priority, flexible."),
    ("Video Render Batch", "video_render", 60, 4.0, "normal", True, 5.0, False, "Competes for capacity."),
    ("Quarterly Report", "report_generation", 20, 0.8, "high", True, 0.75, False, "Tight deadline (45 min)."),
    ("Data Warehouse ETL", "batch_etl", 45, 2.5, "normal", True, 6.0, False, "Deferrable ETL."),
    ("Fraud Scoring (critical)", "security_scan", 25, 1.0, "critical", True, 3.0, False, "Critical: ignores the carbon threshold."),
    ("Impossible Deadline Job", "ml_training", 120, 3.0, "normal", True, 0.5, False, "Cannot fit before its deadline."),
    ("Flaky Export (fails once)", "report_generation", 20, 0.6, "low", True, 7.0, True, "Simulated failure to demo Retry."),
]


def build_timeline(start: datetime, slot_minutes: int = 15, hours: int = 10) -> list[tuple[datetime, int, float]]:
    out = []
    for i in range(hours * 60 // slot_minutes):
        h = i * slot_minutes / 60.0
        for (h0, v0), (h1, v1) in zip(ANCHORS, ANCHORS[1:]):
            if h0 <= h <= h1:
                val = v0 + (v1 - v0) * (h - h0) / (h1 - h0)
                break
        out.append((start + timedelta(minutes=i * slot_minutes), slot_minutes, round(val, 1)))
    return out


def load_demo(db: Session, bus: EventBus | None, now: datetime) -> dict:
    """Replace the telemetry timeline, remove previous *demo* jobs only, submit the demo jobs (left PENDING)."""
    removed = 0
    for j in db.scalars(select(Job).where(Job.is_demo.is_(True))):
        db.delete(j)
        removed += 1
    db.flush()
    anchor = now.replace(second=0, microsecond=0)
    anchor -= timedelta(minutes=anchor.minute % 15)
    replace_timeline(db, build_timeline(anchor))
    update_settings(db, SettingsPatch(capacity=2, carbon_threshold_g=450, current_intensity_g=700,
                                      simulation_speed=60))
    for (name, wl, mins, kwh, prio, defer, dl_h, fail, desc) in DEMO_JOBS:
        create_job(db, bus, now, name=name, description=desc, workload_type=wl, duration_minutes=mins,
                   energy_kwh=kwh, priority=prio, deferrable=defer, earliest_start=None,
                   deadline=now + timedelta(hours=dl_h), simulate_failure=fail, is_demo=True)
    add_log(db, bus, now, f"Demo scenario loaded: {len(DEMO_JOBS)} jobs submitted ({removed} previous demo jobs "
            "removed), telemetry replaced, capacity=2, threshold=450. Run the optimizer to schedule them.")
    return {"jobs_created": len(DEMO_JOBS), "demo_jobs_removed": removed, "timeline_start": anchor}
