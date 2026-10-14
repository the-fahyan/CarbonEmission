import { useCallback, useEffect, useRef, useState } from "react";
import { api, errMsg } from "../api/client";
import { useLive } from "./useLive";

/** Fetch a GET endpoint; refetches whenever a live event arrives. Exposes loading/error/reload. */
export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const { version } = useLive();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    try {
      const d = await api<T>(path);
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError(errMsg(e));
    } finally {
      if (my === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => { void load(); }, [load, version]);
  return { data, error, loading, reload: load };
}
