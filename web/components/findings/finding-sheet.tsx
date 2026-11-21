"use client";

import type { ReactNode } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { SeverityBadge } from "@/components/findings/severity-badge";
import { artifactUrl } from "@/lib/api";
import { SOURCE_LABEL, titleCase } from "@/lib/format";
import type { Evidence, Finding } from "@/lib/types";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

function EvidenceItem({ runId, ev }: { runId: string; ev: Evidence }) {
  const isImage = ev.kind === "screenshot" && !!ev.ref;
  return (
    <li className="space-y-1.5 rounded-lg border border-border bg-background p-2.5">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="font-medium uppercase tracking-wider">
          {titleCase(ev.kind)}
        </span>
        {ev.ref && !isImage && (
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
      {isImage && ev.ref && (
        <a href={artifactUrl(runId, ev.ref)} target="_blank" rel="noreferrer">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={artifactUrl(runId, ev.ref)}
            alt={ev.excerpt ?? "Screenshot captured during the run"}
            loading="lazy"
            className="max-h-96 rounded-md border border-border"
          />
        </a>
      )}
      {ev.excerpt && (
        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 font-mono text-xs">
          {ev.excerpt}
        </pre>
      )}
    </li>
  );
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Copied Maestro flow");
  } catch {
    toast.error("Could not copy. Select the text manually.");
  }
}

function Details({ runId, f }: { runId: string; f: Finding }) {
  const i = f.impact;
  return (
    <div className="flex-1 space-y-5 overflow-y-auto px-4 pb-6">
      <p className="text-sm">{f.description}</p>

      <Block title="Impact (assumptions)">
        {i ? (
          <div className="space-y-2 rounded-lg bg-muted p-3">
            <p className="font-mono text-sm tabular-nums">
              {Math.round(i.users_exposed * 100)}% users × {i.severity_weight}{" "}
              severity × {i.flow_usage} flow usage ={" "}
              <span className="font-semibold text-primary">
                {i.score.toFixed(1)}
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              Users exposed comes from the device profile, severity weight from
              the rule, and flow usage from how often the affected journey is
              used. These are stated assumptions, not measured telemetry.
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No impact estimate was produced for this finding.
          </p>
        )}
      </Block>

      {f.evidence.length > 0 && (
        <Block title="Evidence">
          <ul className="space-y-2">
            {f.evidence.map((ev, idx) => (
              <EvidenceItem key={idx} runId={runId} ev={ev} />
            ))}
          </ul>
        </Block>
      )}

      {f.probable_cause && (
        <Block title="Probable cause">
          <p className="text-sm">{f.probable_cause}</p>
        </Block>
      )}
      {f.suggested_fix && (
        <Block title="Suggested fix">
          <p className="text-sm">{f.suggested_fix}</p>
        </Block>
      )}

      {f.repro_steps.length > 0 && (
        <Block title="Repro steps">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {f.repro_steps.map((s, idx) => (
              <li key={idx}>{s}</li>
            ))}
          </ol>
        </Block>
      )}

      {f.repro_flow && (
        <Block title="Maestro flow">
          <div className="relative">
            <Button
              variant="secondary"
              size="xs"
              className="absolute top-2 right-2"
              onClick={() => copy(f.repro_flow ?? "")}
              aria-label="Copy Maestro YAML"
            >
              <Copy /> Copy
            </Button>
            <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 pr-20 font-mono text-xs">
              {f.repro_flow}
            </pre>
          </div>
        </Block>
      )}
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
      <SheetContent className="w-full rounded-l-2xl max-sm:rounded-none data-[side=right]:sm:max-w-xl">
        {finding && (
          <>
            <SheetHeader className="gap-2 pr-12">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={finding.severity} />
                <span className="text-xs text-muted-foreground">
                  {titleCase(finding.category)} · {SOURCE_LABEL[finding.source]}
                  {finding.profile_id ? ` · ${finding.profile_id}` : ""}
                </span>
              </div>
              <SheetTitle className="text-lg leading-snug">
                {finding.title}
              </SheetTitle>
              <SheetDescription className="font-mono text-xs">
                {finding.rule_id}
                {finding.affected_journey
                  ? ` · ${finding.affected_journey}${
                      finding.journey_step !== null
                        ? ` (step ${finding.journey_step})`
                        : ""
                    }`
                  : ""}
              </SheetDescription>
            </SheetHeader>
            <Details runId={runId} f={finding} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
