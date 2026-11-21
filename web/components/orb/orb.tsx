"use client";

import { useEffect, useRef } from "react";
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
  speaking: "",
  inspecting: "animate-[orb-breathe_2.4s_ease-in-out_infinite]",
  building: "animate-[orb-breathe_2s_ease-in-out_infinite]",
  starting_emulator: "animate-[orb-breathe_2s_ease-in-out_infinite]",
  testing: "animate-[orb-breathe_1.8s_ease-in-out_infinite]",
  analysing: "animate-[orb-breathe_1.6s_ease-in-out_infinite]",
  completed: "",
  error: "animate-[orb-shake_0.4s_ease-in-out_2]",
};

const WORKING: ReadonlySet<OrbState> = new Set([
  "inspecting",
  "building",
  "starting_emulator",
  "testing",
  "analysing",
]);

const SIZES = { sm: "size-10", md: "size-24", lg: "size-44", xl: "size-56 md:size-64" } as const;

// Mouth paths in a 100x100 viewBox (centre x = 50).
const MOUTH: Record<OrbState, string> = {
  idle: "M42 63 Q50 70 58 63",
  listening: "M44 64 Q50 68 56 64",
  thinking: "M45 65 L55 65",
  speaking: "M42 63 Q50 70 58 63",
  inspecting: "M44 65 Q50 67 56 65",
  building: "M44 65 Q50 67 56 65",
  starting_emulator: "M44 65 Q50 67 56 65",
  testing: "M44 65 Q50 67 56 65",
  analysing: "M44 65 Q50 67 56 65",
  completed: "M38 62 Q50 76 62 62",
  error: "M42 68 Q50 62 58 68",
};

/** Mouth for the speaking state; `open` 0..1 follows the output level. */
function speakingMouth(open: number) {
  const w = 7 + open * 2;
  const h = 3 + open * 11;
  return `M${50 - w} 63 Q50 ${63 + h * 1.35} ${50 + w} 63 Q50 64 ${50 - w} 63 Z`;
}

/** Where the eyes look per state (offset in viewBox units). */
const GAZE: Partial<Record<OrbState, [number, number]>> = {
  thinking: [3, -3.5],
  inspecting: [-2.5, 1],
  analysing: [2.5, 1],
};

export function Orb({
  state = "idle",
  size = "lg",
  className,
  showLabel = false,
  getLevel,
}: {
  state?: OrbState;
  size?: keyof typeof SIZES;
  className?: string;
  showLabel?: boolean;
  /** Returns 0..1 (mic or output level). Read every frame; never causes a React render. */
  getLevel?: () => number;
}) {
  const isError = state === "error";
  const isDone = state === "completed";
  const isWorking = WORKING.has(state);

  const bodyRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<SVGCircleElement>(null);
  const eyesRef = useRef<SVGGElement>(null);
  const mouthRef = useRef<SVGPathElement>(null);
  const levelRef = useRef(getLevel);
  const stateRef = useRef(state);
  useEffect(() => {
    levelRef.current = getLevel;
    stateRef.current = state;
  });

  useEffect(() => {
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let smooth = 0;
    let nextBlink = performance.now() + 1800 + Math.random() * 2500;
    let blinkEnd = 0;
    const tick = (now: number) => {
      const st = stateRef.current;
      const raw = levelRef.current?.() ?? 0;
      const target = Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : 0;
      smooth += (target - smooth) * 0.25;
      if (!reduced) {
        if (bodyRef.current) bodyRef.current.style.transform = `scale(${1 + smooth * 0.08})`;
        const ring = ringRef.current;
        if (ring) {
          ring.style.strokeWidth = String(2.2 + smooth * 3);
          ring.style.opacity = String(0.55 + Math.min(1, smooth * 1.6) * 0.45);
        }
        if (now > nextBlink) {
          blinkEnd = now + 140;
          nextBlink = now + 2600 + Math.random() * 3800;
        }
        if (eyesRef.current) {
          eyesRef.current.style.transform = `scaleY(${now < blinkEnd ? 0.1 : 1})`;
        }
      }
      if (st === "speaking" && mouthRef.current) {
        const open = reduced
          ? 0.5
          : target > 0.02
            ? smooth
            : 0.35 + 0.35 * Math.sin(now / 130);
        mouthRef.current.setAttribute("d", speakingMouth(open));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const gaze = GAZE[state] ?? [0, 0];
  const eyeRy = state === "listening" ? 9.4 : isWorking ? 7 : 8.4;
  const ink = "var(--orb-ink)";

  return (
    <div className={cn("orb flex flex-col items-center gap-4", className)} data-state={state}>
      <div className={cn("relative rounded-full", SIZES[size], MOTION[state])} aria-hidden>
        {/* soft sage glow */}
        <div
          className="absolute -inset-[14%] rounded-full opacity-90 blur-2xl"
          style={{
            background: isError
              ? "radial-gradient(circle, color-mix(in oklab, var(--destructive) 30%, transparent), transparent 70%)"
              : "radial-gradient(circle, var(--orb-ring-glow), transparent 70%)",
          }}
        />
        {/* body */}
        <div
          ref={bodyRef}
          className="absolute inset-[7%] overflow-hidden rounded-full will-change-transform"
          style={{
            background: isError
              ? "radial-gradient(circle at 35% 30%, #ffffff, #fecdd3 45%, #fda4af)"
              : "radial-gradient(circle at 35% 30%, var(--orb-hi) 0%, var(--orb-a) 45%, var(--orb-lo) 85%, var(--orb-deep) 100%)",
            boxShadow:
              "inset -6px -8px 22px rgba(76,60,125,0.35), inset 6px 6px 18px rgba(255,255,255,0.75), 0 8px 24px rgba(124,92,255,0.22)",
          }}
        >
          {(isWorking || state === "thinking") && (
            <div
              className={cn(
                "absolute -inset-1/4 opacity-60 mix-blend-overlay",
                state === "thinking"
                  ? "animate-[orb-spin_2.4s_linear_infinite]"
                  : "animate-[orb-spin_4s_linear_infinite]",
              )}
              style={{
                background:
                  "conic-gradient(from 0deg, transparent 0 55%, rgba(255,255,255,0.95) 78%, transparent 100%)",
              }}
            />
          )}
          {/* glossy highlight */}
          <div className="absolute top-[10%] left-[16%] h-[20%] w-[40%] -rotate-[25deg] rounded-full bg-white/75 blur-[3px]" />
        </div>
        {/* ring */}
        <svg className="absolute inset-0 size-full" viewBox="0 0 100 100">
          <circle
            ref={ringRef}
            cx="50"
            cy="50"
            r="47"
            fill="none"
            stroke={isError ? "var(--destructive)" : "var(--orb-ring)"}
            strokeLinecap="round"
            style={{ strokeWidth: 2.2, opacity: 0.55 }}
          />
        </svg>
        {/* face */}
        <svg className="absolute inset-0 size-full" viewBox="0 0 100 100">
          {isError && (
            <g stroke={ink} strokeWidth="1.8" strokeLinecap="round" fill="none">
              <path d="M32 36 L45 39" />
              <path d="M68 36 L55 39" />
            </g>
          )}
          {isDone ? (
            <g stroke={ink} strokeWidth="3" strokeLinecap="round" fill="none">
              <path d="M33 49 Q40 41 47 49" />
              <path d="M53 49 Q60 41 67 49" />
            </g>
          ) : (
            <g
              ref={eyesRef}
              style={{ transformOrigin: "50px 48px", transition: "transform 90ms ease-out" }}
            >
              {[40, 60].map((cx) => (
                <g
                  key={cx}
                  style={{
                    transform: `translate(${gaze[0]}px, ${gaze[1]}px)`,
                    transition: "transform 300ms ease-out",
                  }}
                >
                  <ellipse cx={cx} cy={48} rx={6.4} ry={eyeRy} fill={ink} />
                  <circle cx={cx - 2.2} cy={48 - eyeRy * 0.42} r={2.4} fill="#fff" />
                  <circle cx={cx + 1.8} cy={48 + eyeRy * 0.4} r={0.9} fill="#fff" opacity={0.8} />
                </g>
              ))}
            </g>
          )}
          <path
            ref={mouthRef}
            d={state === "speaking" ? speakingMouth(0.4) : MOUTH[state]}
            stroke={ink}
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill={state === "speaking" ? ink : "none"}
          />
        </svg>
      </div>
      {showLabel && (
        <p className="text-sm font-medium text-muted-foreground" role="status" aria-live="polite">
          {ORB_LABEL[state]}
        </p>
      )}
    </div>
  );
}
