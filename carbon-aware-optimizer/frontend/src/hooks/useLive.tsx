import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { apiUrl } from "../api/client";
import type { LogRow } from "../types";

interface Live { version: number; connected: boolean; logs: LogRow[]; progress: Record<number, number> }
const Ctx = createContext<Live>({ version: 0, connected: false, logs: [], progress: {} });
export const useLive = () => useContext(Ctx);

const EVENTS = ["job_update", "scheduler_run", "telemetry", "settings", "error", "log", "progress"];

/** One EventSource for the whole app (SSE). EventSource auto-reconnects and sends Last-Event-ID itself. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [connected, setConnected] = useState(false);
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [progress, setProgress] = useState<Record<number, number>>({});
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource(apiUrl("/api/events"));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    const bump = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setVersion((v) => v + 1), 250); };
    for (const t of EVENTS) {
      es.addEventListener(t, (ev) => {
        const evt = JSON.parse((ev as MessageEvent).data);
        if (t === "log") {
          const d = evt.data;
          setLogs((l) => (l.some((x) => x.id === d.id) ? l : [...l, { ...d, wall_time: evt.ts }].slice(-300)));
        } else if (t === "progress") {
          setProgress((p) => ({ ...p, [evt.data.job_id]: evt.data.progress }));
        }
        if (t !== "progress") bump();
      });
    }
    return () => { es.close(); window.clearTimeout(timer.current); };
  }, []);

  return <Ctx.Provider value={{ version, connected, logs, progress }}>{children}</Ctx.Provider>;
}
