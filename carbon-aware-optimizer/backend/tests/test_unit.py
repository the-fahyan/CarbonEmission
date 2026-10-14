from datetime import datetime, timedelta

import pytest

from app.services.emissions import Slot, job_emissions, savings
from app.services.optimizer import JobInput, Policy, Reservation, plan
from app.services.telemetry import validate_timeline

T0 = datetime(2026, 10, 14, 10, 0)


def mk_slots(values, minutes=15):
    return [Slot(T0 + timedelta(minutes=minutes * i), T0 + timedelta(minutes=minutes * (i + 1)), v)
            for i, v in enumerate(values)]


def overlap_count(assigns, jobs, tau):
    d = {j.id: j.duration_min for j in jobs}
    return sum(1 for a in assigns.values() if a.start and a.start <= tau < a.start + timedelta(minutes=d[a.job_id]))


# ---------------- emissions ----------------
def test_emissions_single_slot_matches_formula():
    em, avg, ok = job_emissions(T0, 15, 2.0, mk_slots([700]))
    assert ok and em == pytest.approx(1400) and avg == pytest.approx(700)


def test_emissions_multi_slot_energy_not_double_counted():
    # 30 min, 2 kWh, slots 100 and 300 -> 1 kWh each -> 100 + 300 = 400
    em, avg, ok = job_emissions(T0, 30, 2.0, mk_slots([100, 300]))
    assert ok and em == pytest.approx(400) and avg == pytest.approx(200)


def test_emissions_not_covered_flag():
    _, _, ok = job_emissions(T0, 45, 1.0, mk_slots([100, 100]))
    assert not ok


def test_savings_example_and_zero_baseline():
    s, p = savings(1400, 400)
    assert s == 1000 and p == pytest.approx(71.4286, rel=1e-4)
    assert savings(0, 0) == (0, None)  # no division by zero
    assert savings(None, 5) == (None, None)


# ---------------- telemetry validation ----------------
def test_timeline_validation():
    assert validate_timeline([(T0, 15, 100), (T0 + timedelta(minutes=15), 15, 200)]) == []
    assert any(">= 0" in e for e in validate_timeline([(T0, 15, -1)]))
    assert any("Duplicate" in e for e in validate_timeline([(T0, 15, 1), (T0, 15, 2)]))
    assert any("overlap" in e for e in validate_timeline([(T0, 30, 1), (T0 + timedelta(minutes=15), 15, 2)]))


# ---------------- optimizer ----------------
VALS = [700, 600, 420, 250, 120, 110, 120, 300, 500, 650]


def test_deferrable_waits_for_clean_slot_and_saves():
    j = JobInput(1, "a", 15, 2.0, "normal", True, deadline=T0 + timedelta(hours=2))
    r = plan([j], T0, mk_slots(VALS), Policy(capacity=1), [])
    a = r.assignments[1]
    assert r.ok and r.is_optimal and a.status == "SCHEDULED"
    assert a.emissions < a.baseline_emissions and a.savings_pct > 0
    assert a.start > T0 and a.explanation


def test_non_deferrable_not_delayed():
    j = JobInput(1, "a", 15, 2.0, "normal", False)
    a = plan([j], T0, mk_slots(VALS), Policy(), []).assignments[1]
    assert a.start == T0 and a.added_wait_min == 0


def test_never_before_earliest_and_deadline_respected():
    j = JobInput(1, "a", 30, 1.0, "normal", True, earliest_start=T0 + timedelta(minutes=30),
                 deadline=T0 + timedelta(minutes=90))
    a = plan([j], T0, mk_slots(VALS), Policy(), []).assignments[1]
    assert a.start >= j.earliest_start and a.end <= j.deadline


def test_unschedulable_deadline_has_explanation_and_alternative():
    j = JobInput(1, "a", 120, 1.0, "normal", True, deadline=T0 + timedelta(minutes=30))
    a = plan([j], T0, mk_slots(VALS), Policy(), []).assignments[1]
    assert a.status == "UNSCHEDULABLE" and a.start is None
    assert "deadline" in a.explanation and "Alternative" in a.explanation


def test_never_invents_telemetry_beyond_horizon():
    # 4 slots = 60 min of data; 90-minute job can't be covered
    j = JobInput(1, "a", 90, 1.0, "normal", True)
    a = plan([j], T0, mk_slots([100] * 4), Policy(), []).assignments[1]
    assert a.status == "UNSCHEDULABLE" and "more forecast data" in a.explanation


def test_no_telemetry_unschedulable():
    a = plan([JobInput(1, "a", 15, 1.0, "normal", True)], T0, [], Policy(), []).assignments[1]
    assert a.status == "UNSCHEDULABLE" and "no carbon-intensity telemetry" in a.explanation


def test_capacity_with_multi_slot_duration_never_exceeded():
    # 40-minute jobs on 15-min slots, capacity 2, six jobs: check overlap at every instant
    jobs = [JobInput(i, f"j{i}", 40, 1.0, "normal", i % 2 == 0, deadline=T0 + timedelta(hours=6))
            for i in range(1, 7)]
    r = plan(jobs, T0, mk_slots([300] * 30), Policy(capacity=2), [])
    sched = {k: v for k, v in r.assignments.items() if v.status == "SCHEDULED"}
    assert sched
    for t in range(0, 30 * 15, 5):
        assert overlap_count(sched, jobs, T0 + timedelta(minutes=t)) <= 2


def test_running_reservations_reduce_capacity():
    run = [Reservation(T0 - timedelta(minutes=10), T0 + timedelta(minutes=50))]
    j = JobInput(1, "a", 15, 1.0, "normal", False)
    a = plan([j], T0, mk_slots([100] * 10), Policy(capacity=1), run).assignments[1]
    assert a.start >= T0 + timedelta(minutes=50)
    assert "capacity" in a.explanation


def test_threshold_blocks_deferrable_without_deadline_but_deadline_overrides():
    s = mk_slots([700] * 10)
    w = plan([JobInput(1, "a", 15, 1, "normal", True)], T0, s, Policy(threshold=450), []).assignments[1]
    assert w.status == "WAITING"
    d = plan([JobInput(1, "a", 15, 1, "normal", True, deadline=T0 + timedelta(hours=1))], T0, s,
             Policy(threshold=450), []).assignments[1]
    assert d.status == "SCHEDULED" and "deadline takes precedence" in d.explanation


def test_telemetry_change_changes_plan():
    j = JobInput(1, "a", 15, 1.0, "normal", True, deadline=T0 + timedelta(hours=2))
    a1 = plan([j], T0, mk_slots(VALS), Policy(), []).assignments[1]
    flipped = mk_slots(list(reversed(VALS)))
    a2 = plan([j], T0, flipped, Policy(), []).assignments[1]
    assert a1.start != a2.start


def test_critical_not_delayed_for_carbon_but_respects_deadline():
    j = JobInput(1, "a", 15, 1.0, "critical", True, deadline=T0 + timedelta(minutes=10))
    a = plan([j], T0, mk_slots(VALS), Policy(), []).assignments[1]
    assert a.status == "UNSCHEDULABLE"  # critical does not ignore deadlines
    j2 = JobInput(2, "b", 15, 1.0, "critical", True)
    assert plan([j2], T0, mk_slots(VALS), Policy(), []).assignments[2].start == T0


def test_baseline_and_scheduled_use_same_energy():
    j = JobInput(1, "a", 30, 3.0, "normal", True)
    a = plan([j], T0, mk_slots([300] * 12), Policy(), []).assignments[1]
    assert a.baseline_emissions == pytest.approx(900) and a.emissions == pytest.approx(900)
