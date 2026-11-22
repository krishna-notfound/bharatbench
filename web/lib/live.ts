"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, ApiError } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";
import type { ProfileId } from "@/lib/types";

export interface LiveInfo {
  seq?: number;
  running: boolean;
  reason?: string;
  has_frame?: boolean;
  profile_id?: ProfileId | null;
  step_index?: number | null;
  action?: string | null;
  target?: string | null;
  tap?: { x: number; y: number } | null;
  screen?: { w: number; h: number } | null;
  caption?: string | null;
  waiting_for_input?: boolean;
  input_request?: InputRequest | null;
}

export interface InputField {
  key: string;
  label: string;
  kind: "username" | "email" | "phone" | "password" | "otp" | "pin" | "text" | string;
  secret: boolean;
}

/** The agent's live question to the user (labels only; the answer is never echoed back). */
export interface InputRequest {
  request_id: string;
  fields: InputField[];
  reason: string;
  timeout_s?: number;
  started_at?: number;
}

export interface ReplayStep {
  index: number;
  action: string;
  target: string | null;
  ok: boolean;
  x: number | null;
  y: number | null;
  note: string | null;
  duration_ms: number | null;
  screenshot: string | null;
}

export interface ReplayProfile {
  profile_id: ProfileId;
  screen: { w: number; h: number } | null;
  steps: ReplayStep[];
}

export interface Replay {
  run_id: string;
  profiles: ReplayProfile[];
}

export const profileLabel = (id: string): string =>
  (PROFILE_LABEL as Record<string, string>)[id] ??
  (id.startsWith("agent_") ? `Agent: ${id.slice(6).replace(/_/g, " ")}` : id);

export const PROFILE_LABEL: Record<ProfileId, string> = {
  baseline: "Normal phone",
  budget_2gb: "2 GB budget phone",
  flaky_network: "Flaky network",
  low_storage: "Low storage",
  battery_saver: "Battery saver",
  process_death: "App killed & restored",
};

const enc = encodeURIComponent;

async function getJson<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new ApiError(`${res.status}`, res.status);
  return (await res.json()) as T;
}

export const getLive = (runId: string) => getJson<LiveInfo>(`/api/runs/${enc(runId)}/live`);
export const getReplay = (runId: string) => getJson<Replay>(`/api/runs/${enc(runId)}/replay`);
export const liveFrameUrl = (runId: string, seq: number) =>
  `${API_URL}/api/runs/${enc(runId)}/live.png?s=${seq}`;

/** Sends the user's answer (or a skip). Rejects with ApiError; values are never stored client-side. */
export async function sendInput(
  runId: string,
  requestId: string,
  values: Record<string, string>,
  skip: boolean,
): Promise<void> {
  const token = await getAccessToken();
  const res = await fetch(`${API_URL}/api/runs/${enc(runId)}/input`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ request_id: requestId, values, skip }),
  });
  if (!res.ok) throw new ApiError(`${res.status}`, res.status);
}

/** Short human caption for what the agent is doing on the phone. */
export function captionFor(action: string | null | undefined, target: string | null | undefined): string | null {
  switch (action) {
    case "launch":
      return "Opening the app";
    case "tap":
      return target ? `Tapping “${target.length > 28 ? `${target.slice(0, 27)}…` : target}”` : "Tapping";
    case "back":
      return "Going back";
    case "background":
      return "Sending the app to the background";
    case "kill":
      return "Killing the app";
    case "restore":
      return "Restarting app";
    case "fill":
      return target ? `Filling the ${target.replace(/_/g, " ")} field…` : "Filling a field…";
    case "toggle_network":
      return "Network dropped";
    case "wait":
      return "Waiting";
    default:
      return null;
  }
}

/** Blinks the tab title (and shows a notification if allowed) while the agent waits and the tab is hidden. */
export function useNeedsAttention(active: boolean): void {
  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const original = document.title;
    let on = false;
    const timer = setInterval(() => {
      if (document.hidden) {
        on = !on;
        document.title = on ? "Action needed" : original;
      } else {
        on = false;
        document.title = original;
      }
    }, 1000);
    try {
      if (document.hidden && "Notification" in window && Notification.permission === "granted") {
        new Notification("Action needed", { body: "The agent is waiting for your input on the test phone." });
      }
    } catch {
      /* notifications are optional */
    }
    return () => {
      clearInterval(timer);
      document.title = original;
    };
  }, [active]);
}

/** Polls the live endpoint every second while `active`; the last value is kept after it stops. */
export function useLive(runId: string, active: boolean): LiveInfo | null {
  const [live, setLive] = useState<LiveInfo | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    if (!active) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const d = await getLive(runId);
        if (alive.current) setLive(d);
      } catch {
        /* keep the last frame and try again */
      }
      if (alive.current) timer = setTimeout(tick, 1000);
    };
    void tick();
    return () => {
      alive.current = false;
      if (timer) clearTimeout(timer);
    };
  }, [runId, active]);

  return live;
}
