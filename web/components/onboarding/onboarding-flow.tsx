"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ListChecks, Mic, MousePointerClick, Smartphone, Upload } from "lucide-react";
import { Orb, type OrbState } from "@/components/orb/orb";
import { openAgentPanel } from "@/components/voice/agent-events";
import { useRequireSession } from "@/components/auth/require-session";
import { markOnboarded, safeNext } from "@/lib/onboarding";
import { cn } from "@/lib/utils";

const LAB_STEPS = [
  { icon: Upload, title: "Upload your APK", body: "Drop in the file, nothing to install." },
  {
    icon: Smartphone,
    title: "A real Android in our cloud lab",
    body: "Everyday-phone limits: 2 GB RAM cap, slow or flaky network, low storage, battery saver, app restarts.",
  },
  {
    icon: MousePointerClick,
    title: "We tap through your app",
    body: "Screenshots and logs are collected along the way.",
  },
  { icon: ListChecks, title: "Ranked issues with fixes", body: "Ordered by how much real users would feel them." },
];

const ORB_FOR_STEP: OrbState[] = ["listening", "testing", "completed"];
const TITLES = ["Meet your testing buddy", "How the test lab works", "Let's start"];
const CARD = "rounded-3xl border border-border bg-card p-5 md:p-7";

function Step({ index }: { index: number }) {
  if (index === 0) {
    return (
      <div className="space-y-3 text-center">
        <p className="text-pretty text-lg">
          BharatBench tests your Android app the way it runs on the phones your users really carry, then explains what to fix.
        </p>
        <p className="text-pretty text-muted-foreground">
          <Mic className="mr-1.5 inline size-4 align-text-bottom" aria-hidden />
          Talk or type, in Hindi, English or Hinglish.
        </p>
      </div>
    );
  }
  if (index === 1) {
    return (
      <div className="space-y-4">
        <ol className="space-y-3">
          {LAB_STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3 text-left">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-accent-foreground">
                <s.icon className="size-4" aria-hidden />
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">
                  {i + 1}. {s.title}
                </span>
                <span className="block text-sm text-muted-foreground">{s.body}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground">
          We can&apos;t simulate heat throttling or brand-specific battery killers. We&apos;ll say so.
        </p>
      </div>
    );
  }
  return (
    <p className="text-pretty text-center text-lg">
      Upload an APK to run your first test, or just ask the agent what BharatBench can do.
    </p>
  );
}

export function OnboardingFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { ready, allowed } = useRequireSession();
  const [step, setStep] = useState(0);
  const touchX = useRef<number | null>(null);
  const last = TITLES.length - 1;

  const finish = useCallback(
    (to: string) => {
      markOnboarded();
      router.push(to);
    },
    [router],
  );

  const go = useCallback((d: number) => setStep((s) => Math.min(last, Math.max(0, s + d))), [last]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  if (!ready || !allowed) return <div className="min-h-[60vh]" aria-busy="true" />;

  return (
    <div
      className="mx-auto flex min-h-[calc(100dvh-9rem)] w-full max-w-md flex-col items-center justify-center gap-5 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
      onTouchStart={(e) => (touchX.current = e.touches[0].clientX)}
      onTouchEnd={(e) => {
        if (touchX.current === null) return;
        const dx = e.changedTouches[0].clientX - touchX.current;
        touchX.current = null;
        if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
      }}
    >
      <div className="flex w-full items-center justify-end">
        <button
          type="button"
          onClick={() => finish(next)}
          className="min-h-11 rounded-full px-4 text-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Skip
        </button>
      </div>

      <Orb size="lg" state={ORB_FOR_STEP[step]} />

      <section className={cn(CARD, "w-full")} aria-live="polite" aria-labelledby="onb-title">
        <p className="mb-1 text-center text-xs text-muted-foreground">
          Step {step + 1} of {TITLES.length}
        </p>
        <h1 id="onb-title" className="mb-4 text-balance text-center text-2xl font-semibold tracking-tight">
          {TITLES[step]}
        </h1>
        <Step index={step} />
        {step === last && (
          <div className="mt-6 flex flex-col gap-3">
            <button
              type="button"
              onClick={() => finish("/new")}
              className="h-12 rounded-full bg-primary text-[15px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:outline-none"
            >
              Upload my APK
            </button>
            <button
              type="button"
              onClick={() => {
                markOnboarded();
                router.push(next);
                openAgentPanel();
              }}
              className="h-12 rounded-full bg-accent text-[15px] font-medium text-accent-foreground transition-colors hover:bg-accent/70 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
            >
              Talk to the agent
            </button>
          </div>
        )}
      </section>

      <div className="flex w-full items-center justify-between">
        <button
          type="button"
          onClick={() => go(-1)}
          disabled={step === 0}
          className="min-h-11 rounded-full px-4 text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:invisible"
        >
          Back
        </button>
        <div className="flex gap-2" role="tablist" aria-label="Onboarding progress">
          {TITLES.map((t, i) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={i === step}
              aria-label={`Step ${i + 1}: ${t}`}
              onClick={() => setStep(i)}
              className="flex size-6 items-center justify-center focus-visible:outline-none"
            >
              <span
                className={cn(
                  "h-2 rounded-full transition-all motion-reduce:transition-none",
                  i === step ? "w-6 bg-primary" : "w-2 bg-border",
                )}
              />
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => go(1)}
          disabled={step === last}
          className="min-h-11 rounded-full px-4 text-sm font-medium text-primary hover:opacity-80 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none disabled:invisible"
        >
          Next
        </button>
      </div>
    </div>
  );
}
