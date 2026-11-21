"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, ChevronRight, Hourglass } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/shell/states";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { FindingSheet } from "@/components/findings/finding-sheet";
import { findingSourceLabel, impactSentence } from "@/components/findings/finding-text";
import type { Finding } from "@/lib/types";

const CARD =
  "rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]";

export function sortByImpact(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => (b.impact?.score ?? -1) - (a.impact?.score ?? -1));
}

export function FindingsSection({
  runId,
  findings,
  loading,
  error,
  onRetry,
  runActive,
}: {
  runId: string;
  findings: Finding[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  runActive: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const sorted = useMemo(() => sortByImpact(findings ?? []), [findings]);
  const selected = sorted.find((f) => f.id === openId) ?? null;

  let body;
  if (loading) {
    body = (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-28 w-full rounded-3xl" />
        ))}
      </div>
    );
  } else if (error && !findings) {
    body = <ErrorState title="Could not load the issues" message={error} onRetry={onRetry} />;
  } else if (sorted.length === 0) {
    body = runActive ? (
      <EmptyState
        icon={<Hourglass className="size-6" />}
        title="No issues yet"
        message="They show up here as soon as I spot them."
      />
    ) : (
      <EmptyState
        icon={<CheckCircle2 className="size-6 text-success" />}
        title="No issues found under these conditions"
      />
    );
  } else {
    body = (
      <ul className="space-y-3">
        {sorted.map((f, idx) => (
          <li key={f.id}>
            <button
              type="button"
              onClick={() => setOpenId(f.id)}
              aria-label={`Open issue: ${f.title}`}
              className={`${CARD} group flex w-full items-start gap-4 p-5 text-left transition-all outline-none hover:border-primary/40 hover:shadow-[0_12px_32px_rgba(124,92,255,0.14)] focus-visible:ring-3 focus-visible:ring-ring/50`}
            >
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  {idx === 0 && (
                    <span className="rounded-full bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-foreground">
                      Biggest impact
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">{findingSourceLabel(f)}</span>
                </div>
                <h3 className="text-base leading-snug font-semibold">{f.title}</h3>
                <p className="line-clamp-2 text-sm text-muted-foreground">{impactSentence(f)}</p>
              </div>
              <ChevronRight className="mt-1 size-5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section className="space-y-4" aria-label="Issues">
      <h2 className="text-lg font-semibold tracking-tight">
        {sorted.length > 0 ? "What I found" : "Issues"}
      </h2>
      {error && findings && (
        <p role="alert" className="text-xs text-destructive">
          Refresh failed. Showing the last data I have.
        </p>
      )}
      {body}
      <FindingSheet runId={runId} finding={selected} onClose={() => setOpenId(null)} />
    </section>
  );
}
