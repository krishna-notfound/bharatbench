import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL } from "@/lib/format";
import type { RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STYLE: Record<RunStatus, string> = {
  queued: "bg-muted text-muted-foreground",
  analyzing: "bg-accent-info/15 text-accent-info",
  provisioning: "bg-accent-info/15 text-accent-info",
  running: "bg-primary/15 text-primary",
  scoring: "bg-primary/15 text-primary",
  done: "bg-success/15 text-success",
  failed: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground",
};

const LIVE: RunStatus[] = ["analyzing", "provisioning", "running", "scoring"];

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge variant="secondary" className={cn(STYLE[status])}>
      {LIVE.includes(status) && (
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
      )}
      {STATUS_LABEL[status]}
    </Badge>
  );
}
