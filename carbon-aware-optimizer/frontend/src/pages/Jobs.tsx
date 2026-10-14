import { ArrowDownUp, Search } from "lucide-react";
import { useState } from "react";
import JobDrawer from "../components/JobDrawer";
import JobForm from "../components/JobForm";
import { Empty, ErrorBox, Loading, Progress, StatusBadge } from "../components/ui";
import { useFetch } from "../hooks/useFetch";
import { useLive } from "../hooks/useLive";
import type { JobList } from "../types";
import { fmtG, fmtPct, fmtTime } from "../utils/format";

const COLS: [string, string][] = [["id", "#"], ["name", "Name"], ["priority", "Priority"], ["status", "Status"], ["deadline", "Deadline"], ["duration_minutes", "Runtime"], ["estimated_energy_kwh", "Energy"], ["scheduled_start", "Planned start"], ["savings_g", "Est. savings"]];

export default function Jobs() {
  const [q, setQ] = useState(""); const [status, setStatus] = useState(""); const [priority, setPriority] = useState("");
  const [sort, setSort] = useState("id"); const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [open, setOpen] = useState<number | null>(null);
  const { progress } = useLive();
  const qs = new URLSearchParams({ sort, order, limit: "200", ...(q && { q }), ...(status && { status }), ...(priority && { priority }) });
  const { data, error, loading, reload } = useFetch<JobList>(`/api/jobs?${qs}`);
  const toggle = (k: string) => { if (k === sort) setOrder(order === "asc" ? "desc" : "asc"); else { setSort(k); setOrder("asc"); } };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Job management</h1>
      <JobForm onCreated={reload} />
      <div className="card">
        <div className="mb-3 flex flex-wrap gap-2">
          <div className="relative"><Search className="absolute left-2 top-2 h-4 w-4 text-slate-500" /><input aria-label="Search jobs" className="input pl-8" placeholder="Search name…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <select aria-label="Filter by status" className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{["PENDING", "SCHEDULED", "WAITING", "RUNNING", "COMPLETED", "CANCELLED", "FAILED", "UNSCHEDULABLE"].map((s) => <option key={s}>{s}</option>)}</select>
          <select aria-label="Filter by priority" className="input w-auto" value={priority} onChange={(e) => setPriority(e.target.value)}><option value="">All priorities</option>{["low", "normal", "high", "critical"].map((s) => <option key={s}>{s}</option>)}</select>
          <span className="ml-auto self-center text-xs text-slate-500">{data ? `${data.total} job(s)` : ""}</span>
        </div>
        {loading && !data && <Loading />}
        {error && <ErrorBox message={error} onRetry={reload} />}
        {data && data.items.length === 0 && <Empty>No jobs match. Submit one above or load the demo scenario.</Empty>}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto"><table className="w-full">
            <thead><tr>{COLS.map(([k, label]) => <th key={k} className="th"><button className="inline-flex items-center gap-1" onClick={() => toggle(k)} aria-label={`Sort by ${label}`}>{label}<ArrowDownUp className="h-3 w-3" /></button></th>)}<th className="th">Progress</th></tr></thead>
            <tbody>{data.items.map((j) => (
              <tr key={j.id} tabIndex={0} className="cursor-pointer border-t border-ink-700 hover:bg-ink-800 focus:bg-ink-800 focus:outline-none" onClick={() => setOpen(j.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(j.id)}>
                <td className="td text-slate-500">{j.id}</td><td className="td font-medium">{j.name}{j.is_demo && <span className="ml-1 text-xs text-slate-500">demo</span>}</td>
                <td className="td">{j.priority}{!j.deferrable && <span className="ml-1 text-xs text-amber-300">fixed</span>}</td><td className="td"><StatusBadge status={j.status} /></td>
                <td className="td">{fmtTime(j.deadline)}</td><td className="td">{j.duration_minutes} min</td><td className="td">{j.estimated_energy_kwh} kWh</td>
                <td className="td">{fmtTime(j.scheduled_start)}</td><td className="td text-leaf-400">{fmtG(j.savings_g)} <span className="text-slate-500">({fmtPct(j.savings_pct)})</span></td>
                <td className="td w-28">{j.status === "RUNNING" || j.status === "COMPLETED" ? <Progress value={progress[j.id] ?? j.progress} /> : null}</td></tr>))}</tbody></table></div>)}
      </div>
      {open != null && <JobDrawer jobId={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </div>
  );
}
