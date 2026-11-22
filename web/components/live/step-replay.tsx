"use client";

import { useState } from "react";
import { PhoneFrame, type PhoneRipple } from "@/components/live/live-phone";
import { useFetch } from "@/components/shell/use-fetch";
import { artifactUrl } from "@/lib/api";
import { captionFor, getReplay, profileLabel, type ReplayProfile } from "@/lib/live";

/** Playwright-trace style replay: a filmstrip of steps; picking one shows its screenshot, action and tap point. */
export function StepReplay({ runId }: { runId: string }) {
  const replay = useFetch(() => getReplay(runId));
  const profiles = (replay.data?.profiles ?? []).filter((p) => p.steps.length > 0);
  const [pid, setPid] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  if (profiles.length === 0) return null;
  const prof: ReplayProfile = profiles.find((p) => p.profile_id === pid) ?? profiles[0];
  const step = prof.steps[Math.min(sel, prof.steps.length - 1)];
  const screen = prof.screen;
  const ripple: PhoneRipple | null =
    step.x != null && step.y != null && screen
      ? { key: `${prof.profile_id}-${step.index}`, xPct: (step.x / screen.w) * 100, yPct: (step.y / screen.h) * 100 }
      : null;
  const caption = captionFor(step.action, step.target);

  return (
    <section
      id="replay"
      aria-label="Step replay"
      className="space-y-5 rounded-3xl border border-border bg-card p-6 shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)] md:p-8"
    >
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">Replay the test</h2>
        <p className="text-sm text-muted-foreground">Step through what I did on the phone. Pick a step to see its screen.</p>
      </div>
      {profiles.length > 1 && (
        <div role="tablist" className="flex flex-wrap gap-2">
          {profiles.map((p) => (
            <button
              key={p.profile_id}
              role="tab"
              aria-selected={p.profile_id === prof.profile_id}
              onClick={() => {
                setPid(p.profile_id);
                setSel(0);
              }}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                p.profile_id === prof.profile_id
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {profileLabel(p.profile_id)}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-col items-center gap-6 md:flex-row md:items-start md:gap-10">
        <PhoneFrame
          src={step.screenshot ? artifactUrl(runId, step.screenshot) : null}
          aspect={screen ? screen.w / screen.h : 9 / 19.5}
          ripple={ripple}
          caption={caption}
          warn={!step.ok}
          badge={profileLabel(prof.profile_id)}
          step={`Step ${step.index + 1} of ${prof.steps.length}`}
          empty="No screenshot for this step"
        />
        <div className="min-w-0 flex-1 space-y-4">
          <div className="space-y-1 text-sm">
            <p className="font-medium">{caption ?? step.action}</p>
            {step.note && <p className="text-muted-foreground">{step.note}</p>}
            <p className="text-xs text-muted-foreground tabular-nums">
              {step.ok ? "Worked" : "Did not work"}
              {step.duration_ms != null ? ` · ${step.duration_ms} ms` : ""}
              {step.x != null && step.y != null ? ` · tap at ${step.x}, ${step.y}` : ""}
            </p>
          </div>
          <ol className="flex gap-3 overflow-x-auto pb-2" aria-label="Steps">
            {prof.steps.map((s, i) => (
              <li key={s.index} className="shrink-0">
                <button
                  onClick={() => setSel(i)}
                  aria-current={i === sel}
                  aria-label={`Step ${s.index + 1}: ${captionFor(s.action, s.target) ?? s.action}`}
                  className={`flex w-20 flex-col gap-1 rounded-xl border p-1 text-left transition-all motion-reduce:transition-none ${
                    i === sel ? "border-primary bg-primary/5 shadow-md" : "border-border hover:border-primary/40"
                  } ${s.ok ? "" : "ring-1 ring-destructive/40"}`}
                >
                  <span className="block aspect-[9/16] overflow-hidden rounded-lg bg-muted">
                    {s.screenshot && (
                      // eslint-disable-next-line @next/next/no-img-element -- artifact thumbnail from the API
                      <img src={artifactUrl(runId, s.screenshot)} alt="" loading="lazy" className="size-full object-cover" />
                    )}
                  </span>
                  <span className="truncate px-0.5 text-[10px] text-muted-foreground tabular-nums">
                    {s.index + 1}. {s.action}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
