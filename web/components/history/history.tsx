"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { getAccessToken } from "@/lib/supabase/client";

export type ConversationSummary = {
  id: string;
  mode: "voice" | "text";
  created_at: string;
  title: string | null;
};

export type HistoryMessage = {
  role: "user" | "assistant" | "tool";
  content: string;
  interrupted: boolean;
  meta: Record<string, unknown> | null;
  created_at: string;
};

async function authedGet<T>(path: string): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new Error("Sign in to see your history.");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new Error("Cannot reach the API.");
  }
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

function useAuthedList<T>(path: string) {
  const [state, setState] = useState<{
    path: string;
    data: T | null;
    error: string | null;
  } | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let active = true;
    authedGet<T>(path)
      .then((data) => active && setState({ path, data, error: null }))
      .catch(
        (e: unknown) =>
          active &&
          setState({
            path,
            data: null,
            error: e instanceof Error ? e.message : "Something went wrong",
          }),
      );
    return () => {
      active = false;
    };
  }, [path, nonce]);

  const current = state && state.path === path ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: current === null,
    reload: () => setNonce((n) => n + 1),
  };
}

export function ConversationList({
  onSelect,
  selectedId,
}: {
  onSelect?: (id: string) => void;
  selectedId?: string | null;
}) {
  const { data, error, loading } = useAuthedList<ConversationSummary[]>(
    "/api/conversations",
  );
  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error) return <p role="alert" className="text-sm text-muted-foreground">{error}</p>;
  if (!data?.length)
    return <p className="text-sm text-muted-foreground">No conversations yet.</p>;
  return (
    <ul className="space-y-1">
      {data.map((c) => (
        <li key={c.id}>
          <button
            type="button"
            onClick={() => onSelect?.(c.id)}
            className={`w-full rounded-xl px-3 py-2 text-left text-sm transition-colors hover:bg-muted ${
              selectedId === c.id ? "bg-muted" : ""
            }`}
          >
            <span className="block truncate font-medium">
              {c.title || "New conversation"}
            </span>
            <span className="text-xs text-muted-foreground">
              {c.mode} · {new Date(c.created_at).toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function MessagesView({ conversationId }: { conversationId: string }) {
  const { data, error, loading } = useAuthedList<HistoryMessage[]>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
  );
  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error) return <p role="alert" className="text-sm text-muted-foreground">{error}</p>;
  if (!data?.length)
    return <p className="text-sm text-muted-foreground">No messages.</p>;
  return (
    <ol className="space-y-3">
      {data
        .filter((m) => m.role !== "tool")
        .map((m, i) => (
          <li
            key={`${m.created_at}-${i}`}
            className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm ${
              m.role === "user"
                ? "ml-auto bg-primary text-primary-foreground"
                : "bg-muted"
            }`}
          >
            {m.content}
            {m.interrupted && (
              <span className="ml-1 text-xs opacity-70">(interrupted)</span>
            )}
          </li>
        ))}
    </ol>
  );
}

/** List + messages side by side (stacked on small screens). */
export function ConversationHistory() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="grid gap-6 md:grid-cols-[280px_1fr]">
      <ConversationList onSelect={setSelected} selectedId={selected} />
      {selected ? (
        <MessagesView key={selected} conversationId={selected} />
      ) : (
        <p className="text-sm text-muted-foreground">Pick a conversation.</p>
      )}
    </div>
  );
}
