"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { LogOut, UserRound } from "lucide-react";
import { loginHref } from "@/lib/onboarding";
import { useSession } from "./use-session";

const PILL =
  "shrink-0 whitespace-nowrap rounded-full border border-border bg-card px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none";

/**
 * Header account control. Visitors become a Supabase guest silently on first load, so every run they start is
 * owned by them and only they see it (the API lists only the caller's own runs). Guests can upgrade to Google.
 */
export function AccountButton() {
  const s = useSession();
  const router = useRouter();
  const tried = useRef(false);

  useEffect(() => {
    if (!s.available || !s.ready || s.session || tried.current) return;
    tried.current = true;
    void s.signInGuest();
  }, [s]);
  // Read at click time: usePathname() here would opt every static page out of prerendering.
  const here = () => window.location.pathname + window.location.search;

  if (!s.available || !s.ready) return null;

  if (!s.user) {
    return (
      <button
        type="button"
        onClick={() => router.push(loginHref(here()))}
        aria-label="Sign in"
        className={`${PILL} max-sm:size-9 max-sm:px-0 max-sm:flex max-sm:items-center max-sm:justify-center`}
      >
        <UserRound className="size-4 sm:hidden" aria-hidden />
        <span className="max-sm:hidden">Sign in</span>
      </button>
    );
  }

  if (s.user.is_anonymous) {
    return (
      <button
        type="button"
        onClick={() => void s.signInGoogle(here())}
        aria-label="Sign in with Google to keep your guest data"
        className={`${PILL} max-sm:size-9 max-sm:px-0 max-sm:flex max-sm:items-center max-sm:justify-center`}
        title="Keep your tests and chats by signing in with Google"
      >
        <UserRound className="size-4 sm:hidden" aria-hidden />
        <span className="max-sm:hidden">Guest · Sign in with Google</span>
      </button>
    );
  }

  const name = (s.user.user_metadata?.full_name as string | undefined) ?? s.user.email ?? "Signed in";
  const avatar = s.user.user_metadata?.avatar_url as string | undefined;
  return (
    <button
      type="button"
      onClick={() => void s.signOut()}
      title={`${s.user.email ?? name} · Sign out`}
      aria-label="Sign out"
      className="flex items-center gap-2 rounded-full py-1 pr-2 pl-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
    >
      {avatar ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={avatar} alt="" referrerPolicy="no-referrer" className="size-7 rounded-full" />
      ) : (
        <span className="flex size-7 items-center justify-center rounded-full bg-accent font-semibold text-accent-foreground">
          {name.charAt(0).toUpperCase()}
        </span>
      )}
      <span className="hidden max-w-32 truncate sm:inline">{name}</span>
      <LogOut className="size-3.5" />
    </button>
  );
}
