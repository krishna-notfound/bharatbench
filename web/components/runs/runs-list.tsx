"use client";

import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Orb, orbStateFromRun } from "@/components/orb/orb";
import { EmptyState, ErrorState } from "@/components/shell/states";
import { useFetch } from "@/components/shell/use-fetch";
import { CARD, CARD_HOVER, PRIMARY_CTA } from "@/components/shell/surface";
import { sessionLine, runTitle } from "@/components/runs/session-summary";
import { listRuns } from "@/lib/api";
import { STATUS_LABEL, relativeTime } from "@/lib/format";
import { TERMINAL_STATUSES, type Run } from "@/lib/types";
import { cn } from "@/lib/utils";

const POLL_MS = 5000;

function pollWhileActive(runs: Run[] | null): number | null {
  if (!runs) return POLL_MS;
  return runs.some((r) => !TERMINAL_STATUSES.includes(r.status))
    ? POLL_MS
    : null;
}

export function RunsList() {
  const { data, error, loading, reload } = useFetch(listRuns, pollWhileActive);

  if (loading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 w-full rounded-3xl" />
        ))}
      </div>
    );
  }
  if (error && !data) {
    return (
      <ErrorState
        title="I can't reach my test lab"
        message="Your sessions will show up here as soon as I'm back online."
        onRetry={reload}
        className="rounded-3xl"
      />
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<FlaskConical className="size-6" />}
        title="No sessions yet"
        message="Upload an APK and I'll run your first test."
        className="rounded-3xl"
        action={
          <Link href="/new" className={PRIMARY_CTA}>
            Test my app
          </Link>
        }
      />
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="px-1 text-xs text-muted-foreground">
          I couldn&apos;t refresh just now. Showing what I had before.
        </p>
      )}
      <ul className="space-y-3">
        {data.map((r) => (
          <li key={r.id}>
            <Link
              href={`/runs/${r.id}`}
              className={cn(
                CARD,
                CARD_HOVER,
                "flex items-center gap-4 p-4 outline-none focus-visible:ring-2 focus-visible:ring-primary md:p-5",
              )}
            >
              <Orb
                state={orbStateFromRun(r.status)}
                size="sm"
                className="shrink-0"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{runTitle(r)}</p>
                <p className="truncate text-sm text-muted-foreground">
                  {sessionLine(r)}
                </p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {STATUS_LABEL[r.status]} · {relativeTime(r.created_at)}
                </p>
              </div>
              {r.summary && r.summary.total_findings > 0 && (
                <span
                  className={cn(
                    "shrink-0 rounded-full px-3 py-1 text-sm font-medium tabular-nums",
                    r.summary.counts.critical > 0
                      ? "bg-sev-critical/10 text-sev-critical"
                      : "bg-accent text-accent-foreground",
                  )}
                  aria-label={`${r.summary.total_findings} issues`}
                >
                  {r.summary.total_findings}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
