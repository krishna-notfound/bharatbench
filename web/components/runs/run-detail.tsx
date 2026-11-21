"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Download, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/shell/states";
import { useFetch } from "@/components/shell/use-fetch";
import { FindingsSection } from "@/components/findings/findings-section";
import { ScorePanel } from "@/components/runs/score-panel";
import { StatusBadge } from "@/components/runs/status-badge";
import { Timeline } from "@/components/runs/timeline";
import { cancelRun, getFindings, getRun, reportUrl } from "@/lib/api";
import { formatBytes, runTitle } from "@/lib/format";
import { TERMINAL_STATUSES, type RunEvent } from "@/lib/types";
import { useRunEvents } from "@/lib/ws";

export function RunDetail({ runId }: { runId: string }) {
  const run = useFetch(
    () => getRun(runId),
    (r) => (r && TERMINAL_STATUSES.includes(r.status) ? null : 6000),
  );
  const findings = useFetch(() => getFindings(runId));
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const { refresh: refreshRun } = run;
  const { refresh: refreshFindings } = findings;
  const stream = useRunEvents(runId, (e: RunEvent) => {
    if (e.type === "status" || e.type === "finding" || e.type === "done") {
      void refreshRun();
    }
    if (e.type === "finding" || e.type === "done") {
      void refreshFindings();
    }
  });

  async function doCancel() {
    setCancelling(true);
    try {
      await cancelRun(runId);
      toast.success("Run cancelled");
      setConfirmOpen(false);
      void refreshRun();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not cancel run");
    } finally {
      setCancelling(false);
    }
  }

  if (run.loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <Skeleton className="h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }
  if (run.error && !run.data) {
    return (
      <div className="space-y-4">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> All runs
        </Link>
        <ErrorState
          title="Could not load this run"
          message={run.error}
          onRetry={run.reload}
        />
      </div>
    );
  }
  const r = run.data;
  if (!r) return null;
  const active = !TERMINAL_STATUSES.includes(r.status);

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> All runs
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="truncate text-2xl font-semibold tracking-tight">
                {runTitle(r)}
              </h1>
              <StatusBadge status={r.status} />
            </div>
            <p className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-xs text-muted-foreground">
              {r.app?.package_name && <span>{r.app.package_name}</span>}
              {r.app?.version_name && <span>v{r.app.version_name}</span>}
              {r.app && <span>{formatBytes(r.app.size_bytes)}</span>}
              <span>{r.apk_name}</span>
            </p>
          </div>
          <div className="flex gap-2">
            {active && (
              <Button variant="outline" onClick={() => setConfirmOpen(true)}>
                <XCircle /> Cancel run
              </Button>
            )}
            <a
              href={reportUrl(runId)}
              target="_blank"
              rel="noreferrer"
              download={`bharatbench-${runId}.md`}
              className={buttonVariants({ variant: "secondary" })}
            >
              <Download /> Download report
            </a>
          </div>
        </div>
        {r.error && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {r.error}
          </p>
        )}
        {run.error && (
          <p role="alert" className="text-xs text-destructive">
            Refresh failed: {run.error}. Showing last known data.
          </p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <Timeline
          events={stream.events}
          connected={stream.connected}
          finished={stream.finished}
          status={r.status}
          runtimeSkipped={r.summary?.runtime_executed === false}
        />
        <ScorePanel run={r} />
      </div>

      <FindingsSection
        runId={runId}
        findings={findings.data}
        loading={findings.loading}
        error={findings.error}
        onRetry={findings.reload}
        runActive={active}
      />

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel this run?</DialogTitle>
            <DialogDescription>
              The test stops and the run is marked as cancelled. You can start
              a new test with the same APK at any time.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={cancelling}
            >
              Keep running
            </Button>
            <Button
              variant="destructive"
              onClick={doCancel}
              disabled={cancelling}
            >
              {cancelling && <Loader2 className="animate-spin" />}
              Cancel run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
