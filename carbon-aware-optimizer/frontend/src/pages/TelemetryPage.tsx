import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, errMsg } from "../api/client";
import { IntensityChart } from "../components/charts";
import { Confirm, Empty, ErrorBox, Loading, Metric, useToast } from "../components/ui";
import { useFetch } from "../hooks/useFetch";
import type { Settings, Telemetry } from "../types";
import { fmtTime, fromLocalInput, toLocalInput } from "../utils/format";

interface Row { key: string; start: string; dur: string; val: string; kind?: string }

export default function TelemetryPage() {
  const { data, error, loading, reload } = useFetch<Telemetry>("/api/telemetry");
  const st = useFetch<Settings>("/api/settings");
  const [rows, setRows] = useState<Row[]>([]);
  const [cur, setCur] = useState("");
  const [errs, setErrs] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (data && !dirty) {
      setRows(data.slots.map((s) => ({ key: String(s.id), start: toLocalInput(s.start_time), dur: String(s.duration_minutes), val: String(s.intensity_g_per_kwh), kind: s.kind })));
      setCur(data.manual_current_intensity_g == null ? "" : String(data.manual_current_intensity_g));
    }
  }, [data, dirty]);

  const upd = (i: number, k: keyof Row, v: string) => { setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x))); setDirty(true); };
  const addRow = () => {
    const last = rows[rows.length - 1];
    const dur = Number(last?.dur ?? st.data?.default_slot_minutes ?? 15) || 15;
    const start = last ? toLocalInput(new Date(new Date(last.start).getTime() + dur * 60000).toISOString()) : toLocalInput(new Date().toISOString());
    setRows([...rows, { key: `new${Date.now()}`, start, dur: String(dur), val: last?.val ?? "300" }]); setDirty(true);
  };
  const del = (i: number) => { setRows(rows.filter((_, j) => j !== i)); setDirty(true); };

  const save = async () => {
    const local: string[] = [];
    rows.forEach((r, i) => {
      if (!r.start) local.push(`Row ${i + 1}: start time is required.`);
      if (!(Number(r.dur) > 0)) local.push(`Row ${i + 1}: duration must be > 0 minutes.`);
      if (r.val === "" || !(Number(r.val) >= 0)) local.push(`Row ${i + 1}: intensity must be a number ≥ 0.`);
    });
    if (cur !== "" && !(Number(cur) >= 0)) local.push("Current intensity must be ≥ 0.");
    setErrs(local);
    if (local.length) return;
    try {
      await api("/api/telemetry", { method: "PUT", json: {
        slots: rows.map((r) => ({ start_time: fromLocalInput(r.start), duration_minutes: Number(r.dur), intensity_g_per_kwh: Number(r.val) })),
        current_intensity_g: cur === "" ? null : Number(cur) } });
      toast("ok", "Timeline saved; queued jobs were rescheduled."); setDirty(false); setErrs([]); reload();
    } catch (e) { setErrs(e instanceof ApiError && e.details.length ? e.details : [errMsg(e)]); }
  };
  const resetDemo = async () => {
    setConfirmReset(false);
    try { await api("/api/telemetry/demo", { method: "POST", json: { confirm: true } }); toast("ok", "Demo timeline loaded."); setDirty(false); reload(); } catch (e) { toast("err", errMsg(e)); }
  };
  const reschedule = async () => { try { await api("/api/scheduler/run", { method: "POST" }); toast("ok", "Rescheduled."); } catch (e) { toast("err", errMsg(e)); } };

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox message={error} onRetry={reload} />;
  const t = data!;
  const chartSlots = t.slots;

  return (
    <div className="space-y-4">
      <div><h1 className="text-xl font-semibold">Telemetry controller</h1>
        <p className="text-sm text-amber-200/80">{t.disclaimer} Unit: gCO₂e/kWh. “Current” / “Future” labels are relative to the <b>simulation</b> clock; none are measurements.</p></div>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Current configured reading" value={t.current.intensity == null ? "—" : `${t.current.intensity.toFixed(0)} gCO₂e/kWh`} sub={t.current.source === "timeline_slot" ? "from the slot covering simulated now" : t.current.source === "manual_current_entry" ? "manual entry (no slot covers now)" : "none configured"} />
        <Metric accent label="Next cleaner window" value={t.next_cleaner_window ? fmtTime(t.next_cleaner_window.start_time) : "None in timeline"} sub={t.next_cleaner_window ? `${t.next_cleaner_window.intensity.toFixed(0)} gCO₂e/kWh (−${t.next_cleaner_window.reduction_pct}%) — simulated forecast` : "no cleaner future slot is configured"} />
        <Metric label="Telemetry horizon ends" value={fmtTime(t.horizon_end)} sub="jobs needing data beyond this are never given invented readings" />
      </div>
      <div className="card">{chartSlots.length ? <IntensityChart slots={chartSlots} threshold={st.data?.carbon_threshold_g} now={t.sim_time} /> : <Empty>No slots configured.</Empty>}</div>

      <div className="card space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label" htmlFor="cur">Current intensity (manual entry, gCO₂e/kWh)</label><input id="cur" className="input w-56" inputMode="decimal" value={cur} onChange={(e) => { setCur(e.target.value); setDirty(true); }} placeholder="e.g. 700" /></div>
          <button className="btn" onClick={addRow}><Plus className="h-4 w-4" />Add slot</button>
          <button className="btn btn-primary" onClick={save} disabled={!dirty}><Save className="h-4 w-4" />Save timeline</button>
          <button className="btn" onClick={() => { setDirty(false); reload(); }} disabled={!dirty}>Reload saved</button>
          <button className="btn" onClick={reschedule}>Trigger rescheduling</button>
          <button className="btn btn-danger ml-auto" onClick={() => setConfirmReset(true)}><RotateCcw className="h-4 w-4" />Load demo telemetry</button>
        </div>
        {errs.length > 0 && <div role="alert" className="rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-200"><b>Cannot save:</b><ul className="list-disc pl-5">{errs.map((e, i) => <li key={i}>{e}</li>)}</ul></div>}
        {dirty && <p className="text-xs text-amber-300">Unsaved changes.</p>}
        {rows.length === 0 ? <Empty>No time slots. Add one, or load the demo telemetry.</Empty> : (
          <div className="max-h-96 overflow-auto"><table className="w-full"><thead className="sticky top-0 bg-ink-900"><tr><th className="th">Start (local)</th><th className="th">Minutes</th><th className="th">gCO₂e/kWh</th><th className="th">Kind</th><th className="th"><span className="sr-only">Delete</span></th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={r.key} className="border-t border-ink-700">
                <td className="td"><input aria-label={`Slot ${i + 1} start`} type="datetime-local" className="input" value={r.start} onChange={(e) => upd(i, "start", e.target.value)} /></td>
                <td className="td"><input aria-label={`Slot ${i + 1} duration minutes`} className="input w-24" inputMode="numeric" value={r.dur} onChange={(e) => upd(i, "dur", e.target.value)} /></td>
                <td className="td"><input aria-label={`Slot ${i + 1} intensity`} className="input w-28" inputMode="decimal" value={r.val} onChange={(e) => upd(i, "val", e.target.value)} /></td>
                <td className="td text-xs text-slate-400">{r.kind ? `${r.kind} (${r.kind === "historical" ? "recorded configured value" : "simulated"})` : "new (unsaved)"}</td>
                <td className="td"><button className="btn" aria-label={`Delete slot ${i + 1}`} onClick={() => del(i)}><Trash2 className="h-4 w-4" /></button></td></tr>))}</tbody></table></div>)}
      </div>
      {confirmReset && <Confirm danger title="Replace the timeline with the demo scenario?" confirmLabel="Replace timeline" message="All current telemetry slots will be replaced by the predefined demo curve (illustrative values). Jobs are not deleted." onConfirm={resetDemo} onCancel={() => setConfirmReset(false)} />}
    </div>
  );
}
