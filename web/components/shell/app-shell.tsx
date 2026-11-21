"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { getHealth } from "@/lib/api";
import type { Health } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "New test" },
  { href: "/runs", label: "Runs" },
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
      ? "Checking runtime…"
      : online
        ? "Emulator online"
        : h.kind === "api-down"
          ? "API unreachable"
          : "Runtime offline — static scan only";
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
      className="grid size-7 place-items-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground"
    >
      B
    </span>
  );
}

function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <nav className="ml-2 flex items-center gap-1" aria-label="Primary">
      {NAV.map((n) => {
        const active =
          pathname !== null &&
          (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href));
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary",
              active
                ? "bg-muted text-foreground"
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
      <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 md:px-8">
          <Link
            href="/"
            className="flex items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <LogoMark />
            <span className="font-semibold tracking-tight">BharatBench</span>
          </Link>
          <Suspense fallback={<NavLinks pathname={null} />}>
            <ActiveNav />
          </Suspense>
          <div className="ml-auto">
            <HealthDot />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-8">
        {children}
      </main>
    </div>
  );
}
