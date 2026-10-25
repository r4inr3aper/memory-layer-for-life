import { useState } from "react";

import type { LlmCall, LlmCallOrigin, LlmCallStatus, LlmOperation } from "@/api/client";
import { useCalls, useConfig } from "@/api/hooks";
import { CallSummary } from "@/components/shared/call-summary";
import { FilterSelect } from "@/components/shared/filter-select";
import { Link } from "@/components/shared/link";
import { PageHeader } from "@/components/shared/page-header";
import { Pager } from "@/components/shared/pager";
import { EmptyState, QueryState } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  cacheHitRate,
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRelative,
  formatTokens,
  formatUsd,
  modelLabel,
} from "@/lib/format";
import { useRouteLocation } from "@/lib/router";

const PAGE_SIZE = 50;
const ALL = "all";

const ORIGINS = [
  { value: ALL, label: "Any origin" },
  { value: "pipeline", label: "Pipeline" },
  { value: "playground", label: "Playground" },
  { value: "evaluation", label: "Evaluation" },
  { value: "other", label: "Other" },
];
const OPERATIONS = [
  { value: ALL, label: "Any operation" },
  { value: "extraction", label: "Extraction" },
  { value: "judge", label: "Judge" },
  { value: "connection_check", label: "Connection check" },
];
const STATUSES = [
  { value: ALL, label: "Any result" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
];

function orNull<T extends string>(value: string): T | null {
  return value === ALL ? null : (value as T);
}

function CallLinks({ call }: { call: LlmCall }) {
  const className = "text-primary hover:underline";
  return (
    <div className="mt-4 flex flex-wrap gap-4 text-sm">
      {call.evaluation_run_id && (
        <Link to={`/evaluations/${call.evaluation_run_id}`} className={className}>
          Open the evaluation{call.evaluation_case_id ? ` (case ${call.evaluation_case_id})` : ""}
        </Link>
      )}
      {call.playground_run_id && (
        <Link to={`/playground/${call.playground_run_id}`} className={className}>
          Open the test call
        </Link>
      )}
      {call.processing_run_id && (
        <Link to={`/pipeline/${call.processing_run_id}`} className={className}>
          Open the pipeline run{call.attempt_number ? ` (attempt ${call.attempt_number})` : ""}
        </Link>
      )}
    </div>
  );
}

function CallsTable({ calls, onOpen }: { calls: LlmCall[]; onOpen: (call: LlmCall) => void }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Operation</TableHead>
          <TableHead>Model</TableHead>
          <TableHead>Result</TableHead>
          <TableHead className="text-right">Tokens in</TableHead>
          <TableHead className="text-right">Out</TableHead>
          <TableHead className="text-right">Cached</TableHead>
          <TableHead className="text-right">Cost</TableHead>
          <TableHead className="text-right">Took</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {calls.map((call) => {
          const prompt =
            call.input_tokens + call.cache_read_input_tokens + call.cache_creation_input_tokens;
          return (
            <TableRow key={call.id} className="cursor-pointer" onClick={() => onOpen(call)}>
              <TableCell className="whitespace-nowrap" title={formatDateTime(call.started_at)}>
                <button type="button" className="hover:underline">
                  {formatRelative(call.started_at)}
                </button>
              </TableCell>
              <TableCell>
                {call.operation.replace(/_/g, " ")}
                <span className="ml-1 text-xs text-muted-foreground">{call.origin}</span>
              </TableCell>
              <TableCell>
                {modelLabel(call.requested_model)}
                {call.response_model && modelLabel(call.response_model) !== modelLabel(call.requested_model) && (
                  <span className="ml-1 text-xs text-warning">
                    answered by {modelLabel(call.response_model)}
                  </span>
                )}
              </TableCell>
              <TableCell>
                <StatusBadge status={call.status} />
                {call.error_code && (
                  <span className="ml-2 font-mono text-xs text-muted-foreground">{call.error_code}</span>
                )}
              </TableCell>
              <TableCell className="tabular text-right">{formatTokens(prompt)}</TableCell>
              <TableCell className="tabular text-right">{formatTokens(call.output_tokens)}</TableCell>
              <TableCell className="tabular text-right">
                {formatPercent(
                  cacheHitRate(
                    call.cache_read_input_tokens,
                    call.cache_creation_input_tokens,
                    call.input_tokens,
                  ),
                )}
              </TableCell>
              <TableCell className="tabular text-right">
                {formatUsd(call.estimated_cost_usd, { precise: true })}
              </TableCell>
              <TableCell className="tabular text-right">{formatDuration(call.duration_ms)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function CallsPage() {
  const { query } = useRouteLocation();
  const config = useConfig();
  const [origin, setOrigin] = useState(() => query.get("origin") ?? ALL);
  const [operation, setOperation] = useState(() => query.get("operation") ?? ALL);
  const [status, setStatus] = useState(() => query.get("status") ?? ALL);
  const [model, setModel] = useState(() => query.get("model") ?? ALL);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<LlmCall | null>(null);

  const scope = {
    processing_run_id: query.get("processing_run_id"),
    evaluation_run_id: query.get("evaluation_run_id"),
    playground_run_id: query.get("playground_run_id"),
  };
  const scoped = scope.processing_run_id ?? scope.evaluation_run_id ?? scope.playground_run_id;
  const calls = useCalls({
    origin: orNull<LlmCallOrigin>(origin),
    operation: orNull<LlmOperation>(operation),
    status: orNull<LlmCallStatus>(status),
    model: orNull<string>(model),
    ...scope,
    limit: PAGE_SIZE,
    offset,
  });

  function change(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setOffset(0);
    };
  }

  return (
    <>
      <PageHeader
        title="Model calls"
        description="Every call made to a model provider: what it cost, how long it took, and how it ended. Never the content of a call."
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <FilterSelect label="Origin" value={origin} options={ORIGINS} onChange={change(setOrigin)} />
        <FilterSelect label="Operation" value={operation} options={OPERATIONS} onChange={change(setOperation)} />
        <FilterSelect label="Result" value={status} options={STATUSES} onChange={change(setStatus)} />
        <FilterSelect
          label="Model"
          value={model}
          options={[
            { value: ALL, label: "Any model" },
            ...(config.data?.models ?? []).map((option) => ({ value: option.id, label: option.display_name })),
          ]}
          onChange={change(setModel)}
        />
        {scoped && (
          <span className="text-xs text-muted-foreground">
            Showing the calls of one run.{" "}
            <Link to="/calls" className="text-primary hover:underline">
              Show all
            </Link>
          </span>
        )}
      </div>

      <QueryState
        query={calls}
        isEmpty={(data) => data.total === 0}
        empty={
          <EmptyState title="No model call matches">
            Calls are logged from the moment this log was added. Make one in the{" "}
            <Link to="/playground">Playground</Link>.
          </EmptyState>
        }
      >
        {(data) => (
          <>
            <CallsTable calls={data.items} onOpen={setOpen} />
            <Pager total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>

      <Dialog open={open !== null} onOpenChange={(isOpen) => !isOpen && setOpen(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Model call</DialogTitle>
            <DialogDescription>Facts about the call. The log never holds its content.</DialogDescription>
          </DialogHeader>
          {open && (
            <>
              <CallSummary call={open} />
              <CallLinks call={open} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
