import { STATUS_LABEL, runTitle } from "@/lib/format";
import { TERMINAL_STATUSES, type Run } from "@/lib/types";

/** Plain-language one-liner for a session row. Derived only from real run data. */
export function sessionLine(run: Run): string {
  if (run.status === "failed") return "Something went wrong during this test";
  if (run.status === "cancelled") return "Cancelled before it finished";
  if (!TERMINAL_STATUSES.includes(run.status)) {
    return `${STATUS_LABEL[run.status]}…`;
  }
  const s = run.summary;
  if (!s) return "Finished";
  if (s.total_findings === 0) return "No issues found";
  const crit = s.counts.critical;
  const issues = `${s.total_findings} ${s.total_findings === 1 ? "issue" : "issues"}`;
  return crit > 0 ? `${issues}, ${crit} critical` : issues;
}

export { runTitle };
