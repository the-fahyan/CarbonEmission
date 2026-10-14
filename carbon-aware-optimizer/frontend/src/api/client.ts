// Small typed API client. All scheduling decisions happen in the backend; the UI only calls these.
const configuredBase: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
const BASE = configuredBase
  ? `${/^https?:\/\//i.test(configuredBase) ? "" : "https://"}${configuredBase}`.replace(/\/+$/, "")
  : "";

export class ApiError extends Error {
  constructor(message: string, public status: number, public details: string[] = []) { super(message); }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...rest,
      headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers ?? {}) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError("Cannot reach the backend. Is it running on port 8000?", 0);
  }
  if (!res.ok) {
    let body: { message?: string; details?: string[]; detail?: unknown } = {};
    try { body = await res.json(); } catch { /* non-JSON error */ }
    throw new ApiError(body.message ?? (typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`), res.status, body.details ?? []);
  }
  return (res.headers.get("content-type")?.includes("json") ? res.json() : (res.text() as unknown)) as Promise<T>;
}

export const apiUrl = (p: string) => BASE + p;
export const errMsg = (e: unknown) => (e instanceof ApiError ? [e.message, ...e.details].join(" — ") : e instanceof Error ? e.message : String(e));
