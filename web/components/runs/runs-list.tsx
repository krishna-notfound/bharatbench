"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FlaskConical } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, ErrorState } from "@/components/shell/states";
import { useFetch } from "@/components/shell/use-fetch";
import { StatusBadge } from "@/components/runs/status-badge";
import { listRuns } from "@/lib/api";
import { relativeTime, runTitle } from "@/lib/format";
import { TERMINAL_STATUSES, type Run } from "@/lib/types";

const POLL_MS = 5000;

function pollWhileActive(runs: Run[] | null): number | null {
  if (!runs) return POLL_MS;
  return runs.some((r) => !TERMINAL_STATUSES.includes(r.status))
    ? POLL_MS
    : null;
}

export function RunsList() {
  const router = useRouter();
  const { data, error, loading, reload } = useFetch(listRuns, pollWhileActive);

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    );
  }
  if (error && !data) {
    return (
      <ErrorState
        title="Could not load runs"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        icon={<FlaskConical className="size-6" />}
        title="No runs yet"
        message="Upload an APK to run your first Cheap Phone Test."
        action={
          <Link href="/" className={buttonVariants({ size: "lg" })}>
            Run a test
          </Link>
        }
      />
    );
  }

  return (
    <div className="space-y-2">
      {error && (
        <p role="alert" className="text-xs text-destructive">
          Refresh failed: {error}. Showing last known data.
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>App</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Profiles</TableHead>
              <TableHead className="text-right">Critical</TableHead>
              <TableHead className="text-right">High</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead className="text-right">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((r) => (
              <TableRow
                key={r.id}
                className="cursor-pointer"
                onClick={() => router.push(`/runs/${r.id}`)}
              >
                <TableCell className="max-w-64">
                  <Link
                    href={`/runs/${r.id}`}
                    className="block truncate font-medium outline-none hover:text-primary focus-visible:text-primary"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {runTitle(r)}
                  </Link>
                  <span className="block truncate font-mono text-xs text-muted-foreground">
                    {r.app?.package_name ?? r.apk_name}
                  </span>
                </TableCell>
                <TableCell>
                  <StatusBadge status={r.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {r.profile_ids.length}
                  <span className="sr-only"> profiles</span>
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {r.summary ? r.summary.counts.critical : "—"}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {r.summary ? r.summary.counts.high : "—"}
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {r.summary ? Math.round(r.summary.reliability_score) : "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap text-right text-muted-foreground">
                  {relativeTime(r.created_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
