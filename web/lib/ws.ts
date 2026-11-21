"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, getEvents } from "@/lib/api";
import type { RunEvent } from "@/lib/types";

const WS_URL = API_URL.replace(/^http/, "ws");

export type RunEventsState = {
  events: RunEvent[];
  /** WebSocket currently open */
  connected: boolean;
  /** A `done` or `error` event was received; stream is complete */
  finished: boolean;
};

/**
 * Subscribe to a run's event stream (WS /ws/runs/{id}).
 * - dedupes by seq, keeps events ordered
 * - reconnects with exponential backoff, resuming with ?after_seq=<last seq>
 * - while the socket is down, falls back to polling GET /events?after_seq=
 * Mount with `key={runId}` so state resets per run.
 */
export function useRunEvents(
  runId: string,
  onEvent?: (e: RunEvent) => void,
): RunEventsState {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [finished, setFinished] = useState(false);
  const onEventRef = useRef(onEvent);

  useEffect(() => {
    onEventRef.current = onEvent;
  });

  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let pingTimer: ReturnType<typeof setInterval> | undefined;
    let lastSeq = -1;
    let done = false;

    const ingest = (incoming: RunEvent[]) => {
      const fresh = incoming.filter((e) => e.seq > lastSeq);
      if (fresh.length === 0) return;
      fresh.sort((a, b) => a.seq - b.seq);
      const accepted: RunEvent[] = [];
      for (const e of fresh) {
        if (e.seq > lastSeq) {
          lastSeq = e.seq;
          accepted.push(e);
        }
      }
      setEvents((prev) => [...prev, ...accepted]);
      for (const e of accepted) {
        onEventRef.current?.(e);
        if (e.type === "done" || e.type === "error") done = true;
      }
      if (done) {
        setFinished(true);
        cleanup();
      }
    };

    const stopPolling = () => {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const startPolling = () => {
      if (pollTimer || done) return;
      const tick = async () => {
        try {
          const list = await getEvents(runId, lastSeq);
          if (!disposed) ingest(list);
        } catch {
          /* API down; keep trying */
        }
      };
      void tick();
      pollTimer = setInterval(tick, 3000);
    };

    function cleanup() {
      stopPolling();
      if (pingTimer) clearInterval(pingTimer);
      if (retryTimer) clearTimeout(retryTimer);
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        ws = null;
      }
      setConnected(false);
    }

    const connect = () => {
      if (disposed || done) return;
      const url = `${WS_URL}/ws/runs/${encodeURIComponent(runId)}${
        lastSeq >= 0 ? `?after_seq=${lastSeq}` : ""
      }`;
      let sock: WebSocket;
      try {
        sock = new WebSocket(url);
      } catch {
        scheduleRetry();
        return;
      }
      ws = sock;
      sock.onopen = () => {
        retry = 0;
        stopPolling();
        setConnected(true);
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (sock.readyState === WebSocket.OPEN) {
            sock.send(JSON.stringify({ type: "ping" }));
          }
        }, 20000);
      };
      sock.onmessage = (m) => {
        try {
          const data = JSON.parse(String(m.data)) as Record<string, unknown>;
          if (data.type === "pong" || typeof data.seq !== "number") return;
          ingest([data as unknown as RunEvent]);
        } catch {
          /* ignore malformed frame */
        }
      };
      sock.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        setConnected(false);
        ws = null;
        if (!disposed && !done) {
          startPolling();
          scheduleRetry();
        }
      };
      sock.onerror = () => {
        try {
          sock.close();
        } catch {
          /* ignore */
        }
      };
    };

    function scheduleRetry() {
      if (disposed || done) return;
      const delay = Math.min(15000, 1000 * 2 ** retry);
      retry += 1;
      retryTimer = setTimeout(connect, delay);
    }

    connect();

    return () => {
      disposed = true;
      cleanup();
    };
  }, [runId]);

  return { events, connected, finished };
}
