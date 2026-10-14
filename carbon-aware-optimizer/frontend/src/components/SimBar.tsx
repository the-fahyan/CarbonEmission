import { FastForward, Pause, Play, Radio } from "lucide-react";
import { api, errMsg } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { useLive } from "../hooks/useLive";
import type { WorkerStatus } from "../types";
import { fmtClock } from "../utils/format";
import { useToast } from "./ui";

/** Always-visible control strip: clearly labels SIMULATED time vs real wall-clock time. */
export default function SimBar() {
  const { connected } = useLive();
  const { data, reload } = useFetch<WorkerStatus>("/api/worker/status");
  const toast = useToast();
  const act = async (path: string, json?: unknown, okMsg?: string) => {
    try { await api(path, { method: "POST", json }); if (okMsg) toast("ok", okMsg); reload(); } catch (e) { toast("err", errMsg(e)); }
  };
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-ink-600 bg-ink-900 px-4 py-2 text-xs">
      <span className="flex items-center gap-1 rounded-full border border-amber-700 bg-amber-950/50 px-2 py-0.5 font-semibold text-amber-200" title="No live grid API is used">
        <Radio className="h-3 w-3" /> Manual / simulated telemetry
      </span>
      <span className={connected ? "text-leaf-400" : "text-red-300"}>● live updates {connected ? "connected" : "reconnecting…"}</span>
      {data && (
        <>
          <span>Simulation time: <b className="font-mono">{fmtClock(data.sim_time)}</b></span>
          <span className="text-slate-500">Wall-clock: <span className="font-mono">{fmtClock(data.wall_time)}</span></span>
          <span className="text-slate-500">Speed ×{data.simulation_speed} (1 real s = {(data.simulation_speed / 60).toFixed(2)} sim min)</span>
          <span className="ml-auto flex items-center gap-1">
            <button className="btn" onClick={() => act(data.paused ? "/api/worker/resume" : "/api/worker/pause")} aria-label={data.paused ? "Resume worker" : "Pause worker"}>
              {data.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}{data.paused ? "Resume worker" : "Pause worker"}
            </button>
            {[15, 60, 180].map((m) => (
              <button key={m} className="btn" onClick={() => act("/api/worker/advance", { minutes: m }, `Advanced ${m} simulated minutes`)}>
                <FastForward className="h-3 w-3" />+{m >= 60 ? `${m / 60}h` : `${m}m`}
              </button>
            ))}
          </span>
        </>
      )}
    </div>
  );
}
