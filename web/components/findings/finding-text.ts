import type { Finding } from "@/lib/types";

export function findingSourceLabel(f: Finding): string {
  return f.source === "runtime" ? "Observed on emulator" : "Found in APK scan";
}

/** Plain-language impact line built only from the finding's own data. */
export function impactSentence(f: Finding): string {
  if (f.impact) {
    const pct = Math.round(f.impact.users_exposed * 100);
    if (pct > 0) return `Could affect about ${pct}% of your users. ${f.description}`;
  }
  return f.description;
}
