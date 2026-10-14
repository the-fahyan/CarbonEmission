"""Pydantic request/response schemas. Input datetimes -> naive UTC; output datetimes -> ISO-8601 with 'Z'."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.models.entities import WORKLOAD_TYPES
from app.utils.timeutil import iso, to_utc_naive

InDt = Annotated[datetime, AfterValidator(to_utc_naive)]
OutDt = Annotated[datetime, PlainSerializer(lambda d: iso(d), return_type=str, when_used="json")]
Priority = Literal["low", "normal", "high", "critical"]
WorkloadType = Literal[tuple(WORKLOAD_TYPES)]  # type: ignore[valid-type]


class ErrorBody(BaseModel):
    error: str
    message: str
    details: list[str] | None = None


class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    workload_type: WorkloadType = "batch_etl"
    duration_minutes: int = Field(gt=0, le=7 * 24 * 60)
    estimated_energy_kwh: float = Field(ge=0, le=100000)
    priority: Priority = "normal"
    earliest_start: InDt | None = None
    deadline: InDt | None = None
    deferrable: bool = True
    simulate_failure: bool = False

    @model_validator(mode="after")
    def _check(self) -> "JobCreate":
        if self.deadline and self.earliest_start and self.deadline <= self.earliest_start:
            raise ValueError("deadline must be after earliest_start")
        return self


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    attempt_number: int
    state: str
    sim_started_at: OutDt
    sim_finished_at: OutDt | None
    wall_started_at: OutDt
    wall_finished_at: OutDt | None
    progress: float
    emissions_g: float | None
    note: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    workload_type: str
    duration_minutes: int
    estimated_energy_kwh: float
    priority: str
    deferrable: bool
    is_demo: bool
    submitted_at: OutDt
    earliest_start: OutDt | None
    deadline: OutDt | None
    status: str
    status_reason: str
    progress: float
    scheduled_start: OutDt | None
    scheduled_end: OutDt | None
    scheduled_intensity: float | None
    baseline_start: OutDt | None
    baseline_emissions_g: float | None
    scheduled_emissions_g: float | None
    savings_g: float | None
    savings_pct: float | None
    added_wait_minutes: float | None
    scheduling_explanation: str
    actual_start: OutDt | None
    actual_end: OutDt | None
    actual_emissions_g: float | None


class JobDetail(JobOut):
    simulate_failure: bool = False
    attempts: list[AttemptOut] = []


class JobList(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    run_id: int | None
    sim_time: OutDt
    previous_status: str
    new_status: str
    selected_start: OutDt | None
    intensity_used: float | None
    emissions_g: float | None
    explanation: str
    details: dict


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int | None
    level: str
    message: str
    sim_time: OutDt
    wall_time: OutDt


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    trigger: str
    sim_time: OutDt
    wall_time: OutDt
    solver_status: str
    is_optimal: bool
    method: str
    objective_value: float | None
    baseline_objective_value: float | None
    jobs_considered: int
    jobs_scheduled: int
    jobs_waiting: int
    jobs_unschedulable: int
    jobs_changed: int
    variables: int
    solve_ms: float
    summary: str
    details: dict
    committed: bool


class SlotIn(BaseModel):
    start_time: InDt
    duration_minutes: int = Field(15, gt=0, le=24 * 60)
    intensity_g_per_kwh: float = Field(ge=0, le=5000)


class SlotPatch(BaseModel):
    start_time: InDt | None = None
    duration_minutes: int | None = Field(None, gt=0, le=24 * 60)
    intensity_g_per_kwh: float | None = Field(None, ge=0, le=5000)


class TimelineIn(BaseModel):
    slots: list[SlotIn] = Field(max_length=1000)
    current_intensity_g: float | None = Field(None, ge=0, le=5000)


class SlotOut(BaseModel):
    id: int
    start_time: OutDt
    end_time: OutDt
    duration_minutes: int
    intensity_g_per_kwh: float
    kind: Literal["historical", "current", "future"]
    source: str


class AdvanceIn(BaseModel):
    minutes: float = Field(gt=0, le=24 * 60)


class ConfirmIn(BaseModel):
    confirm: bool = False
