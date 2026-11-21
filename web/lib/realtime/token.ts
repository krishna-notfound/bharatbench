import { getAccessToken } from "@/lib/supabase/client";

/** Supabase access token for `session.start` (guest or Google); null when signed out or Supabase is unset. */
export async function getTokenSafe(): Promise<string | null> {
  return getAccessToken();
}
