"use client";

import type { ReactNode } from "react";
import { ChevronDown, Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { findingSourceLabel, findingTitle } from "@/components/findings/finding-text";
import { artifactUrl } from "@/lib/api";
import { titleCase } from "@/lib/format";
import type { Evidence, Finding } from "@/lib/types";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-medium tracking-wider text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

function Screenshot({ runId, ev }: { runId: string; ev: Evidence }) {
  if (!ev.ref) return null;
  const url = artifactUrl(runId, ev.ref);
  return (
    <a href={url} target="_blank" rel="noreferrer" className="block shrink-0">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={ev.excerpt ?? "Screenshot captured during the run"}
        loading="lazy"
        className="max-h-80 rounded-2xl border border-border shadow-sm"
      />
    </a>
  );
}

function RawEvidence({ runId, ev }: { runId: string; ev: Evidence }) {
  return (
    <li className="space-y-1.5 rounded-2xl border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="font-medium tracking-wider uppercase">{titleCase(ev.kind)}</span>
        {ev.ref && (
          <a
            href={artifactUrl(runId, ev.ref)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-accent-info hover:underline"
          >
            Open file <ExternalLink className="size-3" />
          </a>
        )}
      </div>
      {ev.excerpt && (
        <pre className="max-h-56 overflow-auto rounded-xl bg-muted p-2 font-mono text-xs break-words whitespace-pre-wrap">
          {ev.excerpt}
        </pre>
      )}
    </li>
  );
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied the Maestro flow");
  } catch {
    toast.error("Could not copy. Select the text manually.");
  }
}

function Details({ runId, f }: { runId: string; f: Finding }) {
  const i = f.impact;
  const shots = f.evidence.filter((e) => e.kind === "screenshot" && e.ref);
  const raw = f.evidence.filter((e) => !(e.kind === "screenshot" && e.ref) && (e.excerpt || e.ref));
  return (
    <div className="flex-1 space-y-6 overflow-y-auto px-5 pb-8">
      {shots.length > 0 && (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {shots.map((ev, idx) => (
            <Screenshot key={idx} runId={runId} ev={ev} />
          ))}
        </div>
      )}

      <p className="text-sm leading-relaxed">{f.description}</p>

      {f.repro_steps.length > 0 && (
        <Block title="How to reproduce">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {f.repro_steps.map((s, idx) => (
              <li key={idx}>{s}</li>
            ))}
          </ol>
        </Block>
      )}

      {f.probable_cause && (
        <Block title="Probable cause">
          <p className="text-sm leading-relaxed">{f.probable_cause}</p>
        </Block>
      )}
      {f.suggested_fix && (
        <Block title="Suggested fix">
          <p className="rounded-2xl bg-accent px-4 py-3 text-sm leading-relaxed text-accent-foreground">
            {f.suggested_fix}
          </p>
        </Block>
      )}

      {f.repro_flow && (
        <Block title="Maestro flow">
          <div className="relative">
            <Button
              variant="secondary"
              size="xs"
              className="absolute top-2 right-2 rounded-full"
              onClick={() => copy(f.repro_flow ?? "")}
              aria-label="Copy Maestro YAML"
            >
              <Copy /> Copy
            </Button>
            <pre className="max-h-72 overflow-auto rounded-2xl bg-muted p-3 pr-20 font-mono text-xs">
              {f.repro_flow}
            </pre>
          </div>
        </Block>
      )}

      <details className="group rounded-2xl border border-border">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
          Technical details
          <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="space-y-4 border-t border-border px-4 py-4">
          <p className="font-mono text-xs text-muted-foreground">
            {f.rule_id} · {titleCase(f.category)}
            {f.profile_id ? ` · ${f.profile_id}` : ""}
            {f.affected_journey
              ? ` · ${f.affected_journey}${f.journey_step !== null ? ` (step ${f.journey_step})` : ""}`
              : ""}
          </p>
          {i ? (
            <div className="space-y-1.5">
              <p className="font-mono text-sm tabular-nums">
                {Math.round(i.users_exposed * 100)}% users x {i.severity_weight} severity x {i.flow_usage} flow usage ={" "}
                <span className="font-semibold text-primary">{i.score.toFixed(1)}</span>
              </p>
              <p className="text-xs text-muted-foreground">
                Users exposed comes from the device profile, severity weight from the rule, and flow usage from how
                often the journey is used. These are stated assumptions, not measured telemetry.
              </p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No impact estimate was produced for this issue.</p>
          )}
          {raw.length > 0 && (
            <ul className="space-y-2">
              {raw.map((ev, idx) => (
                <RawEvidence key={idx} runId={runId} ev={ev} />
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  );
}

export function FindingSheet({
  runId,
  finding,
  onClose,
}: {
  runId: string;
  finding: Finding | null;
  onClose: () => void;
}) {
  return (
    <Sheet open={!!finding} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-2 rounded-l-3xl bg-background max-sm:rounded-none data-[side=right]:sm:max-w-xl">
        {finding && (
          <>
            <SheetHeader className="gap-2 px-5 pt-5 pr-12">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={finding.severity} />
                <span className="text-xs text-muted-foreground">{findingSourceLabel(finding)}</span>
              </div>
              <SheetTitle className="text-lg leading-snug">{findingTitle(finding)}</SheetTitle>
              <SheetDescription className="text-xs">
                {finding.impact && Math.round(finding.impact.users_exposed * 100) > 0
                  ? `Could affect about ${Math.round(finding.impact.users_exposed * 100)}% of users (an assumption based on the device profile).`
                  : "Impact estimate not available."}
              </SheetDescription>
            </SheetHeader>
            <Details runId={runId} f={finding} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
