"""Manual (simulated) carbon-intensity timeline: validation + CRUD + queries.

Nothing here talks to an external API. Slot kinds are *derived* relative to the simulated clock:
  historical = slot ended already (recorded configured value), current = covers "now",
  future = simulated forecast. None of them is a real measurement.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TelemetrySlot
from app.services.emissions import Slot


class TelemetryValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def slot_end(s: TelemetrySlot) -> datetime:
    return s.start_time + timedelta(minutes=s.duration_minutes)


def validate_timeline(items: list[tuple[datetime, int, float]]) -> list[str]:
    """items = (start, duration_minutes, intensity). Returns human-readable error list."""
    errors: list[str] = []
    for i, (start, dur, val) in enumerate(items, 1):
        if val < 0:
            errors.append(f"Slot {i} ({start:%H:%M}): intensity must be >= 0 (got {val}).")
        if dur <= 0:
            errors.append(f"Slot {i} ({start:%H:%M}): duration must be > 0 minutes.")
    ordered = sorted(((s, d, v) for s, d, v in items if d > 0), key=lambda x: x[0])
    for (s1, d1, _), (s2, _d2, _) in zip(ordered, ordered[1:]):
        if s1 == s2:
            errors.append(f"Duplicate slot start time {s1:%Y-%m-%d %H:%M}.")
        elif s1 + timedelta(minutes=d1) > s2:
            errors.append(
                f"Slots overlap: {s1:%H:%M} (+{d1} min) runs past the next slot starting {s2:%H:%M}.")
    return errors


def list_slots(db: Session) -> list[TelemetrySlot]:
    return list(db.scalars(select(TelemetrySlot).order_by(TelemetrySlot.start_time)))


def replace_timeline(db: Session, items: list[tuple[datetime, int, float]]) -> list[TelemetrySlot]:
    errors = validate_timeline(items)
    if errors:
        raise TelemetryValidationError(errors)
    for old in list_slots(db):
        db.delete(old)
    db.flush()
    rows = [TelemetrySlot(start_time=s, duration_minutes=d, intensity_g_per_kwh=v) for s, d, v in items]
    db.add_all(rows)
    db.flush()
    return sorted(rows, key=lambda r: r.start_time)


def add_slot(db: Session, start: datetime, duration: int, value: float) -> TelemetrySlot:
    existing = [(s.start_time, s.duration_minutes, s.intensity_g_per_kwh) for s in list_slots(db)]
    errors = validate_timeline(existing + [(start, duration, value)])
    if errors:
        raise TelemetryValidationError(errors)
    row = TelemetrySlot(start_time=start, duration_minutes=duration, intensity_g_per_kwh=value)
    db.add(row)
    db.flush()
    return row


def update_slot(db: Session, slot_id: int, start: datetime | None, duration: int | None,
                value: float | None) -> TelemetrySlot | None:
    row = db.get(TelemetrySlot, slot_id)
    if row is None:
        return None
    others = [(s.start_time, s.duration_minutes, s.intensity_g_per_kwh)
              for s in list_slots(db) if s.id != slot_id]
    new = (start or row.start_time, duration or row.duration_minutes,
           row.intensity_g_per_kwh if value is None else value)
    errors = validate_timeline(others + [new])
    if errors:
        raise TelemetryValidationError(errors)
    row.start_time, row.duration_minutes, row.intensity_g_per_kwh = new
    db.flush()
    return row


def delete_slot(db: Session, slot_id: int) -> bool:
    row = db.get(TelemetrySlot, slot_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def to_calc_slots(rows: list[TelemetrySlot]) -> list[Slot]:
    return [Slot(r.start_time, slot_end(r), r.intensity_g_per_kwh) for r in rows]


def slot_kind(row: TelemetrySlot, now: datetime) -> str:
    if slot_end(row) <= now:
        return "historical"
    if row.start_time <= now:
        return "current"
    return "future"


def current_reading(rows: list[TelemetrySlot], now: datetime, manual: float | None) -> dict:
    for r in rows:
        if r.start_time <= now < slot_end(r):
            return {"intensity": r.intensity_g_per_kwh, "source": "timeline_slot", "slot_id": r.id}
    if manual is not None:
        return {"intensity": manual, "source": "manual_current_entry", "slot_id": None}
    return {"intensity": None, "source": "none", "slot_id": None}


def next_cleaner_window(rows: list[TelemetrySlot], now: datetime, current: float | None) -> dict | None:
    """First future slot strictly cleaner than the current reading (None if none exists)."""
    if current is None:
        return None
    for r in rows:
        if r.start_time > now and r.intensity_g_per_kwh < current:
            return {"slot_id": r.id, "start_time": r.start_time, "intensity": r.intensity_g_per_kwh,
                    "reduction_pct": round((current - r.intensity_g_per_kwh) / current * 100, 1) if current else None}
    return None
