"""Persistent settings + the simulation clock.

Simulation clock: sim_now = base_sim + (wall_now - base_wall) * simulation_speed.
With speed=60, one wall-clock second equals one simulated minute, so a 30-minute job finishes in
30 seconds. `advance()` jumps the clock forward (used by the "advance time" demo control).
Sim time is frozen while the server is down (see `restore_after_restart`).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models import AppSetting
from app.utils.timeutil import utcnow


class SettingsModel(BaseModel):
    capacity: int = Field(2, ge=1, le=32, description="Max concurrent jobs (compute capacity)")
    carbon_threshold_g: float = Field(450.0, ge=0, description="Max acceptable gCO2e/kWh for deferrable jobs")
    weight_carbon: float = Field(1.0, ge=0, description="Weight of normalized emissions (0-1 scale term)")
    weight_wait: float = Field(0.25, ge=0, description="Weight of normalized waiting time")
    weight_priority: float = Field(0.25, ge=0, description="Extra wait weight per priority rank (low=0 .. critical=3)")
    nondeferrable_wait_weight: float = Field(100.0, ge=0, description="Wait weight for non-deferrable/critical jobs")
    critical_ignores_threshold: bool = Field(True, description="Critical jobs ignore the carbon threshold (never deadline/capacity)")
    policy: str = Field("balanced", pattern="^(balanced)$")
    simulation_speed: float = Field(60.0, gt=0, le=36000, description="Simulated minutes per wall-clock minute")
    default_slot_minutes: int = Field(15, ge=1, le=240)
    auto_schedule: bool = Field(True, description="Reschedule automatically on submit/cancel/telemetry change")
    current_intensity_g: float | None = Field(None, ge=0, description="Manually configured 'current' reading")


class SettingsPatch(BaseModel):
    capacity: int | None = Field(None, ge=1, le=32)
    carbon_threshold_g: float | None = Field(None, ge=0)
    weight_carbon: float | None = Field(None, ge=0)
    weight_wait: float | None = Field(None, ge=0)
    weight_priority: float | None = Field(None, ge=0)
    nondeferrable_wait_weight: float | None = Field(None, ge=0)
    critical_ignores_threshold: bool | None = None
    simulation_speed: float | None = Field(None, gt=0, le=36000)
    default_slot_minutes: int | None = Field(None, ge=1, le=240)
    auto_schedule: bool | None = None
    current_intensity_g: float | None = Field(None, ge=0)


def load_settings(db: Session) -> SettingsModel:
    row = db.get(AppSetting, "settings")
    return SettingsModel(**(row.value if row else {}))


def save_settings(db: Session, model: SettingsModel) -> None:
    row = db.get(AppSetting, "settings")
    if row is None:
        db.add(AppSetting(key="settings", value=model.model_dump()))
    else:
        row.value = model.model_dump()


def update_settings(db: Session, patch: SettingsPatch) -> SettingsModel:
    current = load_settings(db)
    data = current.model_dump()
    data.update(patch.model_dump(exclude_unset=True))
    new = SettingsModel(**data)  # re-validate
    save_settings(db, new)
    return new


class SimClock:
    """Process-wide simulated clock, persisted in app_settings under key 'clock'."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.base_sim: datetime = utcnow()
        self.base_wall: datetime = utcnow()
        self.speed: float = 60.0

    def now(self) -> datetime:
        with self._lock:
            wall = datetime.now(timezone.utc).replace(tzinfo=None)
            return (self.base_sim + (wall - self.base_wall) * self.speed).replace(microsecond=0)

    def _rebase(self, speed: float | None = None, add_minutes: float = 0, set_to: datetime | None = None) -> None:
        wall = datetime.now(timezone.utc).replace(tzinfo=None)
        cur = self.base_sim + (wall - self.base_wall) * self.speed
        self.base_sim = (set_to if set_to else cur) + timedelta(minutes=add_minutes)
        self.base_wall = wall
        if speed is not None:
            self.speed = speed

    def set_speed(self, speed: float) -> None:
        with self._lock:
            self._rebase(speed=speed)

    def advance(self, minutes: float) -> datetime:
        with self._lock:
            self._rebase(add_minutes=minutes)
        return self.now()

    def reset_to_wall(self) -> None:
        with self._lock:
            self._rebase(set_to=utcnow())

    def persist(self, db: Session) -> None:
        with self._lock:
            val = {"base_sim": self.base_sim.isoformat(), "base_wall": self.base_wall.isoformat(), "speed": self.speed}
        row = db.get(AppSetting, "clock")
        if row is None:
            db.add(AppSetting(key="clock", value=val))
        else:
            row.value = val

    def restore_after_restart(self, db: Session, speed: float) -> None:
        """Resume simulated time from the last persisted instant (time does not pass while down)."""
        row = db.get(AppSetting, "clock")
        with self._lock:
            self.speed = speed
            self.base_wall = datetime.now(timezone.utc).replace(tzinfo=None)
            if row:
                # persisted base_sim + elapsed-at-persist-time is unknown; use last stored "now"
                self.base_sim = datetime.fromisoformat(row.value.get("last_sim", row.value["base_sim"]))
            else:
                self.base_sim = utcnow()

    def persist_now(self, db: Session) -> None:
        """Store the *current* simulated instant so a restart can resume from here."""
        cur = self.now()
        row = db.get(AppSetting, "clock")
        val = {"last_sim": cur.isoformat(), "base_sim": cur.isoformat()}
        if row is None:
            db.add(AppSetting(key="clock", value=val))
        else:
            row.value = val
