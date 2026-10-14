import { Play, RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errMsg } from "../api/client";
import { Empty, ErrorBox, Loading, Metric, StatusBadge, useToast } from "../components/ui";
import { useFetch } from "../hooks/useFetch";
import type { Preview, Run, SchedStatus, Settings } from "../types";
import { fmtG, fmtPct, fmtTime } from "../utils/format";

const FIELDS: [keyof Settings, string, string][] = [
  ["capacity", "Max concurrent jobs", "Compute capacity: overlapping jobs never exceed this."],
  ["carbon_threshold_g", "Carbon threshold (gCO₂e/kWh)", "Deferrable jobs avoid windows above this (deadline overrides)."],
  ["weight_carbon", "Weight: emissions", "Weight on normalized emissions (0–1 scale)."],
  ["weight_wait", "Weight: waiting", "Weight on normalized waiting time."],
  ["weight_priority", "Weight: priority", "Extra waiting weight per priority rank (low 0 … critical 3)."],
  ["nondeferrable_wait_weight", "Weight: non-deferrable/critical wait", "Large, so these start as early as possible."],
  ["simulation_speed", "Simulation speed", "Simulated minutes per real minute (60 → 1 s = 1 min)."],
];

export default function Scheduling() {
  const status = useFetch<SchedStatus>("/api/scheduler/status");
  const hist = useFetch<Run[]>("/api/scheduler/history?limit=10");
  const prev = useFetch<Preview>("/api/scheduler/preview");
  const [form, setForm] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { if (status.data && !form) setForm(status.data.settings); }, [status.data, form]);

  const run = async () => { setBusy(true); try { const r = await api<Run>("/api/scheduler/run", { method: "POST" }); toast(r.committed ? "ok" : "err", r.summary); } catch (e) { toast("err", errMsg(e)); } finally { setBusy(false); } };
  const save = async () => {
    if (!form) return;
    const payload = { ...Object.fromEntries(FIELDS.map(([k]) => [k, Number(form[k])])), critical_ignores_threshold: form.critical_ignores_threshold, auto_schedule: form.auto_schedule };
    try { await api("/api/settings", { method: "PATCH", json: payload }); toast("ok", "Settings saved; queued jobs rescheduled."); setForm(null); status.reload(); }
    catch (e) { toast("err", errMsg(e)); }
  };

  if (status.error) return <ErrorBox message={status.error} onRetry={status.reload} />;
  if (!status.data) return <Loading />;
  const s = status.data; const last = s.last_run;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-xl font-semibold">Scheduling &amp; optimization</h1>
        <button className="btn btn-primary" onClick={run} disabled={busy}><Play className="h-4 w-4" />{busy ? "Optimizing…" : "Run optimization / reschedule"}</button></div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Optimizer status" value={last ? last.solver_status : "not run"} sub={last ? `${last.is_optimal ? "proven optimal" : "feasible, not proven optimal"} · ${last.method}` : undefined} accent={!!last?.is_optimal} />
        <Metric label="Objective value" value={last?.objective_value?.toFixed(3) ?? "—"} sub={last ? `${last.variables} variables · ${last.solve_ms.toFixed(0)} ms` : undefined} />
        <Metric label="Available capacity" value={`${s.available_capacity} / ${s.capacity}`} sub={`${s.running_jobs} running · ${s.queued_jobs} queued`} />
        <Metric label="Last run" value={last ? `#${last.id}` : "—"} sub={last?.summary} />
      </div>

      <div className="card"><h2 className="mb-3 text-sm font-semibold">Policy settings (balanced carbon-aware)</h2>
        {form && <div className="grid gap-3 md:grid-cols-3">
          {FIELDS.map(([k, label, help]) => (<div key={k}><label className="label" htmlFor={`f-${k}`}>{label}</label><input id={`f-${k}`} className="input" inputMode="decimal" value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value as never })} /><p className="mt-1 text-xs text-slate-500">{help}</p></div>))}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.critical_ignores_threshold} onChange={(e) => setForm({ ...form, critical_ignores_threshold: e.target.checked })} />Critical jobs ignore carbon threshold (never deadlines/capacity)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.auto_schedule} onChange={(e) => setForm({ ...form, auto_schedule: e.target.checked })} />Auto-reschedule on changes</label>
          <div className="flex items-end justify-end"><button className="btn btn-primary" onClick={save}><Save className="h-4 w-4" />Save settings</button></div>
        </div>}</div>

      <div className="card"><div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">Before / after (dry-run preview of queued jobs — nothing is applied)</h2><button className="btn" onClick={prev.reload}><RefreshCw className="h-4 w-4" />Refresh preview</button></div>
        {!prev.data?.items.length ? <Empty>No queued jobs to plan.</Empty> : (
          <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Job</th><th className="th">Current</th><th className="th">Current start</th><th className="th">Proposed</th><th className="th">Proposed start</th><th className="th">Baseline start</th><th className="th">Baseline → proposed emissions</th><th className="th">Savings</th></tr></thead>
            <tbody>{prev.data.items.map((i) => (<tr key={i.job_id} className="border-t border-ink-700"><td className="td font-medium">{i.name}</td><td className="td"><StatusBadge status={i.current_status as never} /></td><td className="td">{fmtTime(i.current_start)}</td><td className="td"><StatusBadge status={i.proposed_status as never} /></td><td className="td">{fmtTime(i.proposed_start)}</td><td className="td">{fmtTime(i.baseline_start)}</td>
              <td className="td">{fmtG(i.baseline_emissions_g)} → {fmtG(i.proposed_emissions_g)}</td><td className="td text-leaf-400">{fmtG(i.savings_g)} ({fmtPct(i.savings_pct)})</td></tr>))}</tbody></table></div>)}</div>

      <div className="card"><h2 className="mb-2 text-sm font-semibold">Waiting / unschedulable diagnostics</h2>
        {!s.diagnostics.length ? <Empty>No waiting or unschedulable jobs.</Empty> : <ul className="space-y-2 text-sm">{s.diagnostics.map((d) => (<li key={d.job_id} className="rounded-lg border border-ink-600 p-2"><b>#{d.job_id} {d.name}</b> <StatusBadge status={d.status as never} /><div className="mt-1 text-slate-300">{d.explanation}</div></li>))}</ul>}</div>

      <div className="card"><h2 className="mb-2 text-sm font-semibold">Scheduling audit log</h2>
        {!hist.data?.length ? <Empty>No runs yet.</Empty> : (<table className="w-full"><thead><tr><th className="th">Run</th><th className="th">Sim time</th><th className="th">Solver</th><th className="th">Summary</th></tr></thead>
          <tbody>{hist.data.map((r) => (<tr key={r.id} className="border-t border-ink-700"><td className="td">#{r.id}</td><td className="td">{fmtTime(r.sim_time)}</td><td className="td">{r.solver_status}{r.committed ? "" : " (no changes)"}</td><td className="td text-slate-300">{r.summary}</td></tr>))}</tbody></table>)}</div>
    </div>
  );
}
