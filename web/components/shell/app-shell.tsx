"use client";

import { AccountButton } from "@/components/auth";
import { TalkButton } from "@/components/voice/talk-button";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { getHealth } from "@/lib/api";
import type { Health } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/new", label: "New test" },
  { href: "/runs", label: "Sessions" },
];

type HealthState =
  | { kind: "loading" }
  | { kind: "online" }
  | { kind: "offline"; detail: string }
  | { kind: "api-down" };

function useHealth(): HealthState {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const check = useCallback(async () => {
    try {
      const h: Health = await getHealth();
      setState(
        h.harness.reachable
          ? { kind: "online" }
          : { kind: "offline", detail: h.harness.detail },
      );
    } catch {
      setState({ kind: "api-down" });
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, [check]);
  return state;
}

function HealthDot() {
  const h = useHealth();
  const online = h.kind === "online";
  const label =
    h.kind === "loading"
      ? "Checking…"
      : online
        ? "Emulator ready"
        : h.kind === "api-down"
          ? "Offline"
          : "Emulator offline";
  const title = h.kind === "offline" ? h.detail : label;
  return (
    <div
      className="flex items-center gap-2 text-xs text-muted-foreground"
      title={title}
      role="status"
      aria-live="polite"
    >
      <span
        className={cn(
          "size-2 rounded-full",
          online
            ? "bg-success"
            : h.kind === "api-down"
              ? "bg-destructive"
              : "bg-muted-foreground",
          h.kind === "loading" && "animate-pulse",
        )}
      />
      <span className="hidden sm:inline">{label}</span>
      <span className="sr-only sm:hidden">{label}</span>
    </div>
  );
}

function LogoMark() {
  return (
    <span
      aria-hidden
      className="block size-7 rounded-full bg-linear-to-br from-orb-a via-orb-b to-orb-c shadow-[0_0_0_4px_rgba(124,92,255,0.10)]"
    />
  );
}

function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <nav className="flex items-center gap-0 sm:ml-3 sm:gap-0.5" aria-label="Primary">
      {NAV.map((n) => {
        const active =
          pathname !== null &&
          pathname.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "whitespace-nowrap rounded-full px-2.5 py-1.5 text-sm outline-none sm:px-3.5 transition-colors focus-visible:ring-2 focus-visible:ring-primary",
              active
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

function ActiveNav() {
  return <NavLinks pathname={usePathname()} />;
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 bg-background/70 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-1.5 px-4 sm:gap-3 md:px-8">
          <Link
            href="/"
            className="flex shrink-0 items-center gap-2 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <LogoMark />
            <span className="font-semibold tracking-tight max-[379px]:sr-only">BharatBench</span>
          </Link>
          <Suspense fallback={<NavLinks pathname={null} />}>
            <ActiveNav />
          </Suspense>
          <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-3">
            <HealthDot />
            <TalkButton />
            <AccountButton />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 pb-24 pt-4 md:px-8">
        {children}
      </main>
    </div>
  );
}
