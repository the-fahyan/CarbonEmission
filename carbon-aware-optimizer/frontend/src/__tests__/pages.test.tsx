import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import Jobs from "../pages/Jobs";
import TelemetryPage from "../pages/TelemetryPage";
import { ToastProvider } from "../components/ui";

type Handler = (url: string, init?: RequestInit) => { status?: number; body: unknown } | Promise<never>;
function mockFetch(handler: Handler) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const r = await handler(url, init);
    return { ok: (r.status ?? 200) < 400, status: r.status ?? 200, headers: new Headers({ "content-type": "application/json" }), json: async () => r.body, text: async () => JSON.stringify(r.body) };
  }));
  return calls;
}
const wrap = (ui: React.ReactElement) => render(<ToastProvider>{ui}</ToastProvider>);
afterEach(() => vi.unstubAllGlobals());

const job = { id: 1, name: "Train", description: "", workload_type: "ml_training", duration_minutes: 30, estimated_energy_kwh: 2, priority: "normal", deferrable: true, is_demo: false,
  submitted_at: "2026-10-14T10:00:00Z", earliest_start: null, deadline: null, status: "SCHEDULED", status_reason: "", progress: 0, scheduled_start: "2026-10-14T11:00:00Z", scheduled_end: null,
  scheduled_intensity: 120, baseline_start: null, baseline_emissions_g: 1000, scheduled_emissions_g: 240, savings_g: 760, savings_pct: 76, added_wait_minutes: 60, scheduling_explanation: "", actual_start: null, actual_end: null, actual_emissions_g: null };

describe("Jobs page", () => {
  it("shows a loading state, then the empty state", async () => {
    mockFetch(() => ({ body: { items: [], total: 0, limit: 200, offset: 0 } }));
    wrap(<Jobs />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText(/No jobs match/i)).toBeInTheDocument();
  });

  it("renders jobs from the API", async () => {
    mockFetch(() => ({ body: { items: [job], total: 1, limit: 200, offset: 0 } }));
    wrap(<Jobs />);
    expect(await screen.findByText("Train")).toBeInTheDocument();
    expect(screen.getAllByText("SCHEDULED").some((el) => el.tagName === "SPAN")).toBe(true); // the badge (not the filter <option>)
  });

  it("handles an unreachable backend without crashing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    wrap(<Jobs />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the backend/i);
  });

  it("blocks submission and shows validation errors for an invalid form", async () => {
    const calls = mockFetch(() => ({ body: { items: [], total: 0, limit: 200, offset: 0 } }));
    wrap(<Jobs />);
    await screen.findByText(/No jobs match/i);
    await userEvent.click(screen.getByRole("button", { name: /submit job/i }));
    expect(await screen.findByText(/Name is required/i)).toBeInTheDocument();
    expect(calls.some((c) => c.init?.method === "POST")).toBe(false);
  });

  it("submits a valid job to the backend", async () => {
    const calls = mockFetch((url, init) => init?.method === "POST"
      ? { status: 201, body: { id: 5, status: "SCHEDULED", scheduled_start: "2026-10-14T11:00:00Z" } }
      : { body: { items: [], total: 0, limit: 200, offset: 0 } });
    wrap(<Jobs />);
    await screen.findByText(/No jobs match/i);
    await userEvent.type(screen.getByLabelText(/job name/i), "My job");
    await userEvent.click(screen.getByRole("button", { name: /submit job/i }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST")!;
    expect(post.url).toBe("/api/jobs");
    expect(JSON.parse(post.init!.body as string)).toMatchObject({ name: "My job", duration_minutes: 30, estimated_energy_kwh: 1.5, priority: "normal" });
  });
});

const tele = { mode: "manual_simulated", disclaimer: "All values are manually configured simulated readings, not measurements.", sim_time: "2026-10-14T10:00:00Z",
  slots: [{ id: 1, start_time: "2026-10-14T10:00:00Z", end_time: "2026-10-14T10:15:00Z", duration_minutes: 15, intensity_g_per_kwh: 700, kind: "current", source: "manual_simulated" }],
  current: { intensity: 700, source: "timeline_slot", slot_id: 1 }, manual_current_intensity_g: null, next_cleaner_window: null, horizon_end: "2026-10-14T10:15:00Z" };
const settings = { capacity: 2, carbon_threshold_g: 450, default_slot_minutes: 15 };

describe("Telemetry page", () => {
  const h: Handler = (url, init) => (url === "/api/telemetry" && init?.method === "PUT" ? { status: 422, body: { error: "telemetry_validation", message: "Invalid telemetry.", details: ["Slots overlap: 10:00 (+15 min) runs past the next slot starting 10:05."] } } : url.startsWith("/api/settings") ? { body: settings } : { body: tele });

  it("labels data as simulated and edits a slot", async () => {
    mockFetch(h);
    wrap(<TelemetryPage />);
    expect(await screen.findByText(/not measurements/i)).toBeInTheDocument();
    const input = screen.getByLabelText("Slot 1 intensity");
    await userEvent.clear(input);
    await userEvent.type(input, "250");
    expect(input).toHaveValue("250");
    expect(screen.getByText(/Unsaved changes/i)).toBeInTheDocument();
  });

  it("rejects a negative intensity locally without calling the API", async () => {
    const calls = mockFetch(h);
    wrap(<TelemetryPage />);
    const input = await screen.findByLabelText("Slot 1 intensity");
    await userEvent.clear(input);
    await userEvent.type(input, "-5");
    await userEvent.click(screen.getByRole("button", { name: /save timeline/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/intensity must be a number ≥ 0/i);
    expect(calls.some((c) => c.init?.method === "PUT")).toBe(false);
  });

  it("shows backend validation details (overlap) when saving fails", async () => {
    mockFetch(h);
    wrap(<TelemetryPage />);
    const input = await screen.findByLabelText("Slot 1 intensity");
    await userEvent.clear(input);
    await userEvent.type(input, "300");
    await userEvent.click(screen.getByRole("button", { name: /save timeline/i }));
    expect(await screen.findByText(/Slots overlap/i)).toBeInTheDocument();
  });

  it("asks for confirmation before loading the demo timeline", async () => {
    const calls = mockFetch(h);
    wrap(<TelemetryPage />);
    await screen.findByLabelText("Slot 1 intensity");
    await userEvent.click(screen.getByRole("button", { name: /load demo telemetry/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/telemetry/demo")).toBe(false);
  });
});
