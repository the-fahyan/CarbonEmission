import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EmissionRow, Slot } from "../types";
import { STATUS_COLOR } from "../utils/format";

const tip = { contentStyle: { background: "#10161d", border: "1px solid #2b3744", borderRadius: 8, fontSize: 12 } };
const hhmm = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export function IntensityChart({ slots, threshold, now }: { slots: Slot[]; threshold?: number; now?: string }) {
  const data = slots.map((s) => ({ t: hhmm(s.start_time), v: s.intensity_g_per_kwh, kind: s.kind }));
  const nowLabel = now ? hhmm(now) : undefined;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ left: 0, right: 12, top: 8 }}>
        <CartesianGrid stroke="#1f2933" strokeDasharray="3 3" />
        <XAxis dataKey="t" stroke="#64748b" fontSize={11} interval="preserveStartEnd" />
        <YAxis stroke="#64748b" fontSize={11} unit="" label={{ value: "gCO₂e/kWh", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }} />
        <Tooltip {...tip} formatter={(v: number) => [`${v} gCO₂e/kWh (configured)`, "Intensity"]} />
        {threshold != null && <ReferenceLine y={threshold} stroke="#fbbf24" strokeDasharray="4 4" label={{ value: "threshold", fill: "#fbbf24", fontSize: 10 }} />}
        {nowLabel && <ReferenceLine x={nowLabel} stroke="#38bdf8" label={{ value: "sim now", fill: "#38bdf8", fontSize: 10 }} />}
        <Line type="stepAfter" dataKey="v" stroke="#4ade80" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function EmissionsChart({ rows }: { rows: EmissionRow[] }) {
  const data = rows.filter((r) => r.baseline_g != null && (r.planned_g != null || r.actual_g != null))
    .map((r) => ({ name: r.name.length > 14 ? r.name.slice(0, 13) + "…" : r.name, Baseline: Math.round(r.baseline_g ?? 0), "Carbon-aware": Math.round((r.actual_g ?? r.planned_g) ?? 0) }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ left: 0, right: 8, top: 8 }}>
        <CartesianGrid stroke="#1f2933" strokeDasharray="3 3" />
        <XAxis dataKey="name" stroke="#64748b" fontSize={10} interval={0} angle={-25} textAnchor="end" height={60} />
        <YAxis stroke="#64748b" fontSize={11} label={{ value: "gCO₂e (estimated)", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }} />
        <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Baseline" fill="#f87171" radius={[3, 3, 0, 0]} /><Bar dataKey="Carbon-aware" fill="#4ade80" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StatusPie({ counts }: { counts: Record<string, number> }) {
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>{data.map((d) => <Cell key={d.name} fill={STATUS_COLOR[d.name] ?? "#64748b"} stroke="none" />)}</Pie>
        <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
