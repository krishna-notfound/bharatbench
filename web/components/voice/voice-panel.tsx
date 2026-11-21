"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { Check, ExternalLink, Loader2, Mic, MicOff, RotateCcw, SendHorizontal, WifiOff, X } from "lucide-react";
import { Orb, ORB_LABEL } from "@/components/orb/orb";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { TERMINAL_STATUSES } from "@/lib/types";
import {
  useRealtime,
  type JobUpdate,
  type Message,
  type RealtimeLanguage,
} from "@/lib/realtime/useRealtime";
import { OPEN_AGENT_EVENT, toolLabel } from "./agent-events";

const LANGUAGES: { value: RealtimeLanguage; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "hi-IN", label: "हिन्दी" },
  { value: "en-IN", label: "English" },
];

const DESKTOP_QUERY = "(min-width: 768px)";

const STATE_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  working: "Working on it…",
  offline: "The agent is offline right now",
};

function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(DESKTOP_QUERY);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  );
}

function ToolChip({ item }: { item: Message }) {
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

function JobCard({ job }: { job: JobUpdate | undefined; runId: string }) {
  if (!job) return null;
  const terminal = TERMINAL_STATUSES.includes(job.status);
  const pct = job.progress === null ? null : Math.round(Math.min(1, Math.max(0, job.progress)) * 100);
  return (
    <div className="flex w-full max-w-[85%] flex-col gap-2 self-start rounded-2xl border border-border bg-card px-3.5 py-3">
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
        {terminal ? "Open results" : "Watch live"} <ExternalLink className="size-3" />
      </Link>
    </div>
  );
}

export function VoicePanel() {
  const rt = useRealtime();
  const desktop = useIsDesktop();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const { connect, disconnect } = rt;

  useEffect(() => {
    const handler = () => {
      setOpen(true);
      connect();
    };
    window.addEventListener(OPEN_AGENT_EVENT, handler);
    return () => window.removeEventListener(OPEN_AGENT_EVENT, handler);
  }, [connect]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [rt.transcript, rt.jobs, open]);

  const onOpenChange = (o: boolean) => {
    setOpen(o);
    if (!o) disconnect();
  };

  const offline = rt.state === "offline";
  const speaking = rt.state === "speaking";
  const label = STATE_LABEL[rt.state] ?? ORB_LABEL[rt.orbState];
  const frame = speaking ? rt.caption : null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    rt.sendText(draft);
    setDraft("");
  };

  return (
    <>
      {!open && (
        <button
          type="button"
          aria-label="Talk to BharatBench"
          onClick={() => {
            setOpen(true);
            connect();
          }}
          className="fixed right-4 bottom-4 z-40 flex size-14 items-center justify-center rounded-full border border-border bg-card shadow-[0_8px_24px_rgba(124,92,255,0.22)] transition-transform hover:scale-105 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none md:right-8 md:bottom-8"
        >
          <Orb state={rt.orbState} size="sm" getLevel={rt.getLevel} />
        </button>
      )}

      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side={desktop ? "right" : "bottom"}
          className={cn(
            "gap-0 border-border bg-background p-0",
            desktop ? "data-[side=right]:sm:max-w-md" : "max-h-[88dvh] rounded-t-3xl",
          )}
        >
          <header className="flex flex-col items-center gap-1 border-b border-border px-4 pt-6 pb-4">
            <button
              type="button"
              onClick={() => (speaking || rt.state === "thinking" || rt.state === "working") && rt.interrupt()}
              aria-label={speaking ? "Interrupt the agent" : "BharatBench agent"}
              className={cn("rounded-full outline-none", speaking ? "cursor-pointer" : "cursor-default")}
            >
              <Orb state={rt.orbState} size="md" getLevel={rt.getLevel} />
            </button>
            <SheetTitle className="mt-2 text-base">BharatBench</SheetTitle>
            <SheetDescription role="status" aria-live="polite" className="text-xs">
              {label}
              {speaking && " · tap the orb to interrupt"}
            </SheetDescription>
            <div className="mt-2 flex items-center gap-2">
              <select
                aria-label="Language"
                value={rt.language}
                onChange={(e) => rt.setLanguage(e.target.value as RealtimeLanguage)}
                className="h-8 rounded-full border border-border bg-card px-3 text-xs outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="outline"
                className="h-8 rounded-full px-3"
                onClick={rt.newConversation}
                disabled={rt.transcript.length === 0 && !rt.conversationId}
              >
                <RotateCcw /> New conversation
              </Button>
            </div>
          </header>

          <div
            ref={listRef}
            className="flex min-h-48 flex-1 flex-col gap-2.5 overflow-y-auto px-4 py-4"
            aria-live="polite"
          >
            {offline && (
              <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border bg-card px-4 py-6 text-center">
                <WifiOff className="size-5 text-muted-foreground" />
                <p className="text-sm font-medium">The agent is offline right now</p>
                <p className="text-xs text-muted-foreground">
                  I can&apos;t reach the voice service. Your sessions and results still work.
                </p>
                <Button size="sm" variant="outline" className="rounded-full" onClick={connect}>
                  Try again
                </Button>
              </div>
            )}
            {!offline && rt.transcript.length === 0 && (
              <p className="text-center text-sm text-muted-foreground">
                Ask in Hindi, English or Hinglish. Try &quot;show my recent sessions&quot; or &quot;test my app on a
                slow network&quot;.
              </p>
            )}
            {rt.transcript.map((item) => {
              if (item.role === "tool") return <ToolChip key={item.id} item={item} />;
              if (item.role === "job" && item.runId) {
                return <JobCard key={item.id} runId={item.runId} job={rt.jobs[item.runId]} />;
              }
              return (
                <div
                  key={item.id}
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
            })}
          </div>

          {frame && (
            <div aria-live="off" className="border-t border-border bg-card px-4 py-2 text-center text-sm">
              {frame.words.map((word, i) => (
                <span key={i} className={cn("transition-opacity duration-200", i < frame.revealed ? "opacity-100" : "opacity-30")}>
                  {word}{" "}
                </span>
              ))}
            </div>
          )}

          {rt.error && !offline && (
            <p className="border-t border-border px-4 py-1.5 text-xs text-destructive" role="alert">
              {rt.error}
            </p>
          )}

          <form onSubmit={submit} className="flex items-center gap-2 border-t border-border bg-card p-3">
            <Button
              type="button"
              size="icon-lg"
              variant={rt.micOn ? "default" : "outline"}
              className="size-10 rounded-full"
              aria-label={rt.micOn ? "Stop microphone" : "Start microphone"}
              aria-pressed={rt.micOn}
              disabled={!rt.connected}
              onClick={() => void rt.toggleMic()}
            >
              {rt.micOn ? <Mic /> : <MicOff />}
            </Button>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={rt.connected ? "Type a message" : "Agent offline"}
              aria-label="Message"
              disabled={!rt.connected}
              className="h-10 min-w-0 flex-1 rounded-full border border-input bg-background px-4 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
            />
            <Button
              type="submit"
              size="icon-lg"
              className="size-10 rounded-full"
              aria-label="Send message"
              disabled={!rt.connected || !draft.trim()}
            >
              <SendHorizontal />
            </Button>
          </form>
        </SheetContent>
      </Sheet>
    </>
  );
}
