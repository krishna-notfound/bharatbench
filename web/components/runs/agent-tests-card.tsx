"use client";

import { Check, Minus, X } from "lucide-react";
import { useFetch } from "@/components/shell/use-fetch";
import { getAgentTests } from "@/lib/api";

/** Tests the agent wrote for this app, with the outcome of each. Hidden when none were written. */
export function AgentTestsCard({ runId }: { runId: string }) {
  const tests = useFetch(() => getAgentTests(runId));
  const rows = tests.data ?? [];
  if (rows.length === 0) return null;
  return (
    <section
      aria-label="Tests the agent wrote"
      className="space-y-4 rounded-3xl border border-border bg-card p-6 shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)] md:p-8"
    >
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">Tests the agent wrote</h2>
        <p className="text-sm text-muted-foreground">
          Custom checks for your app. A dash means the test could not be judged.
        </p>
      </div>
      <ul className="space-y-3">
        {rows.map((t) => {
          const Icon = t.passed === true ? Check : t.passed === false ? X : Minus;
          const tone =
            t.passed === true
              ? "bg-emerald-100 text-emerald-700"
              : t.passed === false
                ? "bg-red-100 text-red-700"
                : "bg-muted text-muted-foreground";
          return (
            <li key={t.id} className="flex items-start gap-3">
              <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full ${tone}`}>
                <Icon className="size-3.5" aria-hidden />
                <span className="sr-only">
                  {t.passed === true ? "Passed" : t.passed === false ? "Failed" : "Not judged"}
                </span>
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t.title}</p>
                <p className="text-sm text-muted-foreground">{t.reason}</p>
                <a href="#replay" className="text-xs text-primary hover:underline">
                  See the steps in the replay
                </a>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
