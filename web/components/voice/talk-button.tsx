"use client";

import { AudioLines } from "lucide-react";
import { openAgentPanel } from "./agent-events";

/** Header entry point to the voice/text agent: opens the conversation panel on the right. */
export function TalkButton() {
  return (
    <button
      type="button"
      onClick={openAgentPanel}
      className="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-[0_4px_14px_rgba(124,92,255,0.3)] transition-transform hover:scale-[1.03] focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <AudioLines className="size-3.5" aria-hidden />
      <span className="max-sm:sr-only">Talk to agent</span>
    </button>
  );
}
