const KEY = "bb.onboarded.v1";

export function isOnboarded(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function markOnboarded(): void {
  try {
    window.localStorage.setItem(KEY, "1");
  } catch {
    /* storage blocked: onboarding will simply show again */
  }
}

/** Only same-site relative paths are allowed as post-login destinations. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next.startsWith("/login") || next.startsWith("/auth/")) return "/";
  return next;
}

export function loginHref(next: string): string {
  return `/login?next=${encodeURIComponent(next)}`;
}

/** Where to go right after a successful sign-in. */
export function postSignInHref(next: string | null | undefined): string {
  const dest = safeNext(next);
  if (isOnboarded()) return dest;
  return dest === "/" ? "/onboarding" : `/onboarding?next=${encodeURIComponent(dest)}`;
}
