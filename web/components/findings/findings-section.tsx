"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, Hourglass } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState, ErrorState, SectionTitle } from "@/components/shell/states";
import {
  SEVERITY_BAR,
  SeverityBadge,
} from "@/components/findings/severity-badge";
import { FindingSheet } from "@/components/findings/finding-sheet";
import {
  SEVERITY_LABEL,
  SEVERITY_ORDER,
  SOURCE_LABEL,
  titleCase,
} from "@/lib/format";
import type { Category, Finding, FindingSource, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

const SELECT_CLS =
  "h-8 rounded-lg border border-input bg-background px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-primary";

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      {label}
      <select
        className={SELECT_CLS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="all">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function FindingsSection({
  runId,
  findings,
  loading,
  error,
  onRetry,
  runActive,
}: {
  runId: string;
  findings: Finding[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  runActive: boolean;
}) {
  const [sev, setSev] = useState("all");
  const [cat, setCat] = useState("all");
  const [src, setSrc] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const sorted = useMemo(
    () =>
      [...(findings ?? [])].sort(
        (a, b) => (b.impact?.score ?? -1) - (a.impact?.score ?? -1),
      ),
    [findings],
  );
  const categories = useMemo(
    () => Array.from(new Set(sorted.map((f) => f.category))).sort(),
    [sorted],
  );
  const visible = sorted.filter(
    (f) =>
      (sev === "all" || f.severity === sev) &&
      (cat === "all" || f.category === cat) &&
      (src === "all" || f.source === src),
  );
  const selected = sorted.find((f) => f.id === openId) ?? null;

  let body;
  if (loading) {
    body = (
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    );
  } else if (error && !findings) {
    body = (
      <ErrorState
        title="Could not load findings"
        message={error}
        onRetry={onRetry}
      />
    );
  } else if (sorted.length === 0) {
    body = runActive ? (
      <EmptyState
        icon={<Hourglass className="size-6" />}
        title="No findings yet"
        message="Findings appear here as the test discovers them."
      />
    ) : (
      <EmptyState
        icon={<CheckCircle2 className="size-6 text-success" />}
        title="No issues found under these profiles"
      />
    );
  } else if (visible.length === 0) {
    body = (
      <EmptyState
        title="No findings match these filters"
        message="Clear a filter to see more."
      />
    );
  } else {
    body = (
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Finding</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>Profile</TableHead>
              <TableHead className="min-w-32">Impact</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((f) => (
              <TableRow
                key={f.id}
                tabIndex={0}
                role="button"
                aria-label={`Open finding: ${f.title}`}
                className="cursor-pointer outline-none focus-visible:bg-muted"
                onClick={() => setOpenId(f.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setOpenId(f.id);
                  }
                }}
              >
                <TableCell>
                  <SeverityBadge severity={f.severity} />
                </TableCell>
                <TableCell className="max-w-sm whitespace-normal font-medium">
                  {f.title}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {titleCase(f.category)}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {f.profile_id ?? "—"}
                </TableCell>
                <TableCell>
                  <ImpactBar finding={f} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {SOURCE_LABEL[f.source]}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    );
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionTitle>
          Findings{findings ? ` · ${visible.length}` : ""}
        </SectionTitle>
        {sorted.length > 0 && (
          <div className="flex flex-wrap gap-3">
            <FilterSelect
              label="Severity"
              value={sev}
              onChange={setSev}
              options={SEVERITY_ORDER.map((s: Severity) => ({
                value: s,
                label: SEVERITY_LABEL[s],
              }))}
            />
            <FilterSelect
              label="Category"
              value={cat}
              onChange={setCat}
              options={categories.map((c: Category) => ({
                value: c,
                label: titleCase(c),
              }))}
            />
            <FilterSelect
              label="Source"
              value={src}
              onChange={setSrc}
              options={(["static", "runtime"] as FindingSource[]).map((s) => ({
                value: s,
                label: SOURCE_LABEL[s],
              }))}
            />
          </div>
        )}
      </div>
      {error && findings && (
        <p role="alert" className="text-xs text-destructive">
          Refresh failed: {error}. Showing last known data.
        </p>
      )}
      {body}
      <FindingSheet
        runId={runId}
        finding={selected}
        onClose={() => setOpenId(null)}
      />
    </section>
  );
}

function ImpactBar({ finding }: { finding: Finding }) {
  if (!finding.impact) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  const score = finding.impact.score;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", SEVERITY_BAR[finding.severity])}
          style={{ width: `${Math.max(2, Math.min(100, score))}%` }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums">{score.toFixed(1)}</span>
    </div>
  );
}
