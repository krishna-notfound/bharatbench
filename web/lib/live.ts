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
