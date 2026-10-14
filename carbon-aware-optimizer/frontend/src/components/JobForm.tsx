import { Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, errMsg } from "../api/client";
import { fmtTime, fromLocalInput, validateJobForm } from "../utils/format";
import { useToast } from "./ui";

const WORKLOADS = ["ml_training", "batch_etl", "video_render", "report_generation", "data_backup", "security_scan"];
const blank = { name: "", description: "", workload_type: "batch_etl", duration_minutes: "30", estimated_energy_kwh: "1.5", priority: "normal", earliest_start: "", deadline: "", deferrable: true, simulate_failure: false };

export default function JobForm({ onCreated }: { onCreated: () => void }) {
  const [v, setV] = useState(blank);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const set = (k: string, val: string | boolean) => setV((p) => ({ ...p, [k]: val }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const errs = validateJobForm(v);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const job = await api<{ id: number; status: string; scheduled_start: string | null }>("/api/jobs", { method: "POST", json: {
        name: v.name.trim(), description: v.description, workload_type: v.workload_type, duration_minutes: Number(v.duration_minutes),
        estimated_energy_kwh: Number(v.estimated_energy_kwh), priority: v.priority, deferrable: v.deferrable, simulate_failure: v.simulate_failure,
        earliest_start: fromLocalInput(v.earliest_start), deadline: fromLocalInput(v.deadline) } });
      toast("ok", `Job #${job.id} ${job.status}${job.scheduled_start ? ` — planned ${fmtTime(job.scheduled_start)}` : ""}`);
      setV(blank);
      onCreated();
    } catch (err) { toast("err", errMsg(err)); } finally { setBusy(false); }
  };
  const Err = ({ k }: { k: string }) => (errors[k] ? <p role="alert" className="mt-1 text-xs text-red-300">{errors[k]}</p> : null);

  return (
    <form onSubmit={submit} className="card grid gap-3 md:grid-cols-4" aria-label="Submit job" noValidate>
      <div className="md:col-span-2"><label className="label" htmlFor="jn">Job name</label><input id="jn" className="input" value={v.name} onChange={(e) => set("name", e.target.value)} /><Err k="name" /></div>
      <div><label className="label" htmlFor="jw">Workload type</label><select id="jw" className="input" value={v.workload_type} onChange={(e) => set("workload_type", e.target.value)}>{WORKLOADS.map((w) => <option key={w}>{w}</option>)}</select></div>
      <div><label className="label" htmlFor="jp">Priority</label><select id="jp" className="input" value={v.priority} onChange={(e) => set("priority", e.target.value)}>{["low", "normal", "high", "critical"].map((p) => <option key={p}>{p}</option>)}</select></div>
      <div className="md:col-span-4"><label className="label" htmlFor="jd">Description</label><input id="jd" className="input" value={v.description} onChange={(e) => set("description", e.target.value)} /></div>
      <div><label className="label" htmlFor="jr">Runtime (minutes)</label><input id="jr" className="input" inputMode="numeric" value={v.duration_minutes} onChange={(e) => set("duration_minutes", e.target.value)} /><Err k="duration_minutes" /></div>
      <div><label className="label" htmlFor="je">Energy (kWh, estimated)</label><input id="je" className="input" inputMode="decimal" value={v.estimated_energy_kwh} onChange={(e) => set("estimated_energy_kwh", e.target.value)} /><Err k="estimated_energy_kwh" /></div>
      <div><label className="label" htmlFor="js">Earliest start (optional)</label><input id="js" type="datetime-local" className="input" value={v.earliest_start} onChange={(e) => set("earliest_start", e.target.value)} /></div>
      <div><label className="label" htmlFor="jl">Deadline (optional)</label><input id="jl" type="datetime-local" className="input" value={v.deadline} onChange={(e) => set("deadline", e.target.value)} /><Err k="deadline" /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.deferrable} onChange={(e) => set("deferrable", e.target.checked)} /> Deferrable</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.simulate_failure} onChange={(e) => set("simulate_failure", e.target.checked)} /> Simulate failure (demo retry)</label>
      <div className="flex items-end justify-end md:col-span-2"><button className="btn btn-primary" disabled={busy}><Send className="h-4 w-4" />{busy ? "Submitting…" : "Submit job"}</button></div>
    </form>
  );
}
