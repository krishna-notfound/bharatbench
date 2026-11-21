"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Mic, MicOff, RotateCcw, SendHorizontal, WifiOff } from "lucide-react";
import { Orb, ORB_LABEL } from "@/components/orb/orb";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { LANGUAGE_OPTIONS, type RealtimeLanguage } from "@/lib/realtime/languages";
import { OPEN_AGENT_EVENT } from "./agent-events";
import { Thread } from "./chat-parts";
import { useAgent } from "./realtime-provider";



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

export function VoicePanel() {
  const rt = useAgent();
  const desktop = useIsDesktop();
  const router = useRouter();
  const pathname = usePathname();
  const hidden = pathname === "/" || pathname === "/chat";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const { connect, disconnect } = rt;

  useEffect(() => {
    const handler = () => {
      if (hidden) return; // the home screen and /chat already are the agent
      connect();
      if (!window.matchMedia(DESKTOP_QUERY).matches) {
        router.push("/chat");
        return;
      }
      setOpen(true);
    };
    window.addEventListener(OPEN_AGENT_EVENT, handler);
    return () => window.removeEventListener(OPEN_AGENT_EVENT, handler);
  }, [connect, hidden, router]);

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
      {!open && !hidden && (
        <button
          type="button"
          aria-label="Talk to BharatBench"
          onClick={() => window.dispatchEvent(new CustomEvent(OPEN_AGENT_EVENT))}
          className="fixed right-4 bottom-4 z-40 flex size-14 items-center justify-center rounded-full border border-border bg-card shadow-[0_8px_24px_rgba(124,92,255,0.22)] transition-transform hover:scale-105 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none md:right-8 md:bottom-8"
        >
          <Orb state={rt.orbState} size="sm" getLevel={rt.getLevel} />
        </button>
      )}

      <Sheet open={open && !hidden} onOpenChange={onOpenChange}>
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
                {LANGUAGE_OPTIONS.map((l) => (
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
            <Thread items={rt.transcript} jobs={rt.jobs} />
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
