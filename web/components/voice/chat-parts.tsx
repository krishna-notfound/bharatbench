"use client";

import Link from "next/link";
import { Check, ExternalLink, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { TERMINAL_STATUSES } from "@/lib/types";
import type { JobUpdate, Message } from "@/lib/realtime/useRealtime";
import { toolLabel } from "./agent-events";

export function ToolChip({ item }: { item: Message }) {
  const running = item.ok === undefined;
  const failed = item.ok === false;
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
        failed
          ? "border-destructive/30 bg-destructive/10 text-destructive"
          : "border-border bg-accent text-accent-foreground",
      )}
    >
      {running ? <Loader2 className="size-3 animate-spin" /> : failed ? <X className="size-3" /> : <Check className="size-3" />}
      {running && item.text ? item.text : item.toolName ? toolLabel(item.toolName) : item.text}
    </span>
  );
}

export const REPORT_QUESTIONS = [
  "Summarise this report",
  "How do I fix the top issue?",
  "What should I improve first?",
  "Run deeper tests",
];

export function JobCard({
  job,
  className,
  onAsk,
}: {
  job: JobUpdate | undefined;
  className?: string;
  onAsk?: (text: string) => void;
}) {
  if (!job) return null;
  const terminal = TERMINAL_STATUSES.includes(job.status);
  const pct = job.progress === null ? null : Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
  return (
    <div
      className={cn(
        "flex w-full max-w-[85%] flex-col gap-2 self-start rounded-2xl border border-border bg-card px-3.5 py-3 text-left",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium">Test {job.runId.slice(0, 8)}</span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5",
            job.status === "failed" ? "bg-destructive/10 text-destructive" : "bg-accent text-accent-foreground",
          )}
        >
          {job.status}
        </span>
      </div>
      {job.message && <p className="text-sm text-muted-foreground">{job.message}</p>}
      {!terminal && (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={pct ?? undefined}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className={cn("h-full rounded-full bg-primary", pct === null && "w-1/3 animate-pulse")}
            style={pct === null ? undefined : { width: `${pct}%` }}
          />
        </div>
      )}
      <Link
        href={`/runs/${job.runId}`}
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        {job.status === "done" ? "Open full report" : terminal ? "Open results" : "Watch live"}{" "}
        <ExternalLink className="size-3" />
      </Link>
      {job.status === "done" && onAsk && (
        <div className="flex flex-wrap gap-1.5" aria-label="Ask about this report">
          {REPORT_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function MessageBubble({ item }: { item: Message }) {
  return (
    <div
      className={cn(
        "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm",
        item.role === "user" && "self-end bg-primary text-primary-foreground",
        item.role === "assistant" && "self-start border border-border bg-card",
        item.role === "system" && "self-center text-xs text-muted-foreground",
        item.interrupted && "opacity-70",
      )}
    >
      {item.text}
      {item.streaming && <span className="ml-0.5 inline-block animate-pulse">▍</span>}
      {item.interrupted && <span className="ml-1 text-xs text-muted-foreground">(interrupted)</span>}
    </div>
  );
}

export function Thread({
  items,
  jobs,
  onAsk,
}: {
  items: Message[];
  jobs: Record<string, JobUpdate>;
  onAsk?: (text: string) => void;
}) {
  return (
    <>
      {items.map((item) => {
        if (item.role === "tool") return <ToolChip key={item.id} item={item} />;
        if (item.role === "job" && item.runId) return <JobCard key={item.id} job={jobs[item.runId]} onAsk={onAsk} />;
        return <MessageBubble key={item.id} item={item} />;
      })}
    </>
  );
}
