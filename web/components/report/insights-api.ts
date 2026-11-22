import { API_URL, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";
import type { Severity } from "@/lib/types";

export type PlayRiskLevel = "high" | "medium" | "low" | "unknown";

export interface PlayRisk {
  level: PlayRiskLevel;
  headline: string;
  reasons: { finding_id: string; text: string }[];
  thresholds: { crash_rate_pct: number; anr_rate_pct: number };
}

export interface CompareItem {
  rule_id: string;
  profile: string | null;
  title: string;
  severity: Severity;
}

export interface RunComparison {
  previous_run_id: string;
  score_before: number | null;
  score_after: number | null;
  fixed: CompareItem[];
  new: CompareItem[];
  persisting: CompareItem[];
}

export interface TeamBrief {
  text: string;
  audio_b64: string | null;
  language: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getAccessToken();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}`, 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

const base = (id: string) => `/api/runs/${encodeURIComponent(id)}`;

export const getPlayRisk = (id: string) => call<PlayRisk>(`${base(id)}/play-risk`);
export const getComparison = (id: string) => call<RunComparison>(`${base(id)}/compare`);
export const createBrief = (id: string, language: string) =>
  call<TeamBrief>(`${base(id)}/brief`, {
    method: "POST",
    body: JSON.stringify({ language }),
  });
