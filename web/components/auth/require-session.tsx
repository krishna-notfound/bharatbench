"use client";

import { useCallback, useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { loginHref } from "@/lib/onboarding";
import { useSession } from "./use-session";

/**
 * Redirects to /login?next=<current path> when there is no session.
 * `allowed` is true when signed in (guest or Google) or when auth isn't configured at all
 * (so local dev without Supabase keeps working). `ensure()` is for click handlers, e.g. "Talk to me".
 */
export function useRequireSession(opts: { redirect?: boolean } = {}) {
  const { redirect = true } = opts;
  const s = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const allowed = !s.available || Boolean(s.session);

  useEffect(() => {
    if (redirect && s.ready && !allowed) router.replace(loginHref(pathname || "/"));
  }, [redirect, s.ready, allowed, router, pathname]);

  /** Returns true if signed in; otherwise navigates to /login and returns false. */
  const ensure = useCallback(
    (next?: string) => {
      if (allowed) return true;
      router.push(loginHref(next ?? pathname ?? "/"));
      return false;
    },
    [allowed, router, pathname],
  );

  return { ...s, allowed, ensure };
}

export function RequireSession({ children }: { children: ReactNode }) {
  const { ready, allowed } = useRequireSession();
  if (!ready || !allowed) {
    return (
      <div role="status" aria-busy="true" className="flex min-h-[40vh] items-center justify-center">
        <span className="sr-only">Checking your session</span>
        <span className="size-6 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
      </div>
    );
  }
  return <>{children}</>;
}
