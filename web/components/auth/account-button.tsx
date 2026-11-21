"use client";

import { useEffect, useRef } from "react";
import { LogOut } from "lucide-react";
import { useSession } from "./use-session";

/**
 * Oryn-style frictionless auth: everyone starts as a Supabase guest automatically, so runs and
 * conversations are saved from the first visit. Guests can upgrade to Google from the header.
 */
export function AccountButton() {
  const s = useSession();
  const tried = useRef(false);

  useEffect(() => {
    if (!s.available || !s.ready || s.session || tried.current) return;
    tried.current = true;
    void s.signInGuest();
  }, [s]);

  if (!s.available || !s.ready || !s.user) return null;

  if (s.user.is_anonymous) {
    return (
      <button
        type="button"
        onClick={() => void s.signInGoogle()}
        className="rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
      >
        Sign in with Google
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void s.signOut()}
      title={s.user.email ?? "Signed in"}
      aria-label="Sign out"
      className="flex items-center gap-1.5 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
    >
      <span className="max-w-32 truncate">{s.user.email ?? "Signed in"}</span>
      <LogOut className="size-3.5" />
    </button>
  );
}
