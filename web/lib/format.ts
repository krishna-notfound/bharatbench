import type { Run, RunStatus, Severity } from "@/lib/types";

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour12: false });
}

export function runTitle(run: Pick<Run, "apk_name" | "app">): string {
  return run.app?.app_name || run.app?.package_name || run.apk_name;
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  analyzing: "Analyzing",
  provisioning: "Provisioning",
  running: "Running",
  scoring: "Scoring",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export const SOURCE_LABEL = {
  static: "Static scan",
  runtime: "Observed on emulator",
} as const;

export function titleCase(s: string): string {
  return s.replace(/[_-]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
