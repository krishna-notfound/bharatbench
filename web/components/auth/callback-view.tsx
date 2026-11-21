"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Orb } from "@/components/orb/orb";
import { getSupabase } from "@/lib/supabase/client";
import { loginHref, postSignInHref, safeNext } from "@/lib/onboarding";
import { useSession } from "./use-session";

/**
 * OAuth return. The browser Supabase client (PKCE, detectSessionInUrl) exchanges `?code=` on its own;
 * we only wait for the session and move on, or explain the failure.
 */
export function CallbackView() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { session, ready } = useSession();
  const urlError = params.get("error_description") ?? params.get("error");
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    getSupabase(); // make sure the client exists so it can exchange the code
    const t = setTimeout(() => setTimedOut(true), 10000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (ready && session) router.replace(postSignInHref(next));
  }, [ready, session, next, router]);

  const failed = Boolean(urlError) || timedOut;

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-sm flex-col items-center justify-center text-center">
      <Orb size="lg" state={failed ? "error" : "thinking"} />
      {failed ? (
        <>
          <h1 className="mt-6 text-xl font-semibold">Couldn&apos;t finish signing in</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {urlError ?? "That took too long."} You can try again or continue as a guest.
          </p>
          <Link
            href={loginHref(next)}
            className="mt-5 inline-flex h-11 items-center rounded-full bg-primary px-6 text-sm font-medium text-primary-foreground"
          >
            Back to sign in
          </Link>
        </>
      ) : (
        <p role="status" className="mt-6 text-muted-foreground">
          Signing you in…
        </p>
      )}
    </div>
  );
}
