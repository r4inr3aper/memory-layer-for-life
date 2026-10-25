import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** One number with its label. Dense rows of these replace big metric cards. */
export function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 border-l pl-3 first:border-l-0 first:pl-0", className)}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="tabular mt-0.5 truncate text-lg font-medium leading-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6", className)}>
      {children}
    </div>
  );
}
