"use client";

/** Expanding ring at a tap point (percent coordinates inside the screen). Remount with a new `key` to replay. */
export function TapRipple({ xPct, yPct }: { xPct: number; yPct: number }) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute z-20"
      style={{ left: `${xPct}%`, top: `${yPct}%` }}
    >
      <style>{`
        @keyframes bb-ripple { 0% { transform: translate(-50%,-50%) scale(.25); opacity: .95 } 70% { opacity: .55 } 100% { transform: translate(-50%,-50%) scale(1.6); opacity: 0 } }
        @keyframes bb-dot { 0% { transform: translate(-50%,-50%) scale(.5); opacity: 0 } 20% { opacity: 1 } 100% { transform: translate(-50%,-50%) scale(1); opacity: 0 } }
        @media (prefers-reduced-motion: reduce) { .bb-ripple, .bb-dot { animation-duration: 1ms !important } }
      `}</style>
      <span
        className="bb-ripple absolute block size-16 rounded-full border-2 border-primary bg-primary/25"
        style={{ animation: "bb-ripple 900ms ease-out forwards" }}
      />
      <span
        className="bb-dot absolute block size-4 rounded-full bg-primary shadow-[0_0_0_3px_rgba(255,255,255,0.8)]"
        style={{ animation: "bb-dot 1100ms ease-out forwards" }}
      />
    </span>
  );
}
