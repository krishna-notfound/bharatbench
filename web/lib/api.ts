import { getAccessToken } from "@/lib/supabase/client";
import type {
  Finding,
  Health,
  Profile,
  ProfileId,
  Run,
  RunEvent,
} from "@/lib/types";

export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const headers = { ...(await authHeaders()), ...(init?.headers as Record<string, string> | undefined) };
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}`, 0);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const getHealth = () => request<Health>("/api/health");
export const getProfiles = () => request<Profile[]>("/api/profiles");
export const listRuns = () => request<Run[]>("/api/runs");
export const getRun = (id: string) =>
  request<Run>(`/api/runs/${encodeURIComponent(id)}`);
export const getFindings = (id: string) =>
  request<Finding[]>(`/api/runs/${encodeURIComponent(id)}/findings`);
export const getEvents = (id: string, afterSeq?: number) =>
  request<RunEvent[]>(
    `/api/runs/${encodeURIComponent(id)}/events${
      afterSeq !== undefined ? `?after_seq=${afterSeq}` : ""
    }`,
  );
export const cancelRun = (id: string) =>
  request<Run>(`/api/runs/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  });

export function artifactUrl(runId: string, path: string): string {
  const safe = path
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent)
    .join("/");
  return `${API_URL}/api/runs/${encodeURIComponent(runId)}/artifacts/${safe}`;
}

export function reportUrl(runId: string): string {
  return `${API_URL}/api/runs/${encodeURIComponent(runId)}/report.md`;
}

/** Multipart upload via XHR so we can report upload progress (0-100). */
export function createRun(
  file: File,
  profiles: ProfileId[],
  onProgress?: (pct: number) => void,
): Promise<Run> {
  return authHeaders().then((headers) => new Promise<Run>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/api/runs`);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(`Cannot reach the API at ${API_URL}`, 0));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Run);
        return;
      }
      const body = xhr.response as { detail?: unknown } | null;
      const detail =
        body && typeof body.detail === "string"
          ? body.detail
          : `Upload failed (${xhr.status})`;
      reject(new ApiError(detail, xhr.status));
    };
    const form = new FormData();
    form.append("apk", file);
    form.append("profiles", profiles.join(","));
    xhr.send(form);
  }));
}
