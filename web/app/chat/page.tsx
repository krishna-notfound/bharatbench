"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Mic, MicOff, RotateCcw, SendHorizontal, WifiOff } from "lucide-react";
import { Orb, ORB_LABEL } from "@/components/orb/orb";
import { Thread, MessageBubble } from "@/components/voice/chat-parts";
import { useAgent } from "@/components/voice/realtime-provider";
import { Button } from "@/components/ui/button";
import { API_URL } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";
import type { Message } from "@/lib/realtime/useRealtime";
import { cn } from "@/lib/utils";

const CONVERSATION_KEY = "bb.agent.conversation.v1";

interface HistoryRow {
  role: "user" | "assistant" | "tool";
  content: string;
  interrupted: boolean;
}

/** Earlier messages of the stored conversation (signed-in users only); empty on any failure. */
async function loadHistory(): Promise<Message[]> {
  let id: string | null = null;
  try {
    id = window.localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return [];
  }
  const token = await getAccessToken();
  if (!id || !token) return [];
  try {
    const res = await fetch(`${API_URL}/api/conversations/${encodeURIComponent(id)}/messages`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return [];
    const rows = (await res.json()) as HistoryRow[];
    return rows
      .filter((r) => r.role !== "tool" && r.content)
      .map((r, i) => ({ id: `h${i}`, role: r.role as "user" | "assistant", text: r.content, interrupted: r.interrupted }));
  } catch {
    return [];
  }
}

function ChatView() {
  const rt = useAgent();
  const params = useSearchParams();
  const runParam = params.get("run");
  const customTests = params.get("intent") === "custom-tests";
  const askedRun = useRef<string | null>(null);
  const { connect, connected } = rt;
  const [draft, setDraft] = useState("");
  const [history, setHistory] = useState<Message[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const startedEmpty = useRef(rt.transcript.length === 0);

  useEffect(() => {
    connect();
    if (startedEmpty.current) {
      let alive = true;
      void loadHistory().then((h) => alive && setHistory(h));
      return () => {
        alive = false;
      };
    }
  }, [connect]);

  // /chat?run=<id>: open the conversation about that run with a first message.
  useEffect(() => {
    if (runParam && connected && askedRun.current !== runParam) {
      askedRun.current = runParam;
      rt.sendText(
        customTests
          ? `I want new tests for run ${runParam}. Ask me: "What should I test in <the app's name>? Describe it and I'll write the tests." Then use write_custom_tests with my answer.`
          : `Tell me about run ${runParam}`,
      );
    }
  }, [runParam, customTests, connected, rt]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [rt.transcript, rt.jobs, history]);

  const offline = rt.state === "offline";
  const label = offline ? "Voice service unavailable" : rt.state === "connecting" ? "Connecting…" : ORB_LABEL[rt.orbState];

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    rt.sendText(draft);
    setDraft("");
  };

  return (
    <div className="mx-auto flex h-[calc(100dvh-5.5rem)] w-full max-w-2xl flex-col">
      <div className="flex items-center gap-3 border-b border-border pb-3">
        <Link
          href="/"
          aria-label="Back to voice"
          className="flex size-9 items-center justify-center rounded-full border border-border bg-card hover:bg-accent"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <Orb state={rt.orbState} size="sm" getLevel={rt.getLevel} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">BharatBench</p>
          <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
            {label}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-8 rounded-full px-3"
          onClick={() => {
            setHistory([]);
            rt.newConversation();
          }}
          disabled={rt.transcript.length === 0 && history.length === 0}
        >
          <RotateCcw /> New
        </Button>
      </div>

      <div ref={listRef} className="flex flex-1 flex-col gap-2.5 overflow-y-auto py-4" aria-live="polite">
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
        {!offline && rt.transcript.length === 0 && history.length === 0 && (
          <p className="my-auto text-center text-sm text-muted-foreground">
            Ask in Hindi, English or Hinglish. Try &quot;show my recent sessions&quot; or &quot;test my app on a slow
            network&quot;.
          </p>
        )}
        {history.map((m) => (
          <MessageBubble key={m.id} item={m} />
        ))}
        <Thread items={rt.transcript} jobs={rt.jobs} onAsk={rt.sendText} />
      </div>

      {rt.error && !offline && (
        <p className="pb-1 text-xs text-destructive" role="alert">
          {rt.error}
        </p>
      )}

      <form onSubmit={submit} className={cn("flex items-center gap-2 rounded-full border border-border bg-card p-2")}>
        <Button
          type="button"
          size="icon-lg"
          variant={rt.micOn ? "default" : "outline"}
          className="size-10 rounded-full"
          aria-label={rt.micOn ? "Stop microphone" : "Start microphone"}
          aria-pressed={rt.micOn}
          disabled={!connected}
          onClick={() => void rt.toggleMic()}
        >
          {rt.micOn ? <Mic /> : <MicOff />}
        </Button>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={connected ? "Type a message" : "Connecting…"}
          aria-label="Message"
          disabled={!connected}
          className="h-10 min-w-0 flex-1 bg-transparent px-2 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
        <Button
          type="submit"
          size="icon-lg"
          className="size-10 rounded-full"
          aria-label="Send message"
          disabled={!connected || !draft.trim()}
        >
          <SendHorizontal />
        </Button>
      </form>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatView />
    </Suspense>
  );
}
