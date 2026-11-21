"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Orb, orbStateFromRun } from "@/components/orb/orb";
import { useFetch } from "@/components/shell/use-fetch";
import { CARD, CARD_HOVER } from "@/components/shell/surface";
import { sessionLine, runTitle } from "@/components/runs/session-summary";
import { listRuns } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function RecentSessions() {
  const { data, error, loading } = useFetch(listRuns);

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-xl space-y-2">
        <Skeleton className="h-16 w-full rounded-3xl" />
        <Skeleton className="h-16 w-full rounded-3xl" />
      </div>
    );
  }
  if (error && !data) {
    return (
      <p className="mx-auto max-w-sm text-center text-sm text-muted-foreground">
        I can&apos;t reach my test lab right now, so recent sessions are
        hidden. You can still start a new test once it&apos;s back.
      </p>
    );
  }
  const runs = (data ?? []).slice(0, 3);
  if (runs.length === 0) return null;

  return (
    <section
      aria-labelledby="recent-heading"
      className="mx-auto w-full max-w-xl space-y-3"
    >
      <div className="flex items-baseline justify-between px-1">
        <h2
          id="recent-heading"
          className="text-sm font-medium text-muted-foreground"
        >
          Recent sessions
        </h2>
        <Link
          href="/runs"
          className="rounded text-sm text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
        >
          See all
        </Link>
      </div>
      <ul className="space-y-2">
        {runs.map((r) => (
          <li key={r.id}>
            <Link
              href={`/runs/${r.id}`}
              className={cn(
                CARD,
                CARD_HOVER,
                "flex items-center gap-3 px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-primary",
              )}
            >
              <Orb
                state={orbStateFromRun(r.status)}
                size="sm"
                className="shrink-0"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{runTitle(r)}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {sessionLine(r)} · {relativeTime(r.created_at)}
                </p>
              </div>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
