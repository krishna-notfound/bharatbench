"use client";

import { useCallback, useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { getSupabase, isSupabaseConfigured } from "@/lib/supabase/client";

export type SessionState = {
  session: Session | null;
  user: User | null;
  /** False until the initial session lookup finishes. */
  ready: boolean;
  /** False when NEXT_PUBLIC_SUPABASE_* env vars are unset. */
  available: boolean;
  signInGuest: () => Promise<string | null>;
  /** `next` is where to land after the OAuth round-trip. */
  signInGoogle: (next?: string) => Promise<string | null>;
  signOut: () => Promise<void>;
};

/** Each action resolves to an error message, or null on success. */
export function useSession(): SessionState {
  const [session, setSession] = useState<Session | null>(null);
  const [initialised, setInitialised] = useState(false);
  const available = isSupabaseConfigured();
  const ready = !available || initialised;

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (active) setSession(data.session);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setInitialised(true);
      });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setInitialised(true);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const signInGuest = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return "Sign-in unavailable";
    const { error } = await supabase.auth.signInAnonymously();
    if (!error) return null;
    return error.message.toLowerCase().includes("anonymous")
      ? "Guest sign-in isn't enabled right now."
      : "Couldn't start a guest session. Please try again.";
  }, []);

  const signInGoogle = useCallback(async (next?: string) => {
    const supabase = getSupabase();
    if (!supabase) return "Sign-in unavailable";
    const NOT_SET_UP = "Google sign-in isn't set up yet. Continue as guest for now.";
    // signInWithOAuth only builds a URL, so a disabled provider would dump the user on a raw
    // JSON error page. Ask the auth server first (public settings endpoint).
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_SUPABASE_URL}/auth/v1/settings`,
        { headers: { apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY as string } },
      );
      if (res.ok) {
        const cfg = (await res.json()) as { external?: { google?: boolean } };
        if (cfg.external && !cfg.external.google) return NOT_SET_UP;
      }
    } catch {
      /* offline or blocked: fall through and let the redirect try */
    }
    const redirectTo = `${window.location.origin}/auth/callback${
      next ? `?next=${encodeURIComponent(next)}` : ""
    }`;
    const options = { redirectTo };
    const { data } = await supabase.auth.getSession();
    const isGuest = Boolean(data.session?.user.is_anonymous);
    // Guests upgrade in place (keeps their runs and chats); needs manual linking enabled.
    let { error } = isGuest
      ? await supabase.auth.linkIdentity({ provider: "google", options })
      : await supabase.auth.signInWithOAuth({ provider: "google", options });
    if (error && isGuest) {
      ({ error } = await supabase.auth.signInWithOAuth({ provider: "google", options }));
    }
    if (!error) return null;
    return /provider|enabled|unsupported/i.test(error.message)
      ? NOT_SET_UP
      : "Couldn't start Google sign-in. Please try again.";
  }, []);

  const signOut = useCallback(async () => {
    await getSupabase()?.auth.signOut();
  }, []);

  return {
    session,
    user: session?.user ?? null,
    ready,
    available,
    signInGuest,
    signInGoogle,
    signOut,
  };
}
