import { CheckCircle2, ChevronRight, Presentation, X } from "lucide-react";
import { useState } from "react";
import { api, errMsg } from "../api/client";
import { Confirm, useToast } from "./ui";

export type Page = "overview" | "jobs" | "telemetry" | "scheduling" | "logs";
interface Step { title: string; text: string; page?: Page; action?: { label: string; run: () => Promise<void> } }

/** Guided "Run Demo" panel for presenters. Every action calls the real backend. */
export default function DemoWizard({ onNavigate, onClose }: { onNavigate: (p: Page) => void; onClose: () => void }) {
  const [i, setI] = useState(0);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const post = (path: string, json?: unknown) => api(path, { method: "POST", json });

  const steps: Step[] = [
    { title: "1. Load the scenario", text: "Replaces the telemetry timeline and any previous demo jobs (your own jobs stay). Capacity=2, threshold=450.", action: { label: "Load Demo Scenario…", run: async () => setConfirm(true) } },
    { title: "2. Inspect the grid timeline", text: "High intensity now, cleanest window a few hours ahead. Values are configured/simulated.", page: "telemetry" },
    { title: "3. View submitted jobs", text: "Nine jobs are PENDING: a non-deferrable one, a tight deadline, a critical one, an impossible deadline and a job that fails once.", page: "jobs" },
    { title: "4. Run the optimization", text: "Solves the SciPy MILP and records an explanation for each job.", page: "scheduling", action: { label: "Run optimization", run: async () => { await post("/api/scheduler/run"); toast("ok", "Optimization complete."); } } },
    { title: "5. Examine the schedule", text: "Compare current vs proposed starts, baseline vs optimized emissions, and unschedulable diagnostics.", page: "scheduling" },
    { title: "6. Advance the simulated worker", text: "Jumps simulated time +30 min; due jobs start and run at the configured speed.", page: "logs", action: { label: "Advance +30 min", run: async () => { await post("/api/worker/advance", { minutes: 30 }); toast("ok", "Advanced 30 simulated minutes."); } } },
    { title: "7. Observe live logs", text: "Logs stream in over SSE with no refresh. Use +1h to finish more jobs; the flaky job fails — retry it from its details.", page: "logs" },
    { title: "8. Compare baseline vs optimized", text: "Overview charts use live data; savings are estimates over comparable jobs only.", page: "overview" },
    { title: "9. Inspect decision explanations", text: "Open any job → ‘Decision history’ to see why each slot was chosen or rejected.", page: "jobs" },
  ];
  const s = steps[i];
  const go = async () => {
    setBusy(true);
    try { if (s.action) await s.action.run(); } catch (e) { toast("err", errMsg(e)); setBusy(false); return; }
    setBusy(false);
    if (s.page) onNavigate(s.page);
  };
  const load = async () => {
    setConfirm(false); setBusy(true);
    try { await post("/api/demo/load", { confirm: true }); toast("ok", "Demo scenario loaded."); onNavigate("telemetry"); setI(1); } catch (e) { toast("err", errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <aside aria-label="Demo guide" className="fixed bottom-4 left-4 z-40 w-80 rounded-xl border border-leaf-600 bg-ink-900 p-4 shadow-xl">
      <div className="mb-2 flex items-center justify-between"><span className="flex items-center gap-2 text-sm font-semibold text-leaf-400"><Presentation className="h-4 w-4" />Run Demo</span><button className="btn" aria-label="Close demo guide" onClick={onClose}><X className="h-4 w-4" /></button></div>
      <h3 className="font-semibold">{s.title}</h3><p className="mb-3 mt-1 text-sm text-slate-300">{s.text}</p>
      <div className="flex items-center justify-between">
        <button className="btn" disabled={i === 0} onClick={() => setI(i - 1)}>Back</button>
        <div className="flex gap-2">
          {s.action && <button className="btn btn-primary" disabled={busy} onClick={go}>{s.action.label}</button>}
          {!s.action && s.page && <button className="btn" onClick={() => onNavigate(s.page!)}>Show me</button>}
          {i < steps.length - 1 ? <button className="btn" onClick={() => { setI(i + 1); const n = steps[i + 1]; if (n.page && !n.action) onNavigate(n.page); }}>Next<ChevronRight className="h-4 w-4" /></button> : <span className="flex items-center gap-1 text-leaf-400"><CheckCircle2 className="h-4 w-4" />Done</span>}
        </div>
      </div>
      {confirm && <Confirm danger title="Load the demo scenario?" confirmLabel="Load demo" message="This replaces the telemetry timeline, sets capacity/threshold/speed for the demo, and removes previously loaded DEMO jobs. Jobs you created yourself are not touched." onConfirm={load} onCancel={() => setConfirm(false)} />}
    </aside>
  );
}
