"""Carbon-emissions maths.

Model (documented in README): a job draws *constant power* P = E / T over its runtime.
Energy in each telemetry slot = P * (hours of overlap with that slot).
Emissions_g = sum over slots( energy_in_slot_kWh * intensity_gCO2e_per_kWh ).
Because every job's energy is split (never repeated) across slots, nothing is double counted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    intensity: float  # gCO2e/kWh


def overlap_hours(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    lo, hi = max(a_start, b_start), min(a_end, b_end)
    return max((hi - lo).total_seconds(), 0.0) / 3600.0


def job_emissions(start: datetime, duration_minutes: float, energy_kwh: float,
                  slots: list[Slot]) -> tuple[float, float, bool]:
    """Return (emissions_g, energy_weighted_avg_intensity, fully_covered).

    `fully_covered` is False if the run interval touches time with no telemetry. Callers must
    never treat the uncovered part as zero or invent values; they should reject the interval.
    """
    end = start + timedelta(minutes=duration_minutes)
    total_hours = duration_minutes / 60.0
    if total_hours <= 0:
        return 0.0, 0.0, True
    power_kw = energy_kwh / total_hours
    emissions = 0.0
    covered_hours = 0.0
    for s in slots:
        h = overlap_hours(start, end, s.start, s.end)
        if h > 0:
            emissions += power_kw * h * s.intensity
            covered_hours += h
    fully = covered_hours >= total_hours - 1e-9
    avg = emissions / energy_kwh if energy_kwh > 0 else _time_avg(start, end, slots)
    return emissions, avg, fully


def _time_avg(start: datetime, end: datetime, slots: list[Slot]) -> float:
    tot = w = 0.0
    for s in slots:
        h = overlap_hours(start, end, s.start, s.end)
        tot += h * s.intensity
        w += h
    return tot / w if w else 0.0


def savings(baseline_g: float | None, scheduled_g: float | None) -> tuple[float | None, float | None]:
    """Absolute and percentage savings. Percentage is None when baseline is 0/unknown (no div-by-zero)."""
    if baseline_g is None or scheduled_g is None:
        return None, None
    absolute = baseline_g - scheduled_g
    pct = (absolute / baseline_g * 100.0) if baseline_g > 0 else None
    return absolute, pct
