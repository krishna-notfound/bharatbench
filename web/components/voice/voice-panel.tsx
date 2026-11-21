"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Check, Mic, MicOff, RotateCcw, SendHorizontal, WifiOff, X } from "lucide-react";
import { Orb, ORB_LABEL } from "@/components/orb/orb";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { OPEN_AGENT_EVENT, toolLabel } from "./agent-events";
import { useVoiceSession, type VoiceLanguage } from "./use-voice-session";

const LANGUAGES: { value: VoiceLanguage; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "hi-IN", label: "हिन्दी" },
  { value: "en-IN", label: "English" },
];

const DESKTOP_QUERY = "(min-width: 768px)";

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

export function VoicePanel() {
  const voice = useVoiceSession();
  const desktop = useIsDesktop();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const { connect, disconnect } = voice;
  const openPanel = () => {
    setOpen(true);
    connect();
  };

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
  }, [voice.transcript, open]);

  const onOpenChange = (o: boolean) => {
    setOpen(o);
    if (!o) disconnect();
  };

  const offline = !voice.connected && !!voice.error;
  const speaking = voice.state === "speaking";
  const label = offline ? "The agent is offline right now" : ORB_LABEL[voice.orbState];

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    voice.sendText(draft);
    setDraft("");
  };

  return (
    <>
      {!open && (
        <button
          type="button"
          aria-label="Talk to BharatBench"
          onClick={openPanel}
          className="fixed right-4 bottom-4 z-40 flex size-14 items-center justify-center rounded-full border border-border bg-card shadow-[0_8px_24px_rgba(124,92,255,0.22)] transition-transform hover:scale-105 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none md:right-8 md:bottom-8"
        >
          <Orb state={voice.orbState} size="sm" />
        </button>
      )}

      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side={desktop ? "right" : "bottom"}
          className={cn(
            "gap-0 border-border bg-background p-0",
            desktop
              ? "data-[side=right]:sm:max-w-md"
              : "max-h-[88dvh] rounded-t-3xl",
          )}
        >
          <header className="flex flex-col items-center gap-1 border-b border-border px-4 pt-6 pb-4">
            <button
              type="button"
              onClick={() => speaking && voice.interrupt()}
              aria-label={speaking ? "Interrupt the agent" : "BharatBench agent"}
              className={cn("rounded-full outline-none", speaking ? "cursor-pointer" : "cursor-default")}
            >
              <Orb state={offline ? "error" : voice.orbState} size="md" />
            </button>
            <SheetTitle className="mt-2 text-base">BharatBench</SheetTitle>
            <SheetDescription role="status" aria-live="polite" className="text-xs">
              {label}
              {speaking && " · tap the orb to interrupt"}
            </SheetDescription>
            <div className="mt-2 flex items-center gap-2">
              <select
                aria-label="Language"
                value={voice.language}
                onChange={(e) => voice.setLanguage(e.target.value as VoiceLanguage)}
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
                onClick={voice.clearTranscript}
                disabled={voice.transcript.length === 0}
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
            {!offline && voice.transcript.length === 0 && (
              <p className="text-center text-sm text-muted-foreground">
                Ask in Hindi, English or Hinglish. Try &quot;show my recent sessions&quot; or &quot;test my app on a
                slow network&quot;.
              </p>
            )}
            {voice.transcript.map((item) =>
              item.role === "tool" ? (
                <span
                  key={item.id}
                  className={cn(
                    "inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
                    item.ok === false
                      ? "border-destructive/30 bg-destructive/10 text-destructive"
                      : "border-border bg-accent text-accent-foreground",
                  )}
                >
                  {item.ok === false ? <X className="size-3" /> : <Check className="size-3" />}
                  {item.toolName ? toolLabel(item.toolName) : item.text}
                </span>
              ) : (
                <div
                  key={item.id}
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm",
                    item.role === "user" && "self-end bg-primary text-primary-foreground",
                    item.role === "assistant" && "self-start border border-border bg-card",
                    item.role === "system" && "self-center text-xs text-muted-foreground",
                  )}
                >
                  {item.text}
                </div>
              ),
            )}
            <p className="mt-auto pt-2 text-center text-[11px] text-muted-foreground">
              Saved in this browser for convenience.
            </p>
          </div>

          {voice.error && !offline && (
            <p className="border-t border-border px-4 py-1.5 text-xs text-destructive" role="alert">
              {voice.error}
            </p>
          )}

          <form onSubmit={submit} className="flex items-center gap-2 border-t border-border bg-card p-3">
            <Button
              type="button"
              size="icon-lg"
              variant={voice.micOn ? "default" : "outline"}
              className="size-10 rounded-full"
              aria-label={voice.micOn ? "Stop microphone" : "Start microphone"}
              aria-pressed={voice.micOn}
              disabled={!voice.connected}
              onClick={() => void voice.toggleMic()}
            >
              {voice.micOn ? <Mic /> : <MicOff />}
            </Button>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={voice.connected ? "Type a message" : "Agent offline"}
              aria-label="Message"
              disabled={!voice.connected}
              className="h-10 min-w-0 flex-1 rounded-full border border-input bg-background px-4 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
            />
            <Button
              type="submit"
              size="icon-lg"
              className="size-10 rounded-full"
              aria-label="Send message"
              disabled={!voice.connected || !draft.trim()}
            >
              <SendHorizontal />
            </Button>
          </form>
        </SheetContent>
      </Sheet>
    </>
  );
}
