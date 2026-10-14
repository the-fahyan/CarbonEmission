"""Persist a log line AND publish it on the event bus (single place so they never disagree)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import JobLog
from app.services.event_bus import EventBus
from app.utils.timeutil import iso


def add_log(db: Session, bus: EventBus | None, sim_time: datetime, message: str,
            job_id: int | None = None, level: str = "INFO") -> JobLog:
    row = JobLog(job_id=job_id, level=level, message=message, sim_time=sim_time)
    db.add(row)
    db.flush()
    if bus:
        bus.publish("log", {"id": row.id, "job_id": job_id, "level": level, "message": message,
                            "sim_time": iso(sim_time)})
    return row
