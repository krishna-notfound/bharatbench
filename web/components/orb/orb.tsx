"use client";

import { cn } from "@/lib/utils";
import type { RunStatus } from "@/lib/types";

/**
 * Agent states. Every state is driven by a real event:
 * voice session state (idle/listening/thinking/speaking) or run status (orbStateFromRun).
 */
export type OrbState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "inspecting"
  | "building"
  | "starting_emulator"
  | "testing"
  | "analysing"
  | "completed"
  | "error";

export const ORB_LABEL: Record<OrbState, string> = {
  idle: "Ready when you are",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking",
  inspecting: "Inspecting your app",
  building: "Building APK",
  starting_emulator: "Starting the emulator",
  testing: "Running tests",
  analysing: "Analysing failures",
  completed: "Test complete",
  error: "Something went wrong",
};

/** Map a real run status to an orb state. */
export function orbStateFromRun(status: RunStatus): OrbState {
  switch (status) {
    case "queued":
    case "analyzing":
      return "inspecting";
    case "provisioning":
      return "starting_emulator";
    case "running":
      return "testing";
    case "scoring":
      return "analysing";
    case "done":
      return "completed";
    case "failed":
      return "error";
    case "cancelled":
      return "idle";
  }
}

const MOTION: Record<OrbState, string> = {
  idle: "animate-[orb-breathe_5s_ease-in-out_infinite]",
  listening: "animate-[orb-listen_1.4s_ease-out_infinite]",
  thinking: "animate-[orb-breathe_1.6s_ease-in-out_infinite]",
  speaking: "animate-[orb-pulse_0.9s_ease-in-out_infinite]",
  inspecting: "animate-[orb-breathe_2.4s_ease-in-out_infinite]",
  building: "animate-[orb-breathe_2s_ease-in-out_infinite]",
  starting_emulator: "animate-[orb-breathe_2s_ease-in-out_infinite]",
  testing: "animate-[orb-breathe_1.8s_ease-in-out_infinite]",
  analysing: "animate-[orb-breathe_1.6s_ease-in-out_infinite]",
  completed: "",
  error: "animate-[orb-shake_0.4s_ease-in-out_2]",
};

const SWIRL_SPEED: Partial<Record<OrbState, string>> = {
  thinking: "animate-[orb-spin_2.5s_linear_infinite]",
  inspecting: "animate-[orb-spin_6s_linear_infinite]",
  building: "animate-[orb-spin_4s_linear_infinite]",
  starting_emulator: "animate-[orb-spin_4s_linear_infinite]",
  testing: "animate-[orb-spin_3s_linear_infinite]",
  analysing: "animate-[orb-spin_2.5s_linear_infinite]",
  idle: "animate-[orb-spin_18s_linear_infinite]",
  listening: "animate-[orb-spin_10s_linear_infinite]",
  speaking: "animate-[orb-spin_8s_linear_infinite]",
};

const SIZES = { sm: "size-10", md: "size-24", lg: "size-44", xl: "size-56" } as const;

export function Orb({
  state = "idle",
  size = "lg",
  className,
  showLabel = false,
}: {
  state?: OrbState;
  size?: keyof typeof SIZES;
  className?: string;
  showLabel?: boolean;
}) {
  const isError = state === "error";
  const isDone = state === "completed";
  return (
    <div className={cn("orb flex flex-col items-center gap-4", className)} data-state={state}>
      <div className={cn("relative rounded-full", SIZES[size], MOTION[state])} aria-hidden>
        {/* glow */}
        <div
          className="absolute -inset-[18%] rounded-full opacity-80 blur-2xl"
          style={{
            background: isError
              ? "radial-gradient(circle, color-mix(in oklab, var(--destructive) 35%, transparent), transparent 70%)"
              : "radial-gradient(circle, var(--orb-glow), transparent 70%)",
          }}
        />
        {/* body */}
        <div
          className="absolute inset-0 overflow-hidden rounded-full shadow-[inset_0_-8px_24px_rgba(124,92,255,0.25),0_10px_30px_rgba(124,92,255,0.18)]"
          style={{
            background: isError
              ? "radial-gradient(circle at 35% 30%, #ffffff, #fecdd3 45%, #fda4af)"
              : isDone
                ? "radial-gradient(circle at 35% 30%, #ffffff, #c7f9e1 40%, var(--orb-a) 85%)"
                : "radial-gradient(circle at 35% 30%, #ffffff, var(--orb-a) 45%, var(--orb-c) 90%)",
          }}
        >
          <div
            className={cn("absolute -inset-1/4 opacity-70 mix-blend-multiply", SWIRL_SPEED[state])}
            style={{
              background:
                "conic-gradient(from 0deg, transparent 0 20%, var(--orb-b) 30%, transparent 45% 65%, var(--orb-c) 75%, transparent 90%)",
              filter: "blur(10px)",
            }}
          />
          {/* highlight */}
          <div className="absolute top-[14%] left-[22%] h-[22%] w-[30%] rotate-[-20deg] rounded-full bg-white/70 blur-[6px]" />
          {/* face: two soft eyes give it personality; they squint when listening/done, flatten on error */}
          <div className="absolute inset-0 flex items-center justify-center gap-[16%] pt-[8%]">
            {[0, 1].map((i) => (
              <span
                key={i}
                className={cn(
                  "block w-[7%] rounded-full bg-foreground/70 transition-all duration-300",
                  state === "listening" || isDone ? "h-[5%]" : isError ? "h-[3%]" : "h-[14%]",
                )}
              />
            ))}
          </div>
        </div>
      </div>
      {showLabel && (
        <p className="text-sm font-medium text-muted-foreground" role="status" aria-live="polite">
          {ORB_LABEL[state]}
        </p>
      )}
    </div>
  );
}
