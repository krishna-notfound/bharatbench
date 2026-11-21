"use client";

import { useEffect, useRef } from "react";
import { Check, ChevronDown, Minus } from "lucide-react";
import { clockTime } from "@/lib/format";
import type { RunEvent, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEPS: { status: RunStatus; label: string; runtime: boolean }[] = [
  { status: "analyzing", label: "Inspect app", runtime: false },
  { status: "provisioning", label: "Start emulator", runtime: true },
  { status: "running", label: "Run tests", runtime: true },
  { status: "scoring", label: "Analyse", runtime: false },
  { status: "done", label: "Done", runtime: false },
];

/** Compact progress steps. Runtime steps show as skipped when the run never executed on the emulator. */
export function CompactSteps({
  status,
  runtimeSkipped = false,
}: {
  status: RunStatus;
  runtimeSkipped?: boolean;
}) {
  const idx = STEPS.findIndex((s) => s.status === status);
  const finished = status === "done";
  return (
    <ol className="flex flex-wrap items-center justify-center gap-x-2 gap-y-2" aria-label="Run progress">
      {STEPS.map((s, i) => {
        const skipped = runtimeSkipped && s.runtime && (finished || idx > i || idx === -1);
        const complete = !skipped && (finished || (idx >= 0 && i < idx));
        const current = !finished && i === idx;
        return (
          <li key={s.status} className="flex items-center gap-2">
            <span
              aria-current={current ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
                complete && "border-success/30 bg-success/10 text-success",
                current && "border-primary/30 bg-primary/10 text-primary",
                skipped && "border-dashed border-border bg-transparent text-muted-foreground",
                !complete && !current && !skipped && "border-border bg-muted text-muted-foreground",
              )}
            >
              {complete && <Check className="size-3" />}
              {skipped && <Minus className="size-3" />}
              {current && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
              {s.label}
              {skipped && <span className="font-normal"> · skipped</span>}
            </span>
            {i < STEPS.length - 1 && <span className="hidden h-px w-3 bg-border sm:block" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}

/** Full event log, collapsed by default under "Activity log". */
export function ActivityLog({
  events,
  connected,
  finished,
}: {
  events: RunEvent[];
  connected: boolean;
  finished: boolean;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <details className="group rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <span>
          Activity log{" "}
          <span className="font-normal text-muted-foreground">
            · {events.length} {events.length === 1 ? "event" : "events"}
          </span>
        </span>
        <span className="flex items-center gap-3 text-xs font-normal text-muted-foreground">
          <span className="flex items-center gap-1.5" role="status">
            <span
              className={cn(
                "size-1.5 rounded-full",
                finished ? "bg-muted-foreground" : connected ? "animate-pulse bg-success" : "bg-sev-medium",
              )}
            />
            {finished ? "Complete" : connected ? "Live" : "Reconnecting…"}
          </span>
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
        </span>
      </summary>
      <div ref={boxRef} className="max-h-80 overflow-y-auto border-t border-border px-5 py-3">
        {events.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No events recorded yet.</p>
        ) : (
          <ol className="space-y-2">
            {events.map((e) => (
              <li key={e.seq} className="flex items-start gap-3 text-sm">
                <time
                  dateTime={e.ts}
                  className="shrink-0 pt-0.5 font-mono text-xs tabular-nums text-muted-foreground"
                >
                  {clockTime(e.ts)}
                </time>
                <span
                  className={cn(
                    "min-w-0 flex-1 break-words",
                    e.type === "error" && "text-destructive",
                    e.type === "log" && "text-muted-foreground",
                  )}
                >
                  {e.message}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </details>
  );
}
