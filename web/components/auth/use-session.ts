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
  signInGoogle: () => Promise<string | null>;
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

  const signInGoogle = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return "Sign-in unavailable";
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
    return error ? "Couldn't start Google sign-in. Please try again." : null;
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
