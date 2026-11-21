"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useRealtime, type Realtime } from "@/lib/realtime/useRealtime";

const RealtimeContext = createContext<Realtime | null>(null);

/** One realtime session shared by the home voice screen, /chat and the floating drawer. */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const rt = useRealtime();
  return <RealtimeContext.Provider value={rt}>{children}</RealtimeContext.Provider>;
}

export function useAgent(): Realtime {
  const rt = useContext(RealtimeContext);
  if (!rt) throw new Error("useAgent must be used inside <RealtimeProvider>");
  return rt;
}
