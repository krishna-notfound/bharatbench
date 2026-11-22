"use client";

import { useEffect, useState } from "react";
import { ChevronsRight, Smartphone } from "lucide-react";
import { ActionCaption } from "@/components/live/action-caption";
import { TapRipple } from "@/components/live/tap-ripple";
import { captionFor, liveFrameUrl, profileLabel, useLive } from "@/lib/live";

export interface PhoneRipple {
  key: string;
  xPct: number;
  yPct: number;
}

/** A phone: rounded bezel, notch, lavender glow. The screen shows `src` with optional ripple + caption. */
export function PhoneFrame({
  src,
  aspect = 9 / 19.5,
  width = 232,
  ripple,
  caption,
  warn,
  badge,
  step,
  empty = "Waiting for the phone…",
}: {
  src: string | null;
  aspect?: number;
  width?: number;
  ripple?: PhoneRipple | null;
  caption?: string | null;
  warn?: boolean;
  badge?: string | null;
  step?: string | null;
  empty?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex items-center gap-2 text-[11px] font-medium">
        {badge && <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-primary">{badge}</span>}
        {step && <span className="rounded-full bg-muted px-2.5 py-0.5 text-muted-foreground tabular-nums">{step}</span>}
      </div>
      <div
        className="relative rounded-[2.4rem] border-[7px] border-[#1e1b2e] bg-[#1e1b2e] shadow-[0_24px_60px_-12px_rgba(124,92,255,0.45),0_6px_16px_rgba(30,27,46,0.25)]"
        style={{ width }}
      >
        <div className="absolute top-1.5 left-1/2 z-30 h-4 w-16 -translate-x-1/2 rounded-full bg-[#1e1b2e]" aria-hidden />
        <div className="relative overflow-hidden rounded-[1.8rem] bg-[#0f0d1a]" style={{ aspectRatio: String(aspect) }}>
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element -- live frames change every second; next/image would add nothing
            <img src={src} alt="The test phone's screen" className="size-full object-cover" draggable={false} />
          ) : (
            <div className="flex size-full items-center justify-center p-6 text-center text-xs text-white/60">{empty}</div>
          )}
          {ripple && <TapRipple key={ripple.key} xPct={ripple.xPct} yPct={ripple.yPct} />}
          {caption && <ActionCaption key={caption} text={caption} warn={warn} />}
        </div>
      </div>
    </div>
  );
}

/**
 * The live phone. Slides in from the right (bottom sheet on mobile) while a test runs;
 * minimizes to a small floating phone and reopens.
 */
export function LivePhone({ runId, active }: { runId: string; active: boolean }) {
  const live = useLive(runId, active);
  const [entered, setEntered] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [shown, setShown] = useState<string | null>(null);

  useEffect(() => {
    const a = requestAnimationFrame(() => requestAnimationFrame(() => setEntered(true)));
    return () => cancelAnimationFrame(a);
  }, []);

  // Preload each new frame so the screen never flashes blank between updates.
  const seq = live?.seq ?? 0;
  const hasFrame = !!live?.has_frame;
  useEffect(() => {
    if (!hasFrame) return;
    const url = liveFrameUrl(runId, seq);
    const img = new Image();
    let cancelled = false;
    img.onload = () => {
      if (!cancelled) setShown(url);
    };
    img.src = url;
    return () => {
      cancelled = true;
    };
  }, [runId, seq, hasFrame]);

  const screen = live?.screen ?? null;
  const aspect = screen ? screen.w / screen.h : 9 / 19.5;
  const stepKey = live?.step_index != null ? `${live.profile_id}-${live.step_index}` : null;
  const tap = live?.tap && screen ? live.tap : null;
  const ripple: PhoneRipple | null =
    tap && screen && stepKey
      ? { key: stepKey, xPct: (tap.x / screen.w) * 100, yPct: (tap.y / screen.h) * 100 }
      : null;
  const caption = live?.running === false && !shown ? null : captionFor(live?.action, live?.target);
  const badge = live?.profile_id ? profileLabel(live.profile_id) : null;
  const stepText = live?.step_index != null ? `Step ${live.step_index + 1}` : null;
  const empty = live && !live.running && live.reason ? live.reason : "Waiting for the test phone…";

  return (
    <>
      {minimized && (
        <button
          type="button"
          onClick={() => setMinimized(false)}
          aria-label="Open the live phone"
          className="fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full border border-border bg-card py-2 pr-4 pl-2 shadow-[0_8px_24px_rgba(124,92,255,0.25)] transition-transform hover:scale-105 motion-reduce:transition-none"
        >
          <span className="relative flex h-12 w-7 items-center justify-center overflow-hidden rounded-lg border-2 border-[#1e1b2e] bg-[#0f0d1a]">
            {shown ? (
              // eslint-disable-next-line @next/next/no-img-element -- tiny live thumbnail
              <img src={shown} alt="" className="size-full object-cover" />
            ) : (
              <Smartphone className="size-4 text-white/60" />
            )}
            <span className="absolute top-0.5 right-0.5 size-1.5 animate-pulse rounded-full bg-emerald-400" />
          </span>
          <span className="text-xs font-medium">Live phone</span>
        </button>
      )}
      <aside
        aria-label="Live test phone"
        aria-hidden={minimized}
        data-live-open={entered && !minimized ? "true" : "false"}
        className={`fixed z-40 transition-[transform,opacity] duration-[650ms] ease-[cubic-bezier(0.34,1.4,0.5,1)] motion-reduce:transition-none max-md:inset-x-0 max-md:bottom-0 max-md:rounded-t-3xl max-md:border-t max-md:border-border max-md:bg-card/95 max-md:pt-3 max-md:pb-4 max-md:shadow-[0_-12px_40px_rgba(124,92,255,0.25)] max-md:backdrop-blur md:top-24 md:right-4 ${
          entered && !minimized
            ? "translate-x-0 translate-y-0 opacity-100"
            : "pointer-events-none opacity-0 max-md:translate-y-full md:translate-x-[125%]"
        }`}
      >
        <div className="flex flex-col items-center gap-2 px-3">
          <div className="flex w-full items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" /> Live from the test phone
            </span>
            <button
              type="button"
              onClick={() => setMinimized(true)}
              aria-label="Minimize the live phone"
              className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <ChevronsRight className="size-4 max-md:rotate-90" />
            </button>
          </div>
          <div className="max-md:[&>div>div:nth-child(2)]:!w-40">
            <PhoneFrame
              src={shown}
              aspect={aspect}
              ripple={ripple}
              caption={caption}
              badge={badge}
              step={stepText}
              empty={empty}
            />
          </div>
        </div>
      </aside>
    </>
  );
}
