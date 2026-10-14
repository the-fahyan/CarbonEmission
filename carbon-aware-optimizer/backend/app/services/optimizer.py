"""Pure (database-free) carbon-aware optimizer built on scipy.optimize.milp.

MODEL
-----
Sets      jobs i, candidate start instants t (the job's ready time + every telemetry slot start
          after it). A candidate exists only if the WHOLE run interval [t, t+d_i) lies inside
          configured telemetry (we never invent readings) and ends by the deadline.
Variable  x[i,t] in {0,1}   job i starts at t.
Cost      c[i,t] = w_c * emissions[i,t]/max_t emissions[i,.]          (0..1, unit-free)
                 + w_wait_i * wait[i,t]/max_t wait[i,.]               (0..1, unit-free)
          w_wait_i = nondeferrable_wait_weight   if job is non-deferrable or critical
                   = w_wait + w_priority * rank  otherwise (rank: low 0 .. critical 3)
Objective minimise  sum c[i,t] x[i,t]  -  U_i * sum_t x[i,t]
          U_i is a big "reward for being scheduled" (>> any cost) so the solver schedules as many
          jobs as capacity allows, preferring higher-priority jobs when forced to choose.
Constraints
  (1) sum_t x[i,t] <= 1                                    each job starts at most once
  (2) for every check instant tau (= every candidate start):
        sum_{i,t : t <= tau < t + d_i} x[i,t]  +  running(tau)  <=  capacity
      This is an interval-overlap constraint: a 40-minute job occupies capacity for 40 minutes,
      not just the 15-minute slot where it starts. (Max overlap of intervals always occurs at
      some interval's start, so checking only start instants is exact.)

BASELINE: the same model and constraints, but cost = waiting time only and no carbon threshold,
i.e. "run each job at the earliest feasible time". Savings compare these two schedules.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from app.services.emissions import Slot, job_emissions, savings

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}


@dataclass
class JobInput:
    id: int
    name: str
    duration_min: int
    energy_kwh: float
    priority: str
    deferrable: bool
    earliest_start: datetime | None = None
    deadline: datetime | None = None

    @property
    def rank(self) -> int:
        return PRIORITY_RANK.get(self.priority, 1)

    @property
    def critical(self) -> bool:
        return self.priority == "critical"


@dataclass
class Policy:
    capacity: int = 2
    threshold: float = 450.0
    w_carbon: float = 1.0
    w_wait: float = 0.25
    w_priority: float = 0.25
    nd_wait: float = 100.0
    critical_ignores_threshold: bool = True
    time_limit_s: float = 20.0


@dataclass
class Reservation:
    start: datetime
    end: datetime


@dataclass
class Cand:
    start: datetime
    end: datetime
    emissions: float
    avg_intensity: float
    wait_min: float


@dataclass
class Assignment:
    job_id: int
    status: str  # SCHEDULED | WAITING | UNSCHEDULABLE
    explanation: str
    start: datetime | None = None
    end: datetime | None = None
    avg_intensity: float | None = None
    emissions: float | None = None
    baseline_start: datetime | None = None
    baseline_emissions: float | None = None
    savings_g: float | None = None
    savings_pct: float | None = None
    added_wait_min: float | None = None
    details: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    ok: bool
    solver_status: str
    is_optimal: bool
    objective: float | None
    baseline_objective: float | None
    variables: int
    solve_ms: float
    assignments: dict[int, Assignment]
    message: str = ""


def _fmt(dt: datetime | None) -> str:
    return "n/a" if dt is None else dt.strftime("%H:%M (%d %b)")


def build_candidates(job: JobInput, now: datetime, slots: list[Slot]) -> tuple[list[Cand], dict]:
    """All feasible (covered + before deadline) starts for a job, plus rejection diagnostics."""
    ready = max(now, job.earliest_start or now)
    starts = [ready] + [s.start for s in slots if s.start > ready]
    cands: list[Cand] = []
    deadline_ok_any = False
    for st in starts:
        end = st + timedelta(minutes=job.duration_min)
        if job.deadline is not None and end > job.deadline:
            continue
        deadline_ok_any = True
        em, avg, covered = job_emissions(st, job.duration_min, job.energy_kwh, slots)
        if not covered:
            continue
        cands.append(Cand(st, end, em, avg, (st - ready).total_seconds() / 60.0))
    diag = {"ready": ready, "deadline_ok_any": deadline_ok_any, "no_telemetry": not slots,
            "telemetry_end": max((s.end for s in slots), default=None)}
    return cands, diag


def _uses_threshold(job: JobInput, p: Policy) -> bool:
    return job.deferrable and not (job.critical and p.critical_ignores_threshold)


def _wait_weight(job: JobInput, p: Policy) -> float:
    if (not job.deferrable) or job.critical:
        return p.nd_wait
    return p.w_wait + p.w_priority * job.rank


def _solve(jobs: list[JobInput], cands: dict[int, list[Cand]], costs: dict[int, list[float]],
           p: Policy, running: list[Reservation], reward: dict[int, float]):
    """Build and solve the MILP. Returns (selected {job_id: cand_idx}, status, optimal, objective, nvars, ms)."""
    var_index: list[tuple[int, int]] = []
    c: list[float] = []
    for j in jobs:
        for k, cost in enumerate(costs.get(j.id, [])):
            var_index.append((j.id, k))
            c.append(cost - reward[j.id])
    n = len(var_index)
    if n == 0:
        return {}, "no_candidates", True, 0.0, 0, 0.0

    dur = {j.id: timedelta(minutes=j.duration_min) for j in jobs}
    rows, cols, vals, rhs = [], [], [], []
    r = 0
    # (1) one start per job
    by_job: dict[int, list[int]] = {}
    for v, (jid, _) in enumerate(var_index):
        by_job.setdefault(jid, []).append(v)
    for jid, vs in by_job.items():
        for v in vs:
            rows.append(r); cols.append(v); vals.append(1.0)
        rhs.append(1.0); r += 1
    # (2) capacity at every candidate start instant
    taus = sorted({cands[jid][k].start for jid, k in var_index})
    for tau in taus:
        used = 0
        row_has = False
        for v, (jid, k) in enumerate(var_index):
            cd = cands[jid][k]
            if cd.start <= tau < cd.end:
                rows.append(r); cols.append(v); vals.append(1.0); row_has = True
        if not row_has:
            continue
        used = sum(1 for rs in running if rs.start <= tau < rs.end)
        rhs.append(max(0.0, float(p.capacity - used))); r += 1

    A = coo_matrix((vals, (rows, cols)), shape=(r, n)).tocsr()
    t0 = time.perf_counter()
    res = milp(c=np.array(c), constraints=LinearConstraint(A, -np.inf, np.array(rhs)),
               integrality=np.ones(n), bounds=Bounds(0, 1), options={"time_limit": p.time_limit_s})
    ms = (time.perf_counter() - t0) * 1000.0
    status_names = {0: "optimal", 1: "time_or_iteration_limit", 2: "infeasible", 3: "unbounded", 4: "solver_error"}
    status = status_names.get(res.status, f"status_{res.status}")
    if res.x is None:
        return None, status, False, None, n, ms
    selected = {var_index[v][0]: var_index[v][1] for v in range(n) if res.x[v] > 0.5}
    return selected, status, res.status == 0, float(res.fun), n, ms


def plan(jobs: list[JobInput], now: datetime, slots: list[Slot], policy: Policy,
         running: list[Reservation], trigger: str = "manual") -> PlanResult:
    """Compute carbon-aware and baseline schedules for `jobs` (queued jobs only; running => reservations)."""
    slots = sorted(slots, key=lambda s: s.start)
    all_cands: dict[int, list[Cand]] = {}
    diags: dict[int, dict] = {}
    for j in jobs:
        cs, d = build_candidates(j, now, slots)
        all_cands[j.id], diags[j.id] = cs, d

    big = 10.0 * (policy.w_carbon + max(policy.nd_wait, policy.w_wait + 3 * policy.w_priority) + 1.0)
    reward = {j.id: big * (1.0 + 0.5 * j.rank) for j in jobs}

    # ---- carbon-aware candidate sets & costs ----
    opt_cands: dict[int, list[Cand]] = {}
    opt_costs: dict[int, list[float]] = {}
    threshold_fallback: set[int] = set()
    no_clean: set[int] = set()
    for j in jobs:
        cs = all_cands[j.id]
        if cs and _uses_threshold(j, policy):
            under = [c for c in cs if c.avg_intensity <= policy.threshold]
            if under:
                cs = under
            elif j.deadline is not None:
                threshold_fallback.add(j.id)  # deadline beats threshold: keep all deadline-feasible candidates
            else:
                no_clean.add(j.id)
                cs = []
        opt_cands[j.id] = cs
        if cs:
            e_ref = max(c.emissions for c in cs)
            w_ref = max(c.wait_min for c in cs)
            ww = _wait_weight(j, policy)
            opt_costs[j.id] = [
                policy.w_carbon * (c.emissions / e_ref if e_ref > 0 else 0.0)
                + ww * (c.wait_min / w_ref if w_ref > 0 else 0.0) for c in cs]

    # ---- baseline: earliest feasible start, same capacity, no threshold ----
    base_costs: dict[int, list[float]] = {}
    for j in jobs:
        cs = all_cands[j.id]
        if cs:
            w_ref = max(c.wait_min for c in cs)
            base_costs[j.id] = [(c.wait_min / w_ref if w_ref > 0 else 0.0) for c in cs]

    sel, status, optimal, obj, nvars, ms = _solve(jobs, opt_cands, opt_costs, policy, running, reward)
    if sel is None:
        return PlanResult(False, status, False, None, None, nvars, ms, {},
                          f"Solver did not return a feasible solution (status: {status}). "
                          "Existing schedule left unchanged.")
    bsel, _bs, _bo, bobj, _bn, bms = _solve(jobs, all_cands, base_costs, policy, running, reward)
    if bsel is None:
        bsel = {}

    out: dict[int, Assignment] = {}
    for j in jobs:
        out[j.id] = _build_assignment(j, now, slots, policy, all_cands[j.id], opt_cands[j.id],
                                      opt_costs.get(j.id, []), sel.get(j.id), bsel.get(j.id),
                                      diags[j.id], j.id in threshold_fallback, j.id in no_clean, trigger)
    return PlanResult(True, status, optimal, obj, bobj, nvars, ms + bms, out,
                      "" if optimal else "Feasible but not proven optimal (solver hit a limit).")


def _build_assignment(j: JobInput, now: datetime, slots: list[Slot], p: Policy, all_c: list[Cand],
                      opt_c: list[Cand], opt_cost: list[float], sel_k: int | None, base_k: int | None,
                      diag: dict, fallback: bool, no_clean: bool, trigger: str) -> Assignment:
    ready: datetime = diag["ready"]
    # ---------- unschedulable (no feasible interval at all) ----------
    if not all_c:
        reasons, alt = [], ""
        if diag["no_telemetry"]:
            reasons.append("no carbon-intensity telemetry is configured")
        elif not diag["deadline_ok_any"]:
            need_end = ready + timedelta(minutes=j.duration_min)
            reasons.append(
                f"the {j.duration_min}-minute runtime cannot finish by the deadline {_fmt(j.deadline)} "
                f"(earliest possible finish is {_fmt(need_end)})")
            alt = f" Alternative: extend the deadline to at least {_fmt(need_end)} (and ensure telemetry covers it)."
        else:
            reasons.append(
                f"the run would extend past the configured telemetry (data ends {_fmt(diag['telemetry_end'])}); "
                "more forecast data is required and none is invented")
            alt = " Alternative: add telemetry slots covering the full runtime."
        return Assignment(j.id, "UNSCHEDULABLE",
                          "Marked unschedulable because " + "; ".join(reasons) + "." + alt,
                          details={"reason": reasons, "ready": ready.isoformat()})
    # ---------- no window under threshold, no deadline => keep waiting ----------
    if no_clean:
        best = min(all_c, key=lambda c: c.emissions)
        return Assignment(
            j.id, "WAITING",
            f"Waiting: the job is deferrable and every feasible start in the configured telemetry exceeds the "
            f"carbon threshold ({p.threshold:.0f} gCO2e/kWh); the cleanest available window is "
            f"{best.avg_intensity:.0f} gCO2e/kWh at {_fmt(best.start)}. It will be re-evaluated when telemetry or "
            f"the threshold changes (set a deadline to force execution).",
            details={"cleanest_start": best.start.isoformat(), "cleanest_intensity": best.avg_intensity})
    # ---------- baseline numbers ----------
    base = all_c[base_k] if base_k is not None else None
    # ---------- capacity-blocked (feasible candidates exist but solver left job out) ----------
    if sel_k is None:
        return Assignment(
            j.id, "WAITING",
            f"Waiting: {len(opt_c)} feasible start(s) exist but every one would exceed the compute capacity "
            f"({p.capacity} concurrent jobs) once higher-ranked work is placed. Re-evaluated when a job finishes.",
            baseline_start=base.start if base else None,
            baseline_emissions=base.emissions if base else None,
            details={"candidates": len(opt_c), "reason": "capacity"})
    chosen = opt_c[sel_k]
    sav, pct = savings(base.emissions if base else None, chosen.emissions)
    added_wait = ((chosen.start - base.start).total_seconds() / 60.0) if base else None

    # ---------- explanation (derived from actual inputs/results) ----------
    ready_c = all_c[0] if all_c and all_c[0].start == ready else None
    cleanest = min(opt_c, key=lambda c: c.emissions)
    unconstrained_k = min(range(len(opt_c)), key=lambda k: opt_cost[k])
    lines = [f"Scheduled {_fmt(chosen.start)} → {_fmt(chosen.end)}: average {chosen.avg_intensity:.0f} "
             f"gCO2e/kWh, estimated {chosen.emissions:.0f} gCO2e."]
    if not j.deferrable:
        lines.append("Job is non-deferrable, so it starts at the earliest slot its constraints allow "
                     "(never delayed for carbon).")
    elif j.critical and p.critical_ignores_threshold:
        lines.append("Critical priority: runs as early as constraints allow; the carbon threshold is not applied "
                     "(policy setting).")
    elif fallback:
        lines.append(f"No window under the {p.threshold:.0f} gCO2e/kWh threshold exists before the deadline, so the "
                     "best deadline-feasible window was used (deadline takes precedence over the threshold).")
    elif chosen.start > ready:
        if ready_c:
            lines.append(
                f"Delayed {chosen.wait_min:.0f} min: starting at {_fmt(ready)} would emit about "
                f"{ready_c.emissions:.0f} gCO2e ({ready_c.avg_intensity:.0f} gCO2e/kWh"
                f"{', above the threshold' if ready_c.avg_intensity > p.threshold else ''}); waiting saves "
                f"{ready_c.emissions - chosen.emissions:.0f} gCO2e.")
    else:
        alt = cleanest if cleanest.start != chosen.start and cleanest.emissions < chosen.emissions else None
        if alt:
            lines.append(
                f"Starting now. A cleaner window at {_fmt(alt.start)} would save {chosen.emissions - alt.emissions:.0f} "
                f"gCO2e but delay the job {alt.wait_min:.0f} min; with the configured weights the wait was not "
                "worth that saving.")
        else:
            lines.append("Starting now: no cleaner feasible window exists in the supplied telemetry.")
    if unconstrained_k != sel_k:
        pref = opt_c[unconstrained_k]
        lines.append(f"Preferred slot {_fmt(pref.start)} was unavailable because it would exceed compute capacity "
                     f"({p.capacity} concurrent jobs); {_fmt(chosen.start)} was the best remaining slot.")
    if j.deadline is not None:
        slack = (j.deadline - chosen.end).total_seconds() / 60.0
        lines.append(f"Finishes {_fmt(chosen.end)}, {slack:.0f} min before the deadline {_fmt(j.deadline)}.")
    if base and sav is not None:
        pct_txt = f" ({pct:.1f}%)" if pct is not None else ""
        lines.append(f"Baseline (earliest feasible start {_fmt(base.start)}) would emit {base.emissions:.0f} gCO2e; "
                     f"estimated saving {sav:.0f} gCO2e{pct_txt}, extra wait {added_wait:.0f} min.")
    elif base is None:
        lines.append("Baseline was not feasible under capacity, so savings are not reported for this job.")
    return Assignment(
        j.id, "SCHEDULED", " ".join(lines), chosen.start, chosen.end, chosen.avg_intensity, chosen.emissions,
        base.start if base else None, base.emissions if base else None, sav, pct, added_wait,
        details={"candidates": len(opt_c), "cleanest_start": cleanest.start.isoformat(),
                 "cleanest_emissions": cleanest.emissions, "capacity_displaced": unconstrained_k != sel_k,
                 "threshold_fallback": fallback})
