import { AlertTriangle, Info } from "lucide-react";
import { SEVERITY_BAR } from "@/components/findings/severity-badge";
import { SEVERITY_LABEL, SEVERITY_ORDER } from "@/lib/format";
import type { Run } from "@/lib/types";
import { cn } from "@/lib/utils";

function scoreTone(score: number): string {
  if (score >= 80) return "text-success";
  if (score >= 50) return "text-sev-medium";
  return "text-sev-critical";
}

export function ScorePanel({ run }: { run: Run }) {
  const s = run.summary;
  return (
    <div className="flex h-full flex-col gap-4 rounded-xl border border-border bg-card p-4">
      <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
        Reliability score
      </h2>
      {s ? (
        <>
          <div className="flex items-baseline gap-2">
            <span
              className={cn(
                "font-mono text-5xl font-semibold tabular-nums",
                scoreTone(s.reliability_score),
              )}
            >
              {Math.round(s.reliability_score)}
            </span>
            <span className="font-mono text-sm text-muted-foreground">/ 100</span>
          </div>
          <p className="text-xs text-muted-foreground">
            100 minus the summed impact of {s.total_findings}{" "}
            {s.total_findings === 1 ? "finding" : "findings"}.
          </p>
          <ul className="grid grid-cols-2 gap-2">
            {SEVERITY_ORDER.map((sev) => (
              <li
                key={sev}
                className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2"
              >
                <span className={cn("size-2 rounded-full", SEVERITY_BAR[sev])} />
                <span className="flex-1 text-xs text-muted-foreground">
                  {SEVERITY_LABEL[sev]}
                </span>
                <span className="font-mono text-sm font-medium tabular-nums">
                  {s.counts[sev]}
                </span>
              </li>
            ))}
          </ul>
          {!s.runtime_executed && (
            <div
              role="note"
              className="flex gap-2 rounded-lg border border-sev-medium/40 bg-sev-medium/10 p-3 text-xs"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-sev-medium" />
              <div>
                <p className="font-medium text-sev-medium">
                  Runtime testing was skipped. Static scan only.
                </p>
                <p className="mt-0.5 text-muted-foreground">
                  {s.runtime_skipped_reason ?? "No reason was reported."}
                </p>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="flex flex-1 flex-col items-start justify-center gap-2 text-sm text-muted-foreground">
          <Info className="size-5" />
          {run.status === "failed" || run.status === "cancelled"
            ? "No score: this run did not finish."
            : "Score appears when scoring completes."}
        </div>
      )}
    </div>
  );
}
