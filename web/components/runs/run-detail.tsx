"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, Download, Loader2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Orb, ORB_LABEL, orbStateFromRun } from "@/components/orb/orb";
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
import { ActivityLog, CompactSteps } from "@/components/runs/timeline";
import { cancelRun, getFindings, getRun, reportUrl } from "@/lib/api";
import { runTitle } from "@/lib/format";
import { TERMINAL_STATUSES, type Finding, type Run, type RunEvent, type Severity } from "@/lib/types";
import { useRunEvents } from "@/lib/ws";

async function saveReport(runId: string) {
  try {
    const res = await fetch(reportUrl(runId));
    if (!res.ok) throw new Error(String(res.status));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `bharatbench-${runId}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    toast.error("Could not download the report. Please try again.");
  }
}

const CARD =
  "rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]";

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** Plain-language sentence computed only from the run summary and findings. */
export function summarySentence(run: Run, findings: Finding[] | null): string | null {
  const s = run.summary;
  if (run.status === "failed") return "This test didn't finish, so there are no results to show.";
  if (run.status === "cancelled") return "This test was cancelled before it finished.";
  if (!s) return null;
  const scan = s.runtime_executed ? "" : " in the APK scan";
  if (s.total_findings === 0) {
    return s.runtime_executed
      ? "No issues found under the conditions I tested."
      : "No issues found in the APK scan. The emulator test was skipped.";
  }
  const order: Severity[] = ["critical", "high", "medium", "low"];
  const parts = order.filter((k) => s.counts[k] > 0).slice(0, 2);
  const top = parts[0];
  const label =
    parts.length === 1
      ? plural(s.counts[top], `${top} issue`)
      : `${plural(s.counts[parts[0]], `${parts[0]} issue`)} and ${plural(s.counts[parts[1]], `${parts[1]} issue`)}`;
  let reach = "";
  if (findings && findings.length > 0) {
    const serious = findings.filter((f) => f.severity === "critical" || f.severity === "high");
    const pool = serious.length ? serious : findings;
    const max = Math.max(...pool.map((f) => f.impact?.users_exposed ?? 0));
    if (max > 0) reach = ` that could affect about ${Math.round(max * 100)}% of users`;
  }
  return `Found ${label}${scan}${reach}.`;
}

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
    if (e.type === "status" || e.type === "finding" || e.type === "done") void refreshRun();
    if (e.type === "finding" || e.type === "done") void refreshFindings();
  });

  const r = run.data;
  const sentence = useMemo(() => (r ? summarySentence(r, findings.data) : null), [r, findings.data]);

  async function doCancel() {
    setCancelling(true);
    try {
      await cancelRun(runId);
      toast.success("Test cancelled");
      setConfirmOpen(false);
      void refreshRun();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not cancel the test");
    } finally {
      setCancelling(false);
    }
  }

  const back = (
    <Link
      href="/runs"
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-4" /> All sessions
    </Link>
  );

  if (run.loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 py-8">
        <Skeleton className="mx-auto size-24 rounded-full" />
        <Skeleton className="mx-auto h-6 w-64" />
        <Skeleton className="h-40 rounded-3xl" />
      </div>
    );
  }
  if (run.error && !r) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 py-8">
        {back}
        <ErrorState
          title={/not found|404/i.test(run.error) ? "I couldn't find that session" : "I couldn't load this session"}
          message={
            /not found|404/i.test(run.error)
              ? "It may have been removed, or the link is wrong. Head back to your sessions."
              : "The service may be offline right now. Please try again in a moment."
          }
          onRetry={run.reload}
        />
      </div>
    );
  }
  if (!r) return null;

  const active = !TERMINAL_STATUSES.includes(r.status);
  const orbState = orbStateFromRun(r.status);
  const latest = stream.events.length > 0 ? stream.events[stream.events.length - 1].message : null;
  const runtimeSkipped = r.summary?.runtime_executed === false;

  return (
    <div className="mx-auto max-w-5xl space-y-8 py-8 md:py-12">
      <div className="space-y-6">
        {back}
        <div className="flex flex-col items-center gap-4 text-center">
          <Orb state={orbState} size="lg" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-primary">{ORB_LABEL[orbState]}</p>
            <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{runTitle(r)}</h1>
            {active && (
              <p className="mx-auto max-w-md text-sm text-muted-foreground" aria-live="polite">
                {latest ?? "Getting started…"}
              </p>
            )}
          </div>
          <CompactSteps status={r.status} runtimeSkipped={runtimeSkipped} />
          <div className="flex flex-wrap justify-center gap-2">
            {active && (
              <Button variant="outline" className="h-9 rounded-full px-4" onClick={() => setConfirmOpen(true)}>
                <XCircle /> Cancel test
              </Button>
            )}
            <a
              href={reportUrl(runId)}
              target="_blank"
              rel="noreferrer"
              download={`bharatbench-${runId}.md`}
              onClick={(e) => {
                // Cross-origin `download` is ignored by browsers; fetch the file and save it ourselves.
                e.preventDefault();
                void saveReport(runId);
              }}
              className={`${buttonVariants({ variant: "secondary" })} h-9 rounded-full px-4`}
            >
              <Download /> Download report
            </a>
          </div>
        </div>

        {r.error && (
          <p
            role="alert"
            className="rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {r.error}
          </p>
        )}
        {run.error && (
          <p role="alert" className="text-center text-xs text-destructive">
            I couldn&apos;t refresh just now. Showing the last data I have.
          </p>
        )}
      </div>

      {(sentence || r.summary) && (
        <section className={`${CARD} space-y-5 p-6 md:p-8`}>
          {sentence && <p className="text-xl leading-snug font-semibold tracking-tight md:text-2xl">{sentence}</p>}
          <ScorePanel run={r} />
        </section>
      )}

      <FindingsSection
        runId={runId}
        findings={findings.data}
        loading={findings.loading}
        error={findings.error}
        onRetry={findings.reload}
        runActive={active}
      />

      <ActivityLog events={stream.events} connected={stream.connected} finished={stream.finished} />

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel this test?</DialogTitle>
            <DialogDescription>
              I&apos;ll stop right away and mark it as cancelled. You can start a new test with the same APK any time.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={cancelling}>
              Keep running
            </Button>
            <Button variant="destructive" onClick={doCancel} disabled={cancelling}>
              {cancelling && <Loader2 className="animate-spin" />}
              Cancel test
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
