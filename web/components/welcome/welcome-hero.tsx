"use client";

import Link from "next/link";
import { ArrowRight, MessageCircle } from "lucide-react";
import { Orb } from "@/components/orb/orb";
import { useFetch } from "@/components/shell/use-fetch";
import { getHealth } from "@/lib/api";
import { PRIMARY_CTA, SECONDARY_CTA } from "@/components/shell/surface";
import { cn } from "@/lib/utils";

function StatusPill() {
  const { data, error, loading } = useFetch(getHealth, 15000);
  const online = !!data?.harness.reachable;
  const label = loading
    ? "Checking my test lab…"
    : error && !data
      ? "Test lab offline"
      : online
        ? "Emulator ready"
        : "Emulator offline";
  return (
    <div
      role="status"
      aria-live="polite"
      title={data && !online ? data.harness.detail : label}
      className="mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-medium text-muted-foreground shadow-[0_1px_2px_rgba(30,27,46,0.04)]"
    >
      <span
        className={cn(
          "size-2 rounded-full",
          online ? "bg-success" : error && !data ? "bg-destructive" : "bg-muted-foreground",
          loading && "animate-pulse",
        )}
      />
      {label}
    </div>
  );
}

export function WelcomeHero() {
  return (
    <section className="flex flex-col items-center text-center">
      <Orb state="idle" size="xl" />
      <h1 className="mt-8 text-4xl font-semibold tracking-tight md:text-6xl">
        Hi, I&apos;m BharatBench
      </h1>
      <p className="mt-4 max-w-md text-base text-muted-foreground md:text-lg">
        I run your Android app on the everyday phones your users really
        carry, and tell you what breaks and who it affects.
      </p>
      <StatusPill />
      <div className="mt-8 flex w-full flex-col items-center gap-3 sm:w-auto sm:flex-row">
        <Link href="/new" className={cn(PRIMARY_CTA, "w-full sm:w-auto")}>
          Test my app <ArrowRight className="size-5" />
        </Link>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent("bb:open-agent"))}
          className={cn(SECONDARY_CTA, "w-full sm:w-auto")}
        >
          <MessageCircle className="size-5" /> Talk to me
        </button>
      </div>
    </section>
  );
}
