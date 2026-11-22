import { API_URL, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";
import type { ProfileId, Run } from "@/lib/types";
import type { TestAccount } from "@/lib/account";

/** Import the latest release APK of a GitHub repo and start a run (POST /api/runs/import). */
export async function importRun(
  repoUrl: string,
  profiles?: ProfileId[],
  account?: TestAccount,
): Promise<Run> {
  const token = await getAccessToken();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/runs/import`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ repo_url: repoUrl, profiles, credentials: account }),
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}`, 0);
  }
  if (!res.ok) {
    let detail = `Import failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as Run;
}

const GITHUB_RE = /^(https?:\/\/)?(www\.)?github\.com\/[\w.-]+\/[\w.-]+/i;

/** Cheap client-side shape check; the server does the real validation. */
export function looksLikeGithubRepo(v: string): boolean {
  return GITHUB_RE.test(v.trim());
}
