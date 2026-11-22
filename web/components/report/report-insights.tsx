"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ChevronDown, Loader2, Mic, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LANGUAGE_OPTIONS, type RealtimeLanguage } from "@/lib/realtime/languages";
import type { Finding, Run } from "@/lib/types";
import {
  createBrief,
  getComparison,
  getPlayRisk,
  type CompareItem,
  type PlayRisk,
  type PlayRiskLevel,
  type RunComparison,
  type TeamBrief,
} from "./insights-api";

const LEVEL_STYLE: Record<PlayRiskLevel, { label: string; pill: string }> = {
  high: { label: "High risk", pill: "bg-sev-critical/10 text-sev-critical ring-sev-critical/30" },
  medium: { label: "Medium risk", pill: "bg-sev-medium/10 text-sev-medium ring-sev-medium/30" },
  low: { label: "No crashes seen", pill: "bg-success/10 text-success ring-success/30" },
  unknown: { label: "Not tested", pill: "bg-muted text-muted-foreground ring-foreground/10" },
};

function PlayRiskCard({ risk, onSelectFinding }: { risk: PlayRisk; onSelectFinding?: (id: string) => void }) {
  const style = LEVEL_STYLE[risk.level];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="size-4 text-primary" />
          {risk.on_play_store ? "Play Store risk" : "Stability on our test phone"}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`rounded-full px-4 py-1.5 text-base font-semibold ring-1 ${style.pill}`}
            data-testid="play-risk-level"
          >
            {style.label}
          </span>
        </div>
        <p className="text-sm leading-relaxed">{risk.headline}</p>
        {risk.reasons.length > 0 && (
          <ul className="flex flex-col gap-1.5">
            {risk.reasons.map((r) => (
              <li key={r.finding_id} className="rounded-lg bg-muted px-3 py-2 text-sm">
                {onSelectFinding ? (
                  <button
                    type="button"
                    className="text-left hover:underline"
                    onClick={() => onSelectFinding(r.finding_id)}
                  >
                    {r.text}
                  </button>
                ) : (
                  r.text
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">
          {risk.on_play_store
            ? `Live on Google Play. Play's limits: ${risk.thresholds.anr_rate_pct}% ANR, ${risk.thresholds.crash_rate_pct}% crash rate of users. This is a lab run, not your real-user rate.`
            : risk.on_play_store === false
              ? "Not found on Google Play, so Play's limits don't apply yet. This is what our test phone observed."
              : "This is what our test phone observed; we couldn't check Google Play for this app."}
        </p>
      </CardContent>
    </Card>
  );
}

function ChangeList({ label, items, tone }: { label: string; items: CompareItem[]; tone: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg bg-muted">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-sm"
        aria-expanded={open}
        disabled={items.length === 0}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="flex items-center gap-2">
          <span className={`text-lg font-semibold tabular-nums ${tone}`}>{items.length}</span>
          {label}
        </span>
        {items.length > 0 && (
          <ChevronDown className={`size-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
        )}
      </button>
      {open && (
        <ul className="flex flex-col gap-1 px-3 pb-3 text-sm text-muted-foreground">
          {items.map((it, i) => (
            <li key={`${it.rule_id}-${it.profile}-${i}`}>{it.title}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComparisonCard({ cmp }: { cmp: RunComparison }) {
  const { score_before: before, score_after: after } = cmp;
  const delta = before != null && after != null ? Math.round((after - before) * 10) / 10 : null;
  const tone = delta == null || delta === 0 ? "text-muted-foreground" : delta > 0 ? "text-success" : "text-sev-critical";
  return (
    <Card>
      <CardHeader>
        <CardTitle>Compared with your previous test</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-3 text-3xl font-semibold tabular-nums">
          <span className="text-muted-foreground">{before ?? "-"}</span>
          <ArrowRight className="size-5 text-muted-foreground" />
          <span className={tone}>{after ?? "-"}</span>
          {delta != null && delta !== 0 && (
            <span className={`text-sm font-medium ${tone}`}>
              {delta > 0 ? "+" : ""}
              {delta} points
            </span>
          )}
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <ChangeList label="fixed" items={cmp.fixed} tone="text-success" />
          <ChangeList label="new" items={cmp.new} tone="text-sev-critical" />
          <ChangeList label="still there" items={cmp.persisting} tone="text-sev-medium" />
        </div>
      </CardContent>
    </Card>
  );
}

function audioSrc(brief: TeamBrief): string | null {
  return brief.audio_b64 ? `data:audio/wav;base64,${brief.audio_b64}` : null;
}

function BriefCard({ runId, disabled }: { runId: string; disabled: boolean }) {
  const [language, setLanguage] = useState<RealtimeLanguage>("auto");
  const [loading, setLoading] = useState(false);
  const [brief, setBrief] = useState<TeamBrief | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    try {
      setBrief(await createBrief(runId, language));
    } catch (e) {
      setBrief(null);
      setError(e instanceof Error ? e.message : "Could not create the brief");
    } finally {
      setLoading(false);
    }
  }

  const src = brief ? audioSrc(brief) : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mic className="size-4 text-primary" />
          Brief my team
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          A 60-second plain-language summary of this report for a founder or PM, in the language you pick.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Brief language"
            value={language}
            onChange={(e) => setLanguage(e.target.value as RealtimeLanguage)}
            disabled={loading}
            className="h-8 rounded-lg border border-input bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {LANGUAGE_OPTIONS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
          <Button onClick={generate} disabled={loading || disabled}>
            {loading ? <Loader2 className="animate-spin" /> : <Mic />}
            {loading ? "Writing brief..." : brief ? "Brief again" : "Brief my team"}
          </Button>
        </div>
        {disabled && <p className="text-xs text-muted-foreground">Available once the run has finished.</p>}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {brief && (
          <div className="flex flex-col gap-2 rounded-lg bg-accent p-3">
            {src ? (
              <audio controls autoPlay src={src} className="w-full" />
            ) : (
              <p className="text-xs text-muted-foreground">Voice is unavailable right now; here is the text.</p>
            )}
            <p className="text-sm leading-relaxed whitespace-pre-line">{brief.text}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ReportInsights({ run }: { run: Run; findings: Finding[] }) {
  const [riskFor, setRisk] = useState<{ id: string; data: PlayRisk } | null>(null);
  const [cmpFor, setCmp] = useState<{ id: string; data: RunComparison } | null>(null);
  const risk = riskFor?.id === run.id ? riskFor.data : null;
  const cmp = cmpFor?.id === run.id ? cmpFor.data : null;
  const finished = run.status === "done";

  useEffect(() => {
    let cancelled = false;
    if (!finished) return;
    getPlayRisk(run.id)
      .then((r) => !cancelled && setRisk({ id: run.id, data: r }))
      .catch(() => undefined); // card simply stays hidden
    getComparison(run.id)
      .then((c) => !cancelled && setCmp({ id: run.id, data: c }))
      .catch(() => undefined); // 404 = no earlier run of this app; hidden by design
    return () => {
      cancelled = true;
    };
  }, [run.id, finished]);

  return (
    <section aria-label="Report insights" className="grid gap-4 lg:grid-cols-2">
      {risk && <PlayRiskCard risk={risk} />}
      {cmp && <ComparisonCard cmp={cmp} />}
      <BriefCard runId={run.id} disabled={!finished} />
    </section>
  );
}
