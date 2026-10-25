import {
  Activity,
  BarChart3,
  FlaskConical,
  ListChecks,
  Radio,
  ScrollText,
  Trophy,
  Workflow,
} from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { describeError } from "@/api/client";
import { useConfig, useConnectionCheck, useReadiness } from "@/api/hooks";
import { NavLink } from "@/components/shared/link";
import { Button } from "@/components/ui/button";
import { formatDuration, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Overview", icon: BarChart3, end: true },
  { to: "/playground", label: "Playground", icon: FlaskConical, end: false },
  { to: "/evaluations", label: "Evaluations", icon: ListChecks, end: false },
  { to: "/calls", label: "Model calls", icon: ScrollText, end: false },
  { to: "/pipeline", label: "Pipeline", icon: Workflow, end: false },
  { to: "/phase-1", label: "Phase 1 results", icon: Trophy, end: false },
];

type Tone = "ok" | "warn" | "bad" | "muted";

function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs",
        tone === "ok" && "border-success/30 text-success",
        tone === "warn" && "border-warning/40 text-warning",
        tone === "bad" && "border-destructive/40 text-destructive",
        tone === "muted" && "border-border text-muted-foreground",
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          tone === "ok" && "bg-success",
          tone === "warn" && "bg-warning",
          tone === "bad" && "bg-destructive",
          tone === "muted" && "bg-muted-foreground",
        )}
      />
      {children}
    </span>
  );
}

function StatusPills() {
  const readiness = useReadiness();
  const config = useConfig();
  const check = useConnectionCheck();

  const apiTone: Tone = readiness.isPending ? "muted" : readiness.isError ? "bad" : "ok";
  const apiLabel = readiness.isPending
    ? "Checking the API"
    : readiness.isError
      ? "API or database unreachable"
      : "API and database ready";

  function runCheck() {
    check.mutate(undefined, {
      onSuccess: (result) => {
        if (result.ok) {
          const call = result.call;
          toast.success(`Connected to ${result.model}`, {
            description: call
              ? `${formatDuration(call.duration_ms)}, about ${formatUsd(call.estimated_cost_usd, { precise: true })}`
              : undefined,
          });
        } else {
          toast.error(result.error_message ?? "The connection check failed.", {
            description: result.error_code ?? undefined,
          });
        }
      },
      onError: (error) => toast.error(describeError(error)),
    });
  }

  return (
    <div className="flex items-center gap-2">
      <Pill tone={apiTone}>{apiLabel}</Pill>
      {config.data && (
        <Pill tone={config.data.provider_configured ? "ok" : "warn"}>
          {config.data.provider_configured ? "API key set" : "No API key"}
        </Pill>
      )}
      {config.data?.evaluation_running && (
        <Pill tone="warn">
          <Activity className="size-3 animate-pulse" /> Evaluation running
        </Pill>
      )}
      <Button
        size="sm"
        variant="outline"
        onClick={runCheck}
        disabled={check.isPending || config.data?.provider_configured === false}
        title="Makes one tiny model call. It is logged and costs a fraction of a cent."
      >
        <Radio className="size-3.5" />
        {check.isPending ? "Checking" : "Check connection"}
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const config = useConfig();
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-5 md:flex">
        <div className="px-2">
          <div className="text-sm font-semibold tracking-tight">Second Brain</div>
          <div className="text-xs text-muted-foreground">Test console</div>
        </div>
        <nav className="mt-6 flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={(active) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                )
              }
            >
              <item.icon className="size-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        {config.data && (
          <dl className="mt-auto space-y-1 px-2 text-xs text-muted-foreground">
            <div className="truncate" title={config.data.default_model}>
              Model <span className="text-foreground">{config.data.default_model}</span>
            </div>
            <div>
              Effort <span className="text-foreground">{config.data.default_effort}</span>
            </div>
            <div>
              Timezone <span className="text-foreground">{config.data.default_timezone}</span>
            </div>
            <div>
              Environment <span className="text-foreground">{config.data.environment}</span>
            </div>
          </dl>
        )}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center justify-between gap-3 border-b bg-background/90 px-4 backdrop-blur md:px-8">
          <nav className="flex gap-1 overflow-x-auto md:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={(active) =>
                  cn(
                    "whitespace-nowrap rounded-md px-2 py-1 text-xs",
                    active ? "bg-accent text-foreground" : "text-muted-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto">
            <StatusPills />
          </div>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}
