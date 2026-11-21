/**
 * Access token for `session.start`. Returns null until the auth module (f10, `@/lib/supabase`)
 * is merged; the server accepts a null token only when `AUTH_REQUIRED=false`.
 *
 * ORCHESTRATOR: on merge, replace the body with `return getAccessToken();` from `@/lib/supabase`.
 */
export async function getTokenSafe(): Promise<string | null> {
  return null;
}
