import { EmissionsChart, IntensityChart, StatusPie } from "../components/charts";
import { Empty, ErrorBox, Loading, Metric } from "../components/ui";
import { useFetch } from "../hooks/useFetch";
import { useLive } from "../hooks/useLive";
import type { EmissionRow, JobList, Settings, Summary, Telemetry } from "../types";
import { fmtG, fmtPct, fmtTime } from "../utils/format";

export default function Overview() {
  const s = useFetch<Summary>("/api/analytics/summary");
  const t = useFetch<Telemetry>("/api/telemetry");
  const e = useFetch<EmissionRow[]>("/api/analytics/emissions");
  const st = useFetch<Settings>("/api/settings");
  const up = useFetch<JobList>("/api/jobs?status=SCHEDULED&sort=scheduled_start&order=asc&limit=6");
  const { logs } = useLive();
  const err = s.error || t.error || e.error;
  if (err) return <ErrorBox message={err} onRetry={() => { s.reload(); t.reload(); e.reload(); }} />;
  if (!s.data || !t.data) return <Loading />;
  const d = s.data;
  const cur = d.current_intensity;

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between"><h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-xs text-slate-500">Emission figures are <b>estimates</b> from manually configured, simulated telemetry — not measurements.</p></div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Awaiting scheduling / start" value={d.awaiting} />
        <Metric label="Running" value={d.running} />
        <Metric label="Completed" value={d.completed} />
        <Metric label="Unschedulable" value={d.unschedulable} />
        <Metric label="Baseline emissions (est.)" value={fmtG(d.baseline_g)} sub={`${d.comparable_jobs} comparable job(s)`} />
        <Metric label="Optimized emissions (est.)" value={fmtG(d.optimized_g)} sub="planned + completed" />
        <Metric accent label="Estimated savings" value={fmtG(d.savings_g)} sub={fmtPct(d.savings_pct)} />
        <Metric label="Configured intensity now" value={cur.intensity == null ? "—" : `${cur.intensity.toFixed(0)}`} sub={`gCO₂e/kWh · ${cur.source === "timeline_slot" ? "from timeline slot" : cur.source === "manual_current_entry" ? "manual entry" : "not configured"}`} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card"><h2 className="mb-2 text-sm font-semibold">Carbon-intensity timeline (configured, simulated)</h2>
          {t.data.slots.length ? <IntensityChart slots={t.data.slots} threshold={st.data?.carbon_threshold_g} now={t.data.sim_time} /> : <Empty>No telemetry yet — open Telemetry and load the demo timeline.</Empty>}</div>
        <div className="card"><h2 className="mb-2 text-sm font-semibold">Baseline vs carbon-aware emissions (per job, estimated)</h2>
          {e.data && e.data.some((r) => r.baseline_g != null) ? <EmissionsChart rows={e.data} /> : <Empty>Nothing scheduled yet.</Empty>}</div>
        <div className="card"><h2 className="mb-2 text-sm font-semibold">Job status distribution</h2>
          {Object.keys(d.counts).length ? <StatusPie counts={d.counts} /> : <Empty>No jobs yet.</Empty>}</div>
        <div className="card"><h2 className="mb-2 text-sm font-semibold">Upcoming scheduled jobs</h2>
          {!up.data?.items.length ? <Empty>No scheduled jobs.</Empty> : (
            <ul className="divide-y divide-ink-700 text-sm">{up.data.items.map((j) => (
              <li key={j.id} className="flex justify-between py-2"><span>{j.name}</span><span className="text-slate-400">{fmtTime(j.scheduled_start)} · {j.scheduled_intensity?.toFixed(0)} g/kWh</span></li>))}</ul>)}</div>
      </div>
      <div className="card"><h2 className="mb-2 text-sm font-semibold">Recent execution logs (live)</h2>
        {!logs.length ? <Empty>No live events yet.</Empty> : (
          <div className="max-h-48 overflow-auto font-mono text-xs">{[...logs].reverse().slice(0, 25).map((l) => (
            <div key={l.id}><span className="text-slate-500">{fmtTime(l.sim_time)}</span> <span className={l.level === "ERROR" ? "text-red-300" : l.level === "WARN" ? "text-amber-300" : "text-slate-300"}>[{l.level}]</span> {l.message}</div>))}</div>)}</div>
    </div>
  );
}
