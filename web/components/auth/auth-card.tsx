"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSession } from "./use-session";

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.4 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
      <path fill="#FBBC05" d="M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.2.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}

/**
 * Sign-in actions (Google + guest). Calls `onSignedIn` after a successful guest sign-in;
 * Google leaves the page for the OAuth round-trip and returns via /auth/callback.
 */
export function AuthCard({
  className,
  next,
  onSignedIn,
}: {
  className?: string;
  next?: string;
  onSignedIn?: () => void;
}) {
  const { ready, available, signInGuest, signInGoogle } = useSession();
  const [busy, setBusy] = useState<"guest" | "google" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: "guest" | "google") {
    setBusy(kind);
    setError(null);
    const err = kind === "guest" ? await signInGuest() : await signInGoogle(next);
    if (err) {
      setError(err);
      setBusy(null);
    } else if (kind === "guest") {
      onSignedIn?.();
    }
    // Google success: the browser is navigating away; keep the busy state.
  }

  if (!available) {
    return (
      <div className={cn("rounded-3xl border border-border bg-card p-5 text-center", className)} role="status">
        <p className="text-sm font-medium">Sign-in unavailable</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Accounts aren&apos;t configured here. You can still run tests.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("flex w-full flex-col gap-3", className)} aria-busy={!ready}>
      <Button
        size="lg"
        disabled={!ready || busy !== null}
        onClick={() => void run("google")}
        className="h-12 w-full gap-3 rounded-full border border-border bg-white text-[15px] font-medium text-foreground shadow-sm hover:bg-white/80"
      >
        <GoogleMark />
        {busy === "google" ? "Opening Google…" : "Continue with Google"}
      </Button>
      <Button
        size="lg"
        disabled={!ready || busy !== null}
        onClick={() => void run("guest")}
        className="h-12 w-full rounded-full bg-accent text-[15px] font-medium text-accent-foreground hover:bg-accent/70"
      >
        {busy === "guest" ? "Starting…" : "Continue as guest"}
      </Button>
      {error && (
        <p role="alert" className="rounded-2xl bg-destructive/10 px-4 py-2.5 text-center text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
