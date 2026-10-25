import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type KeyValueEntry = { label: string; value: ReactNode; mono?: boolean };

/** A compact definition list for the details of one record. */
export function KeyValues({ entries, className }: { entries: KeyValueEntry[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm", className)}>
      {entries.map((entry) => (
        <div key={entry.label} className="contents">
          <dt className="text-muted-foreground">{entry.label}</dt>
          <dd className={cn("min-w-0 break-words", entry.mono && "font-mono text-xs")}>
            {entry.value ?? <span className="text-muted-foreground">n/a</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
