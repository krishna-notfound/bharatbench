"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type { Fidelity, Profile, ProfileId } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIDELITY: Record<Fidelity, { label: string; cls: string }> = {
  controlled: { label: "Controlled", cls: "bg-success/15 text-success" },
  approximated: {
    label: "Approximated",
    cls: "bg-sev-medium/15 text-sev-medium",
  },
  unsupported: { label: "Not simulated", cls: "bg-muted text-muted-foreground" },
};

export function FidelityBadge({ fidelity }: { fidelity: Fidelity }) {
  const f = FIDELITY[fidelity];
  return (
    <Badge variant="secondary" className={f.cls}>
      {f.label}
    </Badge>
  );
}

export function ProfileList({
  profiles,
  selected,
  onToggle,
  disabled,
}: {
  profiles: Profile[];
  selected: Set<ProfileId>;
  onToggle: (id: ProfileId, on: boolean) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState<ProfileId | null>(null);

  if (profiles.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        The API returned no selectable profiles.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {profiles.map((p) => {
        const on = selected.has(p.id);
        const expanded = open === p.id;
        return (
          <li
            key={p.id}
            className={cn(
              "rounded-xl border bg-card transition-colors",
              on ? "border-primary/50" : "border-border",
            )}
          >
            <div className="flex items-start gap-3 p-3">
              <Checkbox
                id={`profile-${p.id}`}
                className="mt-0.5"
                checked={on}
                disabled={disabled}
                onCheckedChange={(v) => onToggle(p.id, v === true)}
                aria-label={p.name}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <label
                    htmlFor={`profile-${p.id}`}
                    className="cursor-pointer text-sm font-medium"
                  >
                    {p.name}
                  </label>
                  <FidelityBadge fidelity={p.fidelity} />
                </div>
                <p className="mt-0.5 text-sm text-muted-foreground">
                  {p.description}
                </p>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : p.id)}
                  className="mt-1.5 flex items-center gap-1 rounded text-xs text-accent-info outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  How
                  <ChevronDown
                    className={cn(
                      "size-3 transition-transform",
                      expanded && "rotate-180",
                    )}
                  />
                </button>
                {expanded && (
                  <p className="mt-1.5 rounded-md bg-muted p-2 text-xs text-muted-foreground">
                    {p.how}
                  </p>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
