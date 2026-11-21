/** Shared surface classes for the light lavender system (see context/ui-context.md). */
export const CARD =
  "rounded-3xl border border-border bg-card shadow-[0_1px_2px_rgba(30,27,46,0.04),0_8px_24px_rgba(124,92,255,0.06)]";

export const CARD_HOVER =
  "transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-[0_1px_2px_rgba(30,27,46,0.04),0_12px_32px_rgba(124,92,255,0.12)]";

export const PRIMARY_CTA =
  "inline-flex h-12 items-center justify-center gap-2 rounded-full bg-primary px-7 text-base font-medium text-primary-foreground shadow-[0_8px_24px_rgba(124,92,255,0.3)] outline-none transition-all hover:bg-primary/90 focus-visible:ring-4 focus-visible:ring-ring/30 disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none";

export const SECONDARY_CTA =
  "inline-flex h-12 items-center justify-center gap-2 rounded-full border border-border bg-card px-6 text-base font-medium text-foreground outline-none transition-colors hover:bg-accent focus-visible:ring-4 focus-visible:ring-ring/30";
