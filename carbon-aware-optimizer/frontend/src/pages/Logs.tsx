import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../api/client";
import { Empty, ErrorBox, Loading, Metric, Progress, StatusBadge } from "../components/ui";
import { useFetch } from "../hooks/useFetch";
import { useLive } from "../hooks/useLive";
import type { EmissionRow, JobList, LogRow, SavingsReport } from "../types";
import { fmtG, fmtPct, fmtTime } from "../utils/format";

export default function Logs() {
  const [jobId, setJobId] = useState(""); const [level, setLevel] = useState(""); const [text, setText] = useState(""); const [auto, setAuto] = useState(true);
  const qs = new URLSearchParams({ limit: "300", ...(jobId && { job_id: jobId }), ...(level && { level }) });
  const hist = useFetch<LogRow[]>(`/api/logs?${qs}`);
  const jobs = useFetch<JobList>("/api/jobs?limit=200&sort=id&order=asc");
  const em = useFetch<EmissionRow[]>("/api/analytics/emissions");
  const sv = useFetch<SavingsReport>("/api/analytics/savings");
  const { logs: live, progress } = useLive();

  // History from the API + anything streamed since (deduped by id) => live-updating without refresh.
  const merged = useMemo(() => {
    const map = new Map<number, LogRow>();
    (hist.data ?? []).forEach((l) => map.set(l.id, l));
    live.filter((l) => (!jobId || String(l.job_id) === jobId) && (!level || l.level === level)).forEach((l) => map.set(l.id, l));
    return [...map.values()].sort((a, b) => a.id - b.id).filter((l) => !text || l.message.toLowerCase().includes(text.toLowerCase())).slice(-400);
  }, [hist.data, live, jobId, level, text]);
  useEffect(() => { if (auto) document.getElementById("log-end")?.scrollIntoView({ block: "end" }); }, [merged, auto]);

  if (hist.error) return <ErrorBox message={hist.error} onRetry={hist.reload} />;
  const running = jobs.data?.items.filter((j) => j.status === "RUNNING") ?? [];
  const done = jobs.data?.items.filter((j) => ["COMPLETED", "FAILED", "CANCELLED"].includes(j.status)) ?? [];
  const r = sv.data;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-xl font-semibold">Execution logs &amp; analytics</h1>
        <div className="flex gap-2"><a className="btn" href={apiUrl("/api/logs/export.csv")} download><Download className="h-4 w-4" />Logs CSV</a>
          <a className="btn" href={apiUrl("/api/analytics/export.csv")} download><Download className="h-4 w-4" />Emissions CSV</a></div></div>

      <div className="card"><h2 className="mb-2 text-sm font-semibold">Running jobs</h2>
        {!running.length ? <Empty>No job is running.</Empty> : <div className="space-y-3">{running.map((j) => (<div key={j.id}><div className="mb-1 flex justify-between text-sm"><span>{j.name} <span className="text-xs text-slate-500">({j.duration_minutes} simulated min)</span></span><span>{Math.round((progress[j.id] ?? j.progress) * 100)}%</span></div><Progress value={progress[j.id] ?? j.progress} /></div>))}</div>}</div>

      <div className="card">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <select aria-label="Filter by job" className="input w-auto" value={jobId} onChange={(e) => setJobId(e.target.value)}><option value="">All jobs / system</option>{jobs.data?.items.map((j) => <option key={j.id} value={j.id}>#{j.id} {j.name}</option>)}</select>
          <select aria-label="Filter by severity" className="input w-auto" value={level} onChange={(e) => setLevel(e.target.value)}><option value="">All severities</option>{["INFO", "WARN", "ERROR"].map((l) => <option key={l}>{l}</option>)}</select>
          <input aria-label="Search log text" className="input w-56" placeholder="Search text…" value={text} onChange={(e) => setText(e.target.value)} />
          <label className="ml-auto flex items-center gap-2 text-xs"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />Auto-scroll</label>
        </div>
        {hist.loading && !hist.data ? <Loading /> : !merged.length ? <Empty>No log entries match.</Empty> : (
          <div className="h-72 overflow-auto rounded-lg bg-ink-950 p-2 font-mono text-xs" role="log" aria-live="polite">
            {merged.map((l) => (<div key={l.id}><span className="text-slate-500">{fmtTime(l.sim_time)}</span> <span className={l.level === "ERROR" ? "text-red-300" : l.level === "WARN" ? "text-amber-300" : "text-leaf-400"}>{l.level.padEnd(5)}</span> {l.job_id != null && <span className="text-sky-300">#{l.job_id} </span>}{l.message}</div>))}
            <div id="log-end" /></div>)}</div>

      <div className="grid gap-3 md:grid-cols-2">
        <Metric label="Planned (scheduled + running)" value={r ? `${fmtG(r.planned.baseline_g)} → ${fmtG(r.planned.optimized_g)}` : "—"} sub={r ? `${r.planned.jobs} job(s) · savings ${fmtG(r.planned.savings_g)} (${fmtPct(r.planned.savings_pct)}) — estimated` : undefined} accent />
        <Metric label="Completed (simulated execution)" value={r ? `${fmtG(r.completed.baseline_g)} → ${fmtG(r.completed.optimized_g)}` : "—"} sub={r ? `${r.completed.jobs} job(s) · savings ${fmtG(r.completed.savings_g)} (${fmtPct(r.completed.savings_pct)})` : undefined} />
      </div>
      {r && r.excluded.length > 0 && <p className="text-xs text-amber-300">Not included in comparisons: {r.excluded.map((x) => `#${x.job_id} ${x.name} (${x.reason})`).join("; ")}.</p>}
      <p className="text-xs text-slate-500">{r?.scope}. {r?.note}</p>

      <div className="card"><h2 className="mb-2 text-sm font-semibold">Estimated emissions by job</h2>
        {!em.data?.length ? <Empty>No scheduled jobs yet.</Empty> : <div className="overflow-x-auto"><table className="w-full"><thead><tr><th className="th">Job</th><th className="th">Status</th><th className="th">Baseline</th><th className="th">Planned</th><th className="th">Actual (est.)</th><th className="th">Savings</th></tr></thead>
          <tbody>{em.data.map((e) => (<tr key={e.job_id} className="border-t border-ink-700"><td className="td">{e.name}</td><td className="td"><StatusBadge status={e.status as never} /></td><td className="td">{fmtG(e.baseline_g)}</td><td className="td">{fmtG(e.planned_g)}</td><td className="td">{fmtG(e.actual_g)}</td><td className="td text-leaf-400">{fmtG(e.savings_g)} ({fmtPct(e.savings_pct)})</td></tr>))}</tbody></table></div>}</div>

      <div className="card"><h2 className="mb-2 text-sm font-semibold">Execution history</h2>
        {!done.length ? <Empty>No finished jobs yet.</Empty> : <table className="w-full"><thead><tr><th className="th">Job</th><th className="th">Outcome</th><th className="th">Sim start</th><th className="th">Sim end</th><th className="th">Runtime (sim)</th></tr></thead>
          <tbody>{done.map((j) => (<tr key={j.id} className="border-t border-ink-700"><td className="td">{j.name}</td><td className="td"><StatusBadge status={j.status} /></td><td className="td">{fmtTime(j.actual_start)}</td><td className="td">{fmtTime(j.actual_end)}</td><td className="td">{j.duration_minutes} min</td></tr>))}</tbody></table>}</div>
    </div>
  );
}
