import { AlertTriangle } from "lucide-react";
import type { Run } from "@/lib/types";
import { cn } from "@/lib/utils";

function scoreTone(score: number): { text: string; stroke: string } {
  if (score >= 80) return { text: "text-success", stroke: "stroke-success" };
  if (score >= 50) return { text: "text-sev-medium", stroke: "stroke-sev-medium" };
  return { text: "text-sev-critical", stroke: "stroke-sev-critical" };
}

const R = 44;
const C = 2 * Math.PI * R;

/** Reliability score ring. Renders only when the API has produced a summary. */
export function ScorePanel({ run }: { run: Run }) {
  const s = run.summary;
  if (!s) return null;
  const score = Math.max(0, Math.min(100, Math.round(s.reliability_score)));
  const tone = scoreTone(score);
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:gap-6">
      <div className="relative size-28 shrink-0" role="img" aria-label={`Reliability score ${score} out of 100`}>
        <svg viewBox="0 0 100 100" className="size-full -rotate-90">
          <circle cx="50" cy="50" r={R} fill="none" strokeWidth="8" className="stroke-muted" />
          <circle
            cx="50"
            cy="50"
            r={R}
            fill="none"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - score / 100)}
            className={cn("transition-all duration-700", tone.stroke)}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-mono text-3xl font-semibold tabular-nums", tone.text)}>{score}</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground">of 100</span>
        </div>
      </div>
      <div className="min-w-0 space-y-1 text-center sm:text-left">
        <p className="text-sm font-medium">Reliability score</p>
        <p className="text-xs text-muted-foreground">
          Based on {s.total_findings} {s.total_findings === 1 ? "issue" : "issues"} and how many users each could
          affect. Weights are adjustable assumptions, not measured telemetry.
        </p>
        {!s.runtime_executed && (
          <p
            role="note"
            className="mt-2 flex items-start gap-1.5 rounded-2xl bg-sev-medium/10 px-3 py-2 text-left text-xs text-foreground"
          >
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-sev-medium" />
            <span>
              I skipped the emulator test, so this is an APK scan only.
              {s.runtime_skipped_reason ? ` ${s.runtime_skipped_reason}` : ""}
            </span>
          </p>
        )}
      </div>
    </div>
  );
}
