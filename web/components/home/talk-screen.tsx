"use client";

import { useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { ArrowRight, MessageCircle, Mic, MicOff, PhoneOff, WifiOff } from "lucide-react";
import { Orb, ORB_LABEL } from "@/components/orb/orb";
import { useAgent } from "@/components/voice/realtime-provider";
import { ToolChip, JobCard } from "@/components/voice/chat-parts";
import { PRIMARY_CTA } from "@/components/shell/surface";
import type { RealtimeLanguage } from "@/lib/realtime/useRealtime";
import { cn } from "@/lib/utils";

const LANGUAGES: { value: RealtimeLanguage; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "hi-IN", label: "हिन्दी" },
  { value: "en-IN", label: "English" },
];

const STATE_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  working: "Working on it…",
  offline: "Voice service unavailable",
};

const SUGGESTIONS = ["Test my app on a slow network", "Show my recent sessions", "What can you check?"];

function ControlButton({
  label,
  onClick,
  active,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex size-12 items-center justify-center rounded-full border outline-none transition-colors focus-visible:ring-4 focus-visible:ring-ring/30 disabled:opacity-40",
        active
          ? "border-primary bg-primary text-primary-foreground shadow-[0_8px_24px_rgba(124,92,255,0.3)]"
          : "border-border bg-card text-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}

export function TalkScreen() {
  const rt = useAgent();
  const { connect, disconnect, toggleMic, connected, micOn } = rt;
  const wantMic = useRef(false);
  const pendingText = useRef<string | null>(null);

  useEffect(() => {
    if (pendingText.current && connected) {
      const text = pendingText.current;
      pendingText.current = null;
      rt.sendText(text);
    }
  }, [connected, rt]);

  // First tap connects; the mic starts as soon as the session is ready (still inside the user's intent).
  useEffect(() => {
    if (wantMic.current && connected) {
      wantMic.current = false;
      if (!micOn) void toggleMic();
    }
  }, [connected, micOn, toggleMic]);

  const active = rt.state !== "idle";
  const speaking = rt.state === "speaking";
  const busy = speaking || rt.state === "thinking" || rt.state === "working";
  const hasConversation = rt.transcript.length > 0;

  const onOrb = () => {
    if (busy) return rt.interrupt();
    if (!connected) {
      wantMic.current = true;
      connect();
      return;
    }
    void toggleMic();
  };

  const label = STATE_LABEL[rt.state] ?? (rt.state === "idle" ? "Tap to talk" : ORB_LABEL[rt.orbState]);

  const { lastUser, lastAssistant, tools, jobIds } = useMemo(() => {
    const t = rt.transcript;
    const lastU = [...t].reverse().find((m) => m.role === "user");
    const lastA = [...t].reverse().find((m) => m.role === "assistant");
    const since = lastU ? t.indexOf(lastU) : 0;
    return {
      lastUser: lastU,
      lastAssistant: lastA,
      tools: t.slice(since).filter((m) => m.role === "tool").slice(-3),
      jobIds: [...new Set(t.filter((m) => m.role === "job" && m.runId).map((m) => m.runId as string))],
    };
  }, [rt.transcript]);

  const frame = speaking ? rt.caption : null;

  return (
    <section className="flex flex-col items-center text-center" aria-label="Talk to BharatBench">
      <button
        type="button"
        onClick={onOrb}
        aria-label={busy ? "Interrupt BharatBench" : micOn ? "Mute microphone" : "Talk to BharatBench"}
        className="mt-2 rounded-full outline-none transition-transform focus-visible:ring-4 focus-visible:ring-ring/30 active:scale-[0.98]"
      >
        <Orb state={rt.orbState} size="xl" getLevel={rt.getLevel} />
      </button>

      <p role="status" aria-live="polite" className="mt-6 text-sm font-medium text-muted-foreground">
        {label}
        {speaking && " · tap the orb to interrupt"}
      </p>

      {!hasConversation && !active && (
        <div className="mt-4">
          <h1 className="text-4xl font-semibold tracking-tight md:text-6xl">Hi, I&apos;m BharatBench</h1>
          <p className="mx-auto mt-4 max-w-md text-base text-muted-foreground md:text-lg">
            Talk to me about your Android app. I run it on the everyday phones your users really carry and tell you
            what breaks and who it affects.
          </p>
        </div>
      )}

      <div className="mt-5 flex min-h-24 w-full max-w-xl flex-col items-center gap-3" aria-live="off">
        {lastUser && hasConversation && (
          <p className="max-w-full text-sm text-muted-foreground">&ldquo;{lastUser.text}&rdquo;</p>
        )}
        {frame ? (
          <p className="text-xl leading-snug font-medium md:text-2xl">
            {frame.words.map((w, i) => (
              <span key={i} className={cn("transition-opacity duration-200", i < frame.revealed ? "opacity-100" : "opacity-25")}>
                {w}{" "}
              </span>
            ))}
          </p>
        ) : (
          lastAssistant &&
          (lastAssistant.streaming || !speaking) && (
            <p className={cn("text-lg leading-snug md:text-xl", lastAssistant.interrupted && "opacity-70")}>
              {lastAssistant.text}
              {lastAssistant.streaming && <span className="ml-0.5 inline-block animate-pulse">▍</span>}
            </p>
          )
        )}
        {tools.length > 0 && (
          <div className="flex flex-wrap justify-center gap-1.5">
            {tools.map((m) => (
              <ToolChip key={m.id} item={m} />
            ))}
          </div>
        )}
      </div>

      {rt.error && (
        <div
          role="alert"
          className="mt-3 flex max-w-md items-center gap-2 rounded-2xl border border-border bg-card px-4 py-2.5 text-sm text-muted-foreground"
        >
          {rt.state === "offline" && <WifiOff className="size-4 shrink-0" />}
          <span>{rt.error}</span>
          {rt.state === "offline" && (
            <button type="button" onClick={() => connect()} className="shrink-0 font-medium text-primary hover:underline">
              Try again
            </button>
          )}
        </div>
      )}

      <div className="mt-5 flex items-center gap-3">
        <ControlButton
          label={micOn ? "Mute microphone" : "Start microphone"}
          active={micOn}
          onClick={() => {
            if (!connected) {
              wantMic.current = true;
              connect();
            } else void toggleMic();
          }}
        >
          {micOn ? <Mic className="size-5" /> : <MicOff className="size-5" />}
        </ControlButton>
        <ControlButton label="End conversation" disabled={!active} onClick={disconnect}>
          <PhoneOff className="size-5" />
        </ControlButton>
        <Link
          href="/chat"
          aria-label="Open chat"
          title="Open chat"
          className="flex size-12 items-center justify-center rounded-full border border-border bg-card outline-none transition-colors hover:bg-accent focus-visible:ring-4 focus-visible:ring-ring/30"
        >
          <MessageCircle className="size-5" />
        </Link>
        <select
          aria-label="Language"
          value={rt.language}
          onChange={(e) => rt.setLanguage(e.target.value as RealtimeLanguage)}
          className="h-12 rounded-full border border-border bg-card px-4 text-sm outline-none focus-visible:ring-4 focus-visible:ring-ring/30"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      {jobIds.length > 0 && (
        <div className="mt-6 flex w-full max-w-xl flex-col gap-3">
          {jobIds.map((id) => (
            <JobCard key={id} job={rt.jobs[id]} onAsk={rt.sendText} className="max-w-full self-stretch" />
          ))}
        </div>
      )}

      {!hasConversation && (
        <ul className="mt-6 flex max-w-xl flex-wrap justify-center gap-2" aria-label="Things to try">
          {SUGGESTIONS.map((s) => (
            <li key={s}>
              <button
                type="button"
                onClick={() => {
                  pendingText.current = s;
                  connect();
                }}
                className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              >
                {s}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-8">
        <Link href="/new" className={cn(PRIMARY_CTA)}>
          Test my app <ArrowRight className="size-5" />
        </Link>
      </div>
    </section>
  );
}
