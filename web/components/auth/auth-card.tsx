"use client";

import { useState } from "react";
import { LogOut, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSession } from "./use-session";

export function AuthCard({ className }: { className?: string }) {
  const { user, ready, available, signInGuest, signInGoogle, signOut } =
    useSession();
  const [busy, setBusy] = useState<"guest" | "google" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: "guest" | "google", fn: () => Promise<string | null>) {
    setBusy(kind);
    setError(null);
    const err = await fn();
    if (err) setError(err);
    setBusy(null);
  }

  const shell = `rounded-3xl border border-border bg-card p-6 text-center ${className ?? ""}`;

  if (!available) {
    return (
      <div className={shell} role="status">
        <p className="text-sm font-medium">Sign-in unavailable</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Accounts are not configured here. You can still run tests.
        </p>
      </div>
    );
  }

  if (!ready) {
    return <div className={shell} aria-busy="true" />;
  }

  if (user) {
    const label = user.is_anonymous
      ? "Guest"
      : (user.email ?? "Signed in");
    return (
      <div className={`${shell} flex items-center justify-between gap-3`}>
        <span className="flex items-center gap-2 text-sm">
          <UserRound className="size-4 text-muted-foreground" />
          {label}
        </span>
        <Button variant="outline" size="sm" className="rounded-full" onClick={() => void signOut()}>
          <LogOut /> Sign out
        </Button>
      </div>
    );
  }

  return (
    <div className={shell}>
      <p className="text-base font-medium">Welcome to BharatBench</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Sign in to keep your tests and conversations.
      </p>
      <div className="mt-5 flex flex-col gap-2">
        <Button
          size="lg"
          className="rounded-full"
          disabled={busy !== null}
          onClick={() => void run("google", signInGoogle)}
        >
          {busy === "google" ? "Redirecting…" : "Continue with Google"}
        </Button>
        <Button
          variant="outline"
          size="lg"
          className="rounded-full"
          disabled={busy !== null}
          onClick={() => void run("guest", signInGuest)}
        >
          {busy === "guest" ? "Starting…" : "Continue as guest"}
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
