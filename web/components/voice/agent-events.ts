export const OPEN_AGENT_EVENT = "bb:open-agent";

/** Open the global agent panel from anywhere (dispatches a window CustomEvent). */
export function openAgentPanel(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(OPEN_AGENT_EVENT));
}

/** Friendly, past-tense names for the voice agent's tools (contracts section 6). */
export const TOOL_LABEL: Record<string, string> = {
  list_profiles: "Checked the device profiles",
  list_runs: "Looked at your sessions",
  start_test: "Started a test",
  get_run_status: "Checked on a test",
  list_findings: "Looked at the issues",
  explain_finding: "Read an issue closely",
};

export function toolLabel(name: string): string {
  return TOOL_LABEL[name] ?? name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
