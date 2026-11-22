"use client";

import { useState } from "react";
import { Check, Copy, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { getFindingFixPrompt, getFixPrompt } from "@/lib/api";

const COPIED = "Prompt copied — paste it into Claude Code, Cursor or Copilot";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(COPIED);
    return true;
  } catch {
    toast.error("Could not copy. Open the preview and select the text instead.");
    return false;
  }
}

/** Fetches the prompt from the API (built from this run's real data) on demand, then copies it. */
function usePrompt(load: () => Promise<string>) {
  const [prompt, setPrompt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function ensure(): Promise<string | null> {
    if (prompt) return prompt;
    setBusy(true);
    try {
      const p = await load();
      setPrompt(p);
      return p;
    } catch {
      toast.error("Could not build the prompt. Please try again.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    const p = await ensure();
    if (p && (await copyText(p))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  }

  return { prompt, busy, copied, ensure, copy };
}

export function FixWithAiBlock({ runId, findingId }: { runId: string; findingId: string }) {
  const { prompt, busy, copied, ensure, copy } = usePrompt(
    async () => (await getFindingFixPrompt(runId, findingId)).prompt,
  );
  return (
    <section className="space-y-3 rounded-2xl border border-primary/30 bg-accent p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Sparkles className="size-4" />
        </span>
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-semibold text-accent-foreground">Fix with AI</h3>
          <p className="text-xs leading-relaxed text-muted-foreground">
            A ready-made prompt with the evidence, the fix, acceptance criteria and how to re-test. Paste it into your
            AI coding assistant inside your app&apos;s repo.
          </p>
        </div>
      </div>
      <Button onClick={() => void copy()} disabled={busy} className="h-10 w-full rounded-full">
        {copied ? <Check /> : <Copy />} {copied ? "Copied" : busy ? "Preparing…" : "Copy prompt for your AI assistant"}
      </Button>
      <details
        className="rounded-xl bg-background/60 px-3 py-2"
        onToggle={(e) => {
          if ((e.currentTarget as HTMLDetailsElement).open) void ensure();
        }}
      >
        <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Preview the prompt</summary>
        <pre className="mt-2 max-h-72 overflow-auto rounded-xl bg-muted p-3 font-mono text-xs break-words whitespace-pre-wrap">
          {prompt ?? "Loading…"}
        </pre>
      </details>
    </section>
  );
}

export function FixEverythingCard({ runId, count }: { runId: string; count: number }) {
  const { busy, copied, copy } = usePrompt(async () => (await getFixPrompt(runId)).prompt);
  if (count === 0) return null;
  return (
    <section className="flex flex-col gap-4 rounded-3xl border border-border bg-card p-6 shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)] sm:flex-row sm:items-center sm:justify-between md:p-8">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Sparkles className="size-5" />
        </span>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">Fix everything with AI</h2>
          <p className="text-sm text-muted-foreground">
            {count} {count === 1 ? "issue" : "issues"} in one prompt, ranked by impact. Paste it into your AI coding
            assistant inside your app&apos;s repo, then re-run the test here.
          </p>
        </div>
      </div>
      <Button onClick={() => void copy()} disabled={busy} className="h-10 shrink-0 rounded-full px-5">
        {copied ? <Check /> : <Copy />} {copied ? "Copied" : busy ? "Preparing…" : "Copy full fix prompt"}
      </Button>
    </section>
  );
}
