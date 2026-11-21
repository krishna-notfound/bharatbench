// Frozen mirror of api/app/models.py. Do not edit without orchestrator approval.

export type Severity = "critical" | "high" | "medium" | "low";
export type Category = "security" | "performance" | "reliability" | "network" | "storage" | "memory";
export type FindingSource = "static" | "runtime";
export type EvidenceKind = "logcat" | "screenshot" | "ui_dump" | "manifest" | "code" | "metric" | "note";
export type Fidelity = "controlled" | "approximated" | "unsupported";
export type RunStatus =
  | "queued" | "analyzing" | "provisioning" | "running" | "scoring" | "done" | "failed" | "cancelled";
export type EventType = "status" | "log" | "step" | "finding" | "artifact" | "done" | "error";
export type ProfileId =
  | "baseline" | "budget_2gb" | "flaky_network" | "low_storage" | "battery_saver" | "process_death";

export const TERMINAL_STATUSES: RunStatus[] = ["done", "failed", "cancelled"];

export interface Profile {
  id: ProfileId;
  name: string;
  description: string;
  fidelity: Fidelity;
  how: string;
  users_exposed: number;
}

export interface Evidence {
  kind: EvidenceKind;
  ref: string | null;
  excerpt: string | null;
}

export interface Impact {
  users_exposed: number;
  severity_weight: number;
  flow_usage: number;
  score: number;
}

export interface Finding {
  id: string;
  run_id: string;
  source: FindingSource;
  category: Category;
  rule_id: string;
  title: string;
  severity: Severity;
  description: string;
  evidence: Evidence[];
  repro_steps: string[];
  repro_flow: string | null;
  affected_journey: string | null;
  journey_step: number | null;
  profile_id: ProfileId | null;
  probable_cause: string | null;
  suggested_fix: string | null;
  impact: Impact | null;
}

export interface AppInfo {
  package_name: string;
  app_name: string | null;
  version_name: string | null;
  version_code: string | null;
  min_sdk: number | null;
  target_sdk: number | null;
  size_bytes: number;
  permissions: string[];
  main_activity: string | null;
  native_abis: string[];
  dex_count: number;
}

export interface RunSummary {
  counts: Record<Severity, number>;
  total_findings: number;
  reliability_score: number;
  runtime_executed: boolean;
  runtime_skipped_reason: string | null;
}

export interface Run {
  id: string;
  apk_name: string;
  status: RunStatus;
  profile_ids: ProfileId[];
  created_at: string;
  updated_at: string;
  error: string | null;
  app: AppInfo | null;
  summary: RunSummary | null;
}

export interface RunEvent {
  run_id: string;
  seq: number;
  ts: string;
  type: EventType;
  message: string;
  data: Record<string, unknown> | null;
}

export interface Health {
  ok: boolean;
  harness: { configured: boolean; reachable: boolean; detail: string };
  sarvam_configured: boolean;
}

// Voice WS messages (contracts/README.md §5)
export type VoiceServerMessage =
  | { type: "ready" }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "assistant_text"; text: string; turn_id: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown>; turn_id: string }
  | { type: "tool_result"; name: string; ok: boolean; summary: string }
  | { type: "audio"; turn_id: string; format: "wav" | "mp3"; sample_rate: number; data: string }
  | { type: "turn_end"; turn_id: string }
  | { type: "run_update"; run_id: string; status: string; message: string }
  | { type: "error"; message: string };

export type VoiceClientMessage =
  | { type: "start"; language: "auto" | "hi-IN" | "en-IN"; run_id: string | null }
  | { type: "speech_end" }
  | { type: "interrupt" }
  | { type: "text"; text: string };
