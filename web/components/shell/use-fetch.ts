"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type FetchState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  /** Re-fetch without flipping back to the loading skeleton */
  refresh: () => Promise<void>;
};

/**
 * Minimal fetch hook: initial `loading`, `error` with retry, optional polling.
 * `pollMs` may be a function of the latest data to stop polling when done.
 */
export function useFetch<T>(
  fn: () => Promise<T>,
  pollMs?: number | ((data: T | null) => number | null),
): FetchState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  const dataRef = useRef<T | null>(null);
  const pollRef = useRef(pollMs);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    fnRef.current = fn;
    pollRef.current = pollMs;
  });

  const refresh = useCallback(async () => {
    try {
      const d = await fnRef.current();
      dataRef.current = d;
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      await refresh();
      if (cancelled) return;
      const p = pollRef.current;
      const ms = typeof p === "function" ? p(dataRef.current) : p;
      if (ms) timer = setTimeout(loop, ms);
    };
    void loop();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [refresh, nonce]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setNonce((n) => n + 1);
  }, []);

  return { data, error, loading, reload, refresh };
}
