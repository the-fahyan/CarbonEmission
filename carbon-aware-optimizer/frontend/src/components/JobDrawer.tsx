import { useEffect, useState } from "react";
import { api, errMsg } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useLive } from "../hooks/useLive";
import type { Decision, Job, LogRow } from "../types";
import { fmtG, fmtPct, fmtTime } from "../utils/format";
import { Confirm, ErrorBox, Loading, Modal, Progress, StatusBadge, useToast } from "./ui";

export default function JobDrawer({ jobId, onClose, onChanged }: { jobId: number; onClose: () => void; onChanged: () => void }) {
  const { data: job, error, loading, reload } = useFetch<Job>(`/api/jobs/${jobId}`);
  const { data: decisions } = useFetch<Decision[]>(`/api/jobs/${jobId}/decisions`);
  const { data: logs } = useFetch<LogRow[]>(`/api/jobs/${jobId}/logs`);
  const { progress } = useLive();
  const toast = useToast();
  const [confirm, setConfirm] = useState<"cancel" | "retry" | null>(null);
  useEffect(() => { reload(); }, [onChanged]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (kind: "cancel" | "retry") => {
    setConfirm(null);
    try { await api(`/api/jobs/${jobId}/${kind}`, { method: "POST" }); toast("ok", `Job ${kind === "cancel" ? "cancelled" : "re-queued"}.`); onChanged(); reload(); }
    catch (e) { toast("err", errMsg(e)); }
  };
  const canCancel = job && ["PENDING", "SCHEDULED", "WAITING", "RUNNING", "UNSCHEDULABLE"].includes(job.status);
  const canRetry = job && ["FAILED", "CANCELLED", "UNSCHEDULABLE"].includes(job.status);

  return (
    <Modal title={job ? `Job #${job.id} — ${job.name}` : "Job details"} onClose={onClose} wide>
      {loading && <Loading />}
      {error && <ErrorBox message={error} onRetry={reload} />}
      {job && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={job.status} />
            <span className="text-slate-400">{job.priority} priority · {job.deferrable ? "deferrable" : "non-deferrable"} · {job.duration_minutes} min · {job.estimated_energy_kwh} kWh</span></div>
          {job.status === "RUNNING" && <Progress value={progress[job.id] ?? job.progress} />}
          <p className="text-slate-300">{job.description || <i className="text-slate-500">No description</i>}</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
            <dt className="text-slate-500">Deadline</dt><dd>{fmtTime(job.deadline)}</dd>
            <dt className="text-slate-500">Planned start (simulated)</dt><dd>{fmtTime(job.scheduled_start)}</dd>
            <dt className="text-slate-500">Baseline start</dt><dd>{fmtTime(job.baseline_start)}</dd>
            <dt className="text-slate-500">Baseline emissions (estimate)</dt><dd>{fmtG(job.baseline_emissions_g)}</dd>
            <dt className="text-slate-500">Scheduled emissions (estimate)</dt><dd>{fmtG(job.scheduled_emissions_g)}</dd>
            <dt className="text-slate-500">Estimated savings</dt><dd className="text-leaf-400">{fmtG(job.savings_g)} ({fmtPct(job.savings_pct)})</dd>
            <dt className="text-slate-500">Extra waiting vs baseline</dt><dd>{job.added_wait_minutes == null ? "—" : `${job.added_wait_minutes.toFixed(0)} min`}</dd>
            <dt className="text-slate-500">Actual start / end (simulated)</dt><dd>{fmtTime(job.actual_start)} / {fmtTime(job.actual_end)}</dd>
            <dt className="text-slate-500">Actual emissions (est. from timeline)</dt><dd>{fmtG(job.actual_emissions_g)}</dd>
          </dl>
          <section><h3 className="mb-1 font-semibold">Current scheduling explanation</h3>
            <p className="rounded-lg bg-ink-800 p-3 text-slate-300">{job.scheduling_explanation || "Not scheduled yet."}</p></section>
          <section><h3 className="mb-1 font-semibold">Decision history</h3>
            {!decisions?.length ? <p className="text-slate-500">No decisions recorded yet.</p> : (
              <ol className="space-y-2">{decisions.map((d) => (
                <li key={d.id} className="rounded-lg border border-ink-600 p-2">
                  <div className="text-xs text-slate-500">{fmtTime(d.sim_time)} (sim) · {d.previous_status} → {d.new_status}{d.intensity_used != null && ` · ${d.intensity_used.toFixed(0)} gCO₂e/kWh`}</div>
                  <div>{d.explanation}</div></li>))}</ol>)}</section>
          <section><h3 className="mb-1 font-semibold">Execution attempts</h3>
            {!job.attempts?.length ? <p className="text-slate-500">Never executed.</p> : (
              <table className="w-full"><thead><tr><th className="th">#</th><th className="th">State</th><th className="th">Sim start</th><th className="th">Wall elapsed</th><th className="th">Note</th></tr></thead>
                <tbody>{job.attempts.map((a) => (<tr key={a.id} className="border-t border-ink-700"><td className="td">{a.attempt_number}</td><td className="td">{a.state}</td><td className="td">{fmtTime(a.sim_started_at)}</td>
                  <td className="td">{a.wall_finished_at ? `${Math.max(0, (new Date(a.wall_finished_at).getTime() - new Date(a.wall_started_at).getTime()) / 1000).toFixed(0)} s` : "running"}</td><td className="td">{a.note}</td></tr>))}</tbody></table>)}</section>
          <section><h3 className="mb-1 font-semibold">Logs</h3>
            <div className="max-h-40 overflow-auto rounded-lg bg-ink-950 p-2 font-mono text-xs">{(logs ?? []).map((l) => <div key={l.id}><span className="text-slate-500">{fmtTime(l.sim_time)}</span> [{l.level}] {l.message}</div>)}</div></section>
          <div className="flex justify-end gap-2">
            {canRetry && <button className="btn" onClick={() => setConfirm("retry")}>Retry</button>}
            {canCancel && <button className="btn btn-danger" onClick={() => setConfirm("cancel")}>Cancel job</button>}
          </div>
        </div>
      )}
      {confirm && <Confirm title={confirm === "cancel" ? "Cancel this job?" : "Retry this job?"} danger={confirm === "cancel"}
        message={confirm === "cancel" ? "A running job will be stopped; history is kept." : "A new execution attempt will be created; earlier attempts stay in the history."}
        confirmLabel={confirm === "cancel" ? "Cancel job" : "Retry"} onConfirm={() => act(confirm)} onCancel={() => setConfirm(null)} />}
    </Modal>
  );
}
