"use client";

import { ChevronDown } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { CARD } from "@/components/shell/surface";
import type { Fidelity, Profile, ProfileId } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Friendly names; descriptions still come from the API. */
export const FRIENDLY_NAME: Record<ProfileId, string> = {
  baseline: "Baseline",
  budget_2gb: "Budget Android",
  flaky_network: "Weak Network",
  low_storage: "Low Storage",
  battery_saver: "Battery Saver",
  process_death: "App restarts",
};

const FIDELITY_LABEL: Record<Fidelity, string> = {
  controlled: "Controlled",
  approximated: "Approximated",
  unsupported: "Not simulated",
};

export function FidelityTag({ fidelity }: { fidelity: Fidelity }) {
  return (
    <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
      {FIDELITY_LABEL[fidelity]}
    </span>
  );
}

export function ProfileList({
  profiles,
  selected,
  onToggle,
  disabled,
  showHow,
}: {
  profiles: Profile[];
  selected: Set<ProfileId>;
  onToggle: (id: ProfileId, on: boolean) => void;
  disabled?: boolean;
  /** Advanced mode: reveal the technical "how" text per condition. */
  showHow?: boolean;
}) {
  if (profiles.length === 0) {
    return (
      <p className="rounded-3xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        No test conditions are available right now.
      </p>
    );
  }

  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {profiles.map((p) => {
        const on = selected.has(p.id);
        return (
          <li key={p.id}>
            <label
              htmlFor={`profile-${p.id}`}
              className={cn(
                CARD,
                "flex h-full cursor-pointer items-start gap-3 p-4 transition-colors",
                on ? "border-primary/60 bg-accent/40" : "hover:border-primary/30",
                disabled && "cursor-not-allowed opacity-70",
              )}
            >
              <Checkbox
                id={`profile-${p.id}`}
                className="mt-0.5"
                checked={on}
                disabled={disabled}
                onCheckedChange={(v) => onToggle(p.id, v === true)}
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">
                    {FRIENDLY_NAME[p.id] ?? p.name}
                  </span>
                  <FidelityTag fidelity={p.fidelity} />
                </span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {p.description}
                </span>
                {showHow && (
                  <span className="mt-2 block rounded-2xl bg-muted p-2.5 text-xs text-muted-foreground">
                    {p.how}
                  </span>
                )}
              </span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

export function AdvancedDisclosure({
  open,
  onToggle,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex items-center gap-1 rounded-full px-1 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
      >
        Advanced
        <ChevronDown
          className={cn("size-4 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && <div className="mt-3 space-y-3">{children}</div>}
    </div>
  );
}
