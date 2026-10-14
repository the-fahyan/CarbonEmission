export type Priority = "low" | "normal" | "high" | "critical";
export type Status = "PENDING" | "SCHEDULED" | "WAITING" | "RUNNING" | "COMPLETED" | "CANCELLED" | "FAILED" | "UNSCHEDULABLE";

export interface Attempt { id: number; attempt_number: number; state: string; sim_started_at: string; sim_finished_at: string | null; wall_started_at: string; wall_finished_at: string | null; progress: number; emissions_g: number | null; note: string }
export interface Job {
  id: number; name: string; description: string; workload_type: string; duration_minutes: number; estimated_energy_kwh: number;
  priority: Priority; deferrable: boolean; is_demo: boolean; submitted_at: string; earliest_start: string | null; deadline: string | null;
  status: Status; status_reason: string; progress: number; scheduled_start: string | null; scheduled_end: string | null;
  scheduled_intensity: number | null; baseline_start: string | null; baseline_emissions_g: number | null; scheduled_emissions_g: number | null;
  savings_g: number | null; savings_pct: number | null; added_wait_minutes: number | null; scheduling_explanation: string;
  actual_start: string | null; actual_end: string | null; actual_emissions_g: number | null;
  attempts?: Attempt[]; simulate_failure?: boolean;
}
export interface JobList { items: Job[]; total: number; limit: number; offset: number }
export interface Decision { id: number; job_id: number; run_id: number | null; sim_time: string; previous_status: string; new_status: string; selected_start: string | null; intensity_used: number | null; emissions_g: number | null; explanation: string }
export interface LogRow { id: number; job_id: number | null; level: string; message: string; sim_time: string; wall_time: string }
export interface Slot { id: number; start_time: string; end_time: string; duration_minutes: number; intensity_g_per_kwh: number; kind: "historical" | "current" | "future"; source: string }
export interface Telemetry {
  mode: string; disclaimer: string; sim_time: string; slots: Slot[];
  current: { intensity: number | null; source: string; slot_id: number | null };
  manual_current_intensity_g: number | null;
  next_cleaner_window: { slot_id: number; start_time: string; intensity: number; reduction_pct: number | null } | null;
  horizon_end: string | null;
}
export interface Settings {
  capacity: number; carbon_threshold_g: number; weight_carbon: number; weight_wait: number; weight_priority: number;
  nondeferrable_wait_weight: number; critical_ignores_threshold: boolean; policy: string; simulation_speed: number;
  default_slot_minutes: number; auto_schedule: boolean; current_intensity_g: number | null;
}
export interface Run { id: number; trigger: string; sim_time: string; solver_status: string; is_optimal: boolean; method: string; objective_value: number | null; jobs_considered: number; jobs_scheduled: number; jobs_waiting: number; jobs_unschedulable: number; jobs_changed: number; variables: number; solve_ms: number; summary: string; committed: boolean }
export interface PreviewItem { job_id: number; name: string; current_status: string; proposed_status: string; current_start: string | null; proposed_start: string | null; baseline_start: string | null; baseline_emissions_g: number | null; proposed_emissions_g: number | null; savings_g: number | null; savings_pct: number | null; explanation: string }
export interface Preview { ok: boolean; solver_status: string; is_optimal: boolean; objective_value: number | null; variables: number; solve_ms: number; message: string; items: PreviewItem[] }
export interface SchedStatus { last_run: Run | null; capacity: number; running_jobs: number; available_capacity: number; queued_jobs: number; settings: Settings; diagnostics: { job_id: number; name: string; status: string; explanation: string }[] }
export interface Summary { counts: Record<string, number>; awaiting: number; running: number; completed: number; unschedulable: number; baseline_g: number; optimized_g: number; savings_g: number | null; savings_pct: number | null; comparable_jobs: number; current_intensity: { intensity: number | null; source: string }; telemetry_mode: string; sim_time: string }
export interface EmissionRow { job_id: number; name: string; status: string; baseline_g: number | null; planned_g: number | null; actual_g: number | null; savings_g: number | null; savings_pct: number | null }
export interface SavingsReport { scope: string; planned: Agg; completed: Agg; excluded: { job_id: number; name: string; reason: string }[]; note: string }
export interface Agg { jobs: number; baseline_g: number; optimized_g: number; savings_g: number | null; savings_pct: number | null }
export interface WorkerStatus { running: boolean; paused: boolean; sim_time: string; wall_time: string; simulation_speed: number; capacity: number; label: string }
