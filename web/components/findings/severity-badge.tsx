import { Badge } from "@/components/ui/badge";
import { SEVERITY_LABEL } from "@/lib/format";
import type { Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

export const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-sev-critical/15 text-sev-critical",
  high: "bg-sev-high/15 text-sev-high",
  medium: "bg-sev-medium/15 text-sev-medium",
  low: "bg-sev-low/15 text-sev-low",
};

export const SEVERITY_BAR: Record<Severity, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge variant="secondary" className={cn(SEVERITY_STYLE[severity])}>
      {SEVERITY_LABEL[severity]}
    </Badge>
  );
}
