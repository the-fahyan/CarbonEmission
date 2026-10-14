import type { Job } from "../types";

export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
export const fmtClock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
export const fmtG = (g: number | null | undefined) => (g == null ? "—" : g >= 1000 ? `${(g / 1000).toFixed(2)} kg` : `${g.toFixed(0)} g`);
export const fmtPct = (p: number | null | undefined) => (p == null ? "—" : `${p.toFixed(1)}%`);

/** ISO (UTC) -> value for <input type="datetime-local"> in the user's local timezone. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
/** datetime-local value (local time) -> ISO UTC string. */
export const fromLocalInput = (v: string): string | null => (v ? new Date(v).toISOString() : null);

export interface JobFormValues { name: string; duration_minutes: string; estimated_energy_kwh: string; earliest_start: string; deadline: string }
/** Client-side validation mirrors the backend rules; the backend remains the authority. */
export function validateJobForm(v: JobFormValues): Record<string, string> {
  const e: Record<string, string> = {};
  if (!v.name.trim()) e.name = "Name is required.";
  const d = Number(v.duration_minutes);
  if (!v.duration_minutes || !Number.isFinite(d) || d <= 0 || !Number.isInteger(d)) e.duration_minutes = "Runtime must be a whole number of minutes > 0.";
  const k = Number(v.estimated_energy_kwh);
  if (v.estimated_energy_kwh === "" || !Number.isFinite(k) || k < 0) e.estimated_energy_kwh = "Energy must be a number ≥ 0.";
  if (v.deadline && v.earliest_start && new Date(v.deadline) <= new Date(v.earliest_start)) e.deadline = "Deadline must be after the earliest start.";
  return e;
}

export const STATUS_STYLE: Record<Job["status"], string> = {
  PENDING: "bg-slate-700 text-slate-200", SCHEDULED: "bg-sky-900/60 text-sky-200", WAITING: "bg-amber-900/60 text-amber-200",
  RUNNING: "bg-leaf-600/30 text-leaf-400", COMPLETED: "bg-emerald-900/60 text-emerald-200", CANCELLED: "bg-slate-800 text-slate-400",
  FAILED: "bg-red-900/60 text-red-200", UNSCHEDULABLE: "bg-orange-900/60 text-orange-200",
};
export const STATUS_COLOR: Record<string, string> = {
  PENDING: "#94a3b8", SCHEDULED: "#38bdf8", WAITING: "#fbbf24", RUNNING: "#4ade80", COMPLETED: "#10b981", CANCELLED: "#64748b", FAILED: "#f87171", UNSCHEDULABLE: "#fb923c",
};
