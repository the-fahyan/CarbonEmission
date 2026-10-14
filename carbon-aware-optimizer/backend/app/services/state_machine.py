"""Job lifecycle. Every status change goes through `transition` so illegal moves are impossible.

PENDING       -> SCHEDULED | WAITING | UNSCHEDULABLE | CANCELLED
SCHEDULED     -> RUNNING | WAITING | UNSCHEDULABLE | CANCELLED   (re-planning may also move it)
WAITING       -> SCHEDULED | UNSCHEDULABLE | CANCELLED
UNSCHEDULABLE -> SCHEDULED | WAITING | PENDING(retry) | CANCELLED
RUNNING       -> COMPLETED | FAILED | CANCELLED                 (only the worker starts/finishes)
FAILED        -> PENDING (retry)
CANCELLED     -> PENDING (retry)
COMPLETED     -> (terminal)
"""
from __future__ import annotations

import threading

from app.models import Job

# One lock serialises every writer (API handlers, scheduler, worker) -> consistent job state.
STATE_LOCK = threading.RLock()

TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"SCHEDULED", "WAITING", "UNSCHEDULABLE", "CANCELLED"},
    "SCHEDULED": {"RUNNING", "WAITING", "UNSCHEDULABLE", "CANCELLED"},
    "WAITING": {"SCHEDULED", "UNSCHEDULABLE", "CANCELLED"},
    "UNSCHEDULABLE": {"SCHEDULED", "WAITING", "PENDING", "CANCELLED"},
    "RUNNING": {"COMPLETED", "FAILED", "CANCELLED"},
    "FAILED": {"PENDING"},
    "CANCELLED": {"PENDING"},
    "COMPLETED": set(),
}
CANCELLABLE = {"PENDING", "SCHEDULED", "WAITING", "RUNNING", "UNSCHEDULABLE"}
RETRYABLE = {"FAILED", "CANCELLED", "UNSCHEDULABLE"}
QUEUED = ["PENDING", "SCHEDULED", "WAITING", "UNSCHEDULABLE"]  # eligible for (re)scheduling


class InvalidTransition(Exception):
    pass


def transition(job: Job, new_status: str, reason: str = "") -> None:
    if job.status == new_status:
        if reason:
            job.status_reason = reason
        return
    if new_status not in TRANSITIONS.get(job.status, set()):
        raise InvalidTransition(f"Job {job.id}: cannot move from {job.status} to {new_status}.")
    job.status = new_status
    job.status_reason = reason
