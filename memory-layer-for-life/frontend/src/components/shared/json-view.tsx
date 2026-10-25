import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Pretty-printed JSON with a copy button. For model output and API payloads. */
export function JsonView({ value, className, maxHeight = "28rem" }: { value: unknown; className?: string; maxHeight?: string }) {
  const [copied, setCopied] = useState(false);
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // The clipboard is not available in every context; the text is still visible.
    }
  }

  return (
    <div className={cn("relative rounded-md border bg-muted/30", className)}>
      <Button size="icon" variant="ghost" className="absolute right-1 top-1 size-7" onClick={copy} aria-label="Copy">
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </Button>
      <pre className="overflow-auto p-3 pr-10 font-mono text-xs leading-relaxed" style={{ maxHeight }}>
        {text}
      </pre>
    </div>
  );
}
