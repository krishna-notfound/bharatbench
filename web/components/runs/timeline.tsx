"use client";

import { useEffect, useRef } from "react";
import {
  AlertOctagon,
  Bug,
  CheckCircle2,
  CircleDot,
  Footprints,
  Image as ImageIcon,
  ScrollText,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { clockTime, STATUS_LABEL } from "@/lib/format";
import type { EventType, RunEvent, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON: Record<EventType, { Icon: typeof Bug; cls: string }> = {
  status: { Icon: CircleDot, cls: "text-accent-info" },
  log: { Icon: ScrollText, cls: "text-muted-foreground" },
  step: { Icon: Footprints, cls: "text-primary" },
  finding: { Icon: Bug, cls: "text-sev-high" },
  artifact: { Icon: ImageIcon, cls: "text-muted-foreground" },
  done: { Icon: CheckCircle2, cls: "text-success" },
  error: { Icon: AlertOctagon, cls: "text-destructive" },
};

const STEPS: RunStatus[] = [
  "analyzing",
  "provisioning",
  "running",
  "scoring",
  "done",
];

export function StatusStepper({ status }: { status: RunStatus }) {
  const idx = STEPS.indexOf(status);
  const stopped = status === "failed" || status === "cancelled";
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1" aria-label="Run progress">
      {STEPS.map((s, i) => {
        const complete = status === "done" || (idx >= 0 && i < idx);
        const current = !stopped && i === idx && status !== "done";
        return (
          <li key={s} className="flex items-center gap-1">
            <span
              aria-current={current ? "step" : undefined}
              className={cn(
                "whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium",
                complete && "bg-success/15 text-success",
                current && "bg-primary/15 text-primary",
                !complete && !current && "bg-muted text-muted-foreground",
              )}
            >
              {current && (
                <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-current align-middle" />
              )}
              {STATUS_LABEL[s]}
            </span>
            {i < STEPS.length - 1 && (
              <span className="h-px w-3 bg-border" aria-hidden />
            )}
          </li>
        );
      })}
      {stopped && (
        <li className="ml-2">
          <span
            className={cn(
              "rounded-full px-2.5 py-1 text-xs font-medium",
              status === "failed"
                ? "bg-destructive/15 text-destructive"
                : "bg-muted text-muted-foreground",
            )}
          >
            {STATUS_LABEL[status]}
          </span>
        </li>
      )}
    </ol>
  );
}

export function Timeline({
  events,
  connected,
  finished,
  status,
}: {
  events: RunEvent[];
  connected: boolean;
  finished: boolean;
  status: RunStatus;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Live timeline
        </h2>
        <span
          className="flex items-center gap-1.5 text-xs text-muted-foreground"
          role="status"
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              finished
                ? "bg-muted-foreground"
                : connected
                  ? "animate-pulse bg-success"
                  : "bg-sev-medium",
            )}
          />
          {finished ? "Complete" : connected ? "Live" : "Reconnecting…"}
        </span>
      </div>
      <div className="border-b border-border px-4 py-3">
        <StatusStepper status={status} />
      </div>
      <div
        ref={boxRef}
        className="max-h-96 min-h-48 flex-1 overflow-y-auto px-4 py-3"
        aria-live="off"
      >
        {events.length === 0 ? (
          finished || connected ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No events recorded for this run.
            </p>
          ) : (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-5 w-full" />
              ))}
            </div>
          )
        ) : (
          <ol className="space-y-2.5">
            {events.map((e) => {
              const { Icon, cls } = ICON[e.type];
              return (
                <li key={e.seq} className="flex items-start gap-2.5 text-sm">
                  <Icon className={cn("mt-0.5 size-4 shrink-0", cls)} />
                  <span className="min-w-0 flex-1 break-words">
                    {e.message}
                  </span>
                  <time
                    dateTime={e.ts}
                    className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground"
                  >
                    {clockTime(e.ts)}
                  </time>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
