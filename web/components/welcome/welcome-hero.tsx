"use client";

import Link from "next/link";
import { ArrowRight, MessageCircle } from "lucide-react";
import { Orb } from "@/components/orb/orb";
import { PRIMARY_CTA, SECONDARY_CTA } from "@/components/shell/surface";
import { cn } from "@/lib/utils";

export function WelcomeHero() {
  return (
    <section className="flex flex-col items-center text-center">
      <Orb state="idle" size="xl" />
      <h1 className="mt-10 text-4xl font-semibold tracking-tight md:text-6xl">
        Hi, I&apos;m BharatBench
      </h1>
      <p className="mt-4 max-w-md text-base text-muted-foreground md:text-lg">
        I try your Android app on a cheap phone, the kind your users really
        carry, and tell you what breaks and who it hurts.
      </p>
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
