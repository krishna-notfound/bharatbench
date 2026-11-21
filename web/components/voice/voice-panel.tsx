"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, SendHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useVoiceSession, type VoiceLanguage, type VoiceState } from "./use-voice-session";

const STATE_LABEL: Record<VoiceState, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

const STATE_STYLE: Record<VoiceState, string> = {
  idle: "bg-muted text-muted-foreground",
  listening: "bg-success/15 text-success",
  thinking: "bg-accent-info/15 text-accent-info",
  speaking: "bg-primary/15 text-primary",
};

const LANGUAGES: { value: VoiceLanguage; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "hi-IN", label: "हिन्दी" },
  { value: "en-IN", label: "English" },
];

export function VoicePanel() {
  const voice = useVoiceSession();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [voice.transcript]);

  const openPanel = () => {
    setOpen(true);
    voice.connect();
  };
  const closePanel = () => {
    setOpen(false);
    voice.disconnect();
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    voice.sendText(draft);
    setDraft("");
  };

  if (!open) {
    return (
      <Button
        size="icon-lg"
        className="fixed right-4 bottom-4 z-50 size-12 rounded-full shadow-lg md:right-8 md:bottom-8"
        aria-label="Open voice assistant"
        onClick={openPanel}
      >
        <Mic className="size-5" />
      </Button>
    );
  }

  return (
    <section
      aria-label="Voice assistant"
      className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80dvh] flex-col rounded-t-2xl border border-border bg-card shadow-lg md:inset-x-auto md:right-8 md:bottom-8 md:w-96 md:rounded-2xl"
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span
          className={cn("rounded-md px-2 py-0.5 text-xs font-medium", STATE_STYLE[voice.state])}
          role="status"
        >
          {STATE_LABEL[voice.state]}
        </span>
        <select
          aria-label="Language"
          value={voice.language}
          onChange={(e) => voice.setLanguage(e.target.value as VoiceLanguage)}
          className="h-7 rounded-md border border-border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-1">
          <Button
            size="icon-sm"
            variant={voice.micOn ? "default" : "outline"}
            aria-label={voice.micOn ? "Stop microphone" : "Start microphone"}
            aria-pressed={voice.micOn}
            disabled={!voice.connected}
            onClick={() => void voice.toggleMic()}
          >
            {voice.micOn ? <Mic /> : <MicOff />}
          </Button>
          <Button size="icon-sm" variant="ghost" aria-label="Close voice assistant" onClick={closePanel}>
            <X />
          </Button>
        </div>
      </header>

      <div
        ref={listRef}
        className="flex min-h-40 flex-1 flex-col gap-2 overflow-y-auto px-3 py-3"
        aria-live="polite"
      >
        {voice.transcript.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Ask in Hindi, English or Hinglish: &quot;list my runs&quot;, &quot;test my app on slow network&quot;.
          </p>
        )}
        {voice.transcript.map((item) => (
          <div
            key={item.id}
            className={cn(
              "max-w-[85%] rounded-md px-2.5 py-1.5 text-sm",
              item.role === "user" && "self-end bg-primary text-primary-foreground",
              item.role === "assistant" && "self-start bg-muted text-foreground",
              item.role === "tool" && "self-start font-mono text-xs text-muted-foreground",
              item.role === "system" && "self-center text-xs text-accent-info",
            )}
          >
            {item.text}
          </div>
        ))}
      </div>

      {voice.error && (
        <p className="border-t border-border px-3 py-1.5 text-xs text-destructive" role="alert">
          {voice.error}
        </p>
      )}

      <form onSubmit={submit} className="flex items-center gap-2 border-t border-border p-3">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type a message"
          aria-label="Message"
          disabled={!voice.connected}
        />
        <Button type="submit" size="icon" aria-label="Send message" disabled={!voice.connected || !draft.trim()}>
          <SendHorizontal />
        </Button>
      </form>
    </section>
  );
}
