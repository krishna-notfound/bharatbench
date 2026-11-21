"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Orb } from "@/components/orb/orb";
import { AuthCard } from "./auth-card";
import { useSession } from "./use-session";
import { postSignInHref, safeNext } from "@/lib/onboarding";

export function LoginView() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { session, ready, available } = useSession();

  // Already signed in (or just came back from Google): continue.
  useEffect(() => {
    if (ready && session) router.replace(postSignInHref(next));
  }, [ready, session, next, router]);

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-9rem)] w-full max-w-sm flex-col items-center justify-center py-6 text-center">
      <Orb size="xl" state="idle" />
      <span className="mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground">
        <span className="size-1.5 rounded-full bg-success" aria-hidden />
        Ready when you are
      </span>
      <h1 className="mt-4 text-balance text-3xl font-semibold tracking-tight md:text-4xl">
        Your <span className="whitespace-nowrap">real-phone</span> test lab
      </h1>
      <p className="mt-3 text-pretty text-muted-foreground">
        Upload an Android app and see how it behaves on the phones your users really carry, then hear what to fix.
      </p>
      <AuthCard
        className="mt-8"
        next={next}
        onSignedIn={() => router.replace(postSignInHref(next))}
      />
      {available && (
        <p className="mt-5 text-xs text-muted-foreground">
          Guests can try everything. Sign in with Google to keep your tests across devices. We only
          use your account to save your sessions.
        </p>
      )}
    </div>
  );
}
