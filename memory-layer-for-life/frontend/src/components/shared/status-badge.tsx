import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TONES: Record<string, string> = {
  succeeded: "border-success/40 text-success",
  completed: "border-success/40 text-success",
  passed: "border-success/40 text-success",
  ready: "border-success/40 text-success",
  running: "border-warning/40 text-warning",
  queued: "border-border text-muted-foreground",
  proposed: "border-border text-muted-foreground",
  needs_review: "border-warning/40 text-warning",
  not_evaluated: "border-border text-muted-foreground",
  interrupted: "border-warning/40 text-warning",
  cancelled: "border-border text-muted-foreground",
  failed: "border-destructive/40 text-destructive",
  active: "border-success/40 text-success",
  extract: "border-chart-2/40 text-chart-2",
  context: "border-chart-3/40 text-chart-3",
  abstain: "border-border text-muted-foreground",
};

/** A status word with a colour the whole console agrees on. */
export function StatusBadge({ status, className }: { status: string | null | undefined; className?: string }) {
  if (!status) return <span className="text-muted-foreground">n/a</span>;
  return (
    <Badge variant="outline" className={cn("font-normal", TONES[status] ?? "border-border", className)}>
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
