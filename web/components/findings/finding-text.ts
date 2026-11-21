import type { Finding } from "@/lib/types";

export function findingSourceLabel(f: Finding): string {
  return f.source === "runtime" ? "Observed on emulator" : "Found in APK scan";
}

const PROFILE_NAMES: Record<string, string> = {
  baseline: "a normal phone",
  budget_2gb: "a budget phone",
  flaky_network: "an unreliable network",
  low_storage: "low storage",
  battery_saver: "battery saver",
  process_death: "app restart",
};

/** Replace raw profile ids (e.g. `flaky_network`) in a finding title with plain words. */
export function findingTitle(f: Pick<Finding, "title">): string {
  return f.title.replace(
    /\bon (baseline|budget_2gb|flaky_network|low_storage|battery_saver|process_death)\b/g,
    (_m, id: string) => `on ${PROFILE_NAMES[id]}`,
  );
}

/** Plain-language impact line built only from the finding's own data. */
export function impactSentence(f: Finding): string {
  if (f.impact) {
    const pct = Math.round(f.impact.users_exposed * 100);
    if (pct > 0) return `Could affect about ${pct}% of your users. ${f.description}`;
  }
  return f.description;
}
