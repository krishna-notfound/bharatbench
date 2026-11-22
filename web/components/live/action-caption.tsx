"use client";

/** Chip floating under the phone's notch describing what the agent is doing. Remount (key) to re-animate. */
export function ActionCaption({ text, warn = false }: { text: string; warn?: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-9 z-20 flex justify-center px-3" aria-live="polite">
      <style>{`
        @keyframes bb-chip { 0% { transform: translateY(-8px) scale(.92); opacity: 0 } 100% { transform: none; opacity: 1 } }
      `}</style>
      <span
        className={`max-w-full truncate rounded-full px-3 py-1 text-[11px] font-medium shadow-lg backdrop-blur ${
          warn ? "bg-destructive/90 text-white" : "bg-foreground/85 text-background"
        }`}
        style={{ animation: "bb-chip 260ms cubic-bezier(.2,.9,.3,1.3) both" }}
      >
        {text}
      </span>
    </div>
  );
}
