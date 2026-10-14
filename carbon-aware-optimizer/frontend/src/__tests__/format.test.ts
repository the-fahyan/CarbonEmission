import { fromLocalInput, toLocalInput, validateJobForm } from "../utils/format";

const ok = { name: "A", duration_minutes: "30", estimated_energy_kwh: "1.5", earliest_start: "", deadline: "" };

describe("validateJobForm", () => {
  it("accepts a valid form", () => expect(validateJobForm(ok)).toEqual({}));
  it("requires a name", () => expect(validateJobForm({ ...ok, name: "  " }).name).toBeTruthy());
  it("rejects non-positive / fractional runtime", () => {
    expect(validateJobForm({ ...ok, duration_minutes: "0" }).duration_minutes).toBeTruthy();
    expect(validateJobForm({ ...ok, duration_minutes: "2.5" }).duration_minutes).toBeTruthy();
    expect(validateJobForm({ ...ok, duration_minutes: "abc" }).duration_minutes).toBeTruthy();
  });
  it("rejects negative energy but allows zero", () => {
    expect(validateJobForm({ ...ok, estimated_energy_kwh: "-1" }).estimated_energy_kwh).toBeTruthy();
    expect(validateJobForm({ ...ok, estimated_energy_kwh: "0" })).toEqual({});
  });
  it("rejects deadline before earliest start", () => {
    expect(validateJobForm({ ...ok, earliest_start: "2026-10-14T12:00", deadline: "2026-10-14T11:00" }).deadline).toBeTruthy();
  });
});

describe("datetime helpers", () => {
  it("round-trips local input <-> ISO UTC", () => {
    const iso = "2026-10-14T10:30:00.000Z";
    expect(fromLocalInput(toLocalInput(iso))).toBe(iso);
    expect(fromLocalInput("")).toBeNull();
  });
});
