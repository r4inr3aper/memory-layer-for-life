import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  type ConsoleConfig,
  describeError,
  type EffortLevel,
  type ModelOption,
  type PlaygroundRun,
} from "@/api/client";
import {
  useConfig,
  useContract,
  useIngest,
  usePlaygroundRun,
  usePlaygroundRuns,
  useRunPlayground,
} from "@/api/hooks";
import { CallSummary } from "@/components/shared/call-summary";
import { ExtractionView } from "@/components/shared/extraction-view";
import { FilterSelect } from "@/components/shared/filter-select";
import { JsonView } from "@/components/shared/json-view";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { EmptyState, QueryState } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { asExtractionOutput } from "@/lib/extraction";
import {
  formatDuration,
  formatRelative,
  formatTokens,
  formatUsd,
  modelLabel,
} from "@/lib/format";
import { navigate } from "@/lib/router";

interface Draft {
  id: string;
  text: string;
  sentAt: string;
}

/** The current local time in the form a datetime-local input takes. */
function localNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function newDraft(): Draft {
  return { id: crypto.randomUUID(), text: "", sentAt: localNow() };
}

function toIso(local: string): string | null {
  if (!local) return null;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** A rough cost of one test call: a full prompt written to the cache and a short answer. */
function typicalCost(model: ModelOption | undefined): number | null {
  if (!model?.prices) return null;
  const { cache_write_usd_per_mtok, input_usd_per_mtok, output_usd_per_mtok } = model.prices;
  return (7300 * cache_write_usd_per_mtok + 150 * input_usd_per_mtok + 600 * output_usd_per_mtok) / 1e6;
}

function TestForm({ config }: { config: ConsoleConfig }) {
  const [drafts, setDrafts] = useState<Draft[]>(() => [newDraft()]);
  const [model, setModel] = useState(config.default_model);
  const [effort, setEffort] = useState(config.default_effort);
  const [timezone, setTimezone] = useState(config.default_timezone);
  const [throughPipeline, setThroughPipeline] = useState(false);
  const test = useRunPlayground();
  const ingest = useIngest();

  const busy = test.isPending || ingest.isPending;
  const ready = drafts.every((draft) => draft.text.trim() !== "");
  const cost = typicalCost(config.models.find((option) => option.id === model));

  function update(id: string, change: Partial<Draft>) {
    setDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, ...change } : draft)));
  }

  function submit() {
    if (throughPipeline) {
      ingest.mutate(
        {
          messages: drafts.map((draft) => ({
            source: "manual_capture" as const,
            content: draft.text,
            source_created_at: toIso(draft.sentAt),
          })),
        },
        {
          onSuccess: (unit) => {
            toast.success("Captured. The pipeline is processing it.");
            navigate(`/pipeline/${unit.processing_run.id}`);
          },
          onError: (error) => toast.error(describeError(error)),
        },
      );
      return;
    }
    test.mutate(
      {
        messages: drafts.map((draft) => ({ text: draft.text, sent_at: toIso(draft.sentAt) })),
        model,
        effort: effort as EffortLevel,
        timezone,
      },
      {
        onSuccess: (run) => navigate(`/playground/${run.id}`),
        onError: (error) => toast.error(describeError(error)),
      },
    );
  }

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="space-y-3">
        {drafts.map((draft, index) => (
          <div key={draft.id} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor={`text-${draft.id}`}>
                {drafts.length > 1 ? `Message ${index + 1}` : "Message"}
              </Label>
              {drafts.length > 1 && (
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Remove message ${index + 1}`}
                  onClick={() => setDrafts((current) => current.filter((item) => item.id !== draft.id))}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </div>
            <Textarea
              id={`text-${draft.id}`}
              value={draft.text}
              rows={3}
              placeholder="Type a note exactly as you would send it to yourself"
              onChange={(event) => update(draft.id, { text: event.target.value })}
            />
            <Input
              type="datetime-local"
              aria-label={`When message ${index + 1} was written`}
              value={draft.sentAt}
              className="w-56"
              onChange={(event) => update(draft.id, { sentAt: event.target.value })}
            />
          </div>
        ))}
        {drafts.length < config.limits.max_unit_messages && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setDrafts((current) => [...current, newDraft()])}
          >
            <Plus className="size-3.5" /> Add a message to this unit
          </Button>
        )}
        <p className="text-xs text-muted-foreground">
          Messages in one unit are read together, in order, as one thought.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-md border p-3">
        <Switch id="through-pipeline" checked={throughPipeline} onCheckedChange={setThroughPipeline} />
        <div>
          <Label htmlFor="through-pipeline">Save through the pipeline</Label>
          <p className="mt-1 text-xs text-muted-foreground">
            {throughPipeline
              ? "The note is stored as a real message and becomes proposed memories. It uses the configured model."
              : "Dry run: the model is called and checked, and nothing is stored as a message or a memory."}
          </p>
        </div>
      </div>

      {!throughPipeline && (
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2 space-y-1.5">
            <Label>Model</Label>
            <FilterSelect
              label="Model"
              value={model}
              className="w-full"
              options={config.models.map((option) => ({
                value: option.id,
                label: option.is_default ? `${option.display_name} (configured)` : option.display_name,
              }))}
              onChange={setModel}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Effort</Label>
            <FilterSelect
              label="Effort"
              value={effort}
              className="w-full"
              options={config.effort_levels.map((level) => ({ value: level, label: level }))}
              onChange={setEffort}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="timezone">Timezone of the writer</Label>
            <Input id="timezone" value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          </div>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={busy || !ready || !config.provider_configured}>
          {busy ? "Calling the model" : throughPipeline ? "Capture and process" : "Run test call"}
        </Button>
        <span className="text-xs text-muted-foreground">
          {!config.provider_configured
            ? "No API key is configured, so no call can be made."
            : !throughPipeline && cost !== null
              ? `One model call, roughly ${formatUsd(cost, { precise: true })}.`
              : "One model call."}
        </span>
      </div>
    </form>
  );
}

function ContractDialog() {
  const contract = useContract();
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Output format
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Extraction output format</DialogTitle>
          <DialogDescription>
            Every answer must satisfy this contract before anything is stored.
          </DialogDescription>
        </DialogHeader>
        <QueryState query={contract}>
          {(data) => (
            <Tabs defaultValue="validated">
              <p className="mb-3 text-xs text-muted-foreground">
                Contract {data.schema_version}, prompt {data.prompt_version}, pipeline{" "}
                {data.pipeline_version}.
              </p>
              <TabsList>
                <TabsTrigger value="validated">Validated by the application</TabsTrigger>
                <TabsTrigger value="provider">Sent to the model</TabsTrigger>
              </TabsList>
              <TabsContent value="validated">
                <JsonView value={data.output_schema} />
              </TabsContent>
              <TabsContent value="provider">
                <JsonView value={data.provider_schema} />
              </TabsContent>
            </Tabs>
          )}
        </QueryState>
      </DialogContent>
    </Dialog>
  );
}

function RunResult({ run }: { run: PlaygroundRun }) {
  const output = asExtractionOutput(run.output);
  const call = run.call;
  const billing = run.error_code?.includes("BILLING") ?? false;
  const firstTab = output ? "memories" : run.raw_output ? "raw" : "input";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <StatusBadge status={run.status} />
        <span>
          {modelLabel(run.requested_model)}, effort {run.effort}
        </span>
        {call && (
          <span className="tabular text-muted-foreground">
            {formatDuration(call.duration_ms)}, {formatTokens(call.input_tokens + call.cache_read_input_tokens + call.cache_creation_input_tokens)}{" "}
            tokens in, {formatTokens(call.output_tokens)} out, about{" "}
            {formatUsd(call.estimated_cost_usd, { precise: true })}
          </span>
        )}
        <span className="text-muted-foreground">{formatRelative(run.created_at)}</span>
      </div>

      {run.status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle className="font-mono text-xs">{run.error_code}</AlertTitle>
          <AlertDescription>
            {run.error_message}
            {billing && " Add credit in the Anthropic Console, then run the test again."}
          </AlertDescription>
        </Alert>
      )}
      {run.corrections.length > 0 && (
        <Alert>
          <AlertTitle>The application corrected the model's output</AlertTitle>
          <AlertDescription>{run.corrections.join(". ")}</AlertDescription>
        </Alert>
      )}

      <Tabs defaultValue={firstTab}>
        <TabsList>
          {output && <TabsTrigger value="memories">Memories</TabsTrigger>}
          {output && <TabsTrigger value="json">Validated JSON</TabsTrigger>}
          {run.raw_output && <TabsTrigger value="raw">Raw model output</TabsTrigger>}
          {call && <TabsTrigger value="call">Model call</TabsTrigger>}
          <TabsTrigger value="input">Input</TabsTrigger>
        </TabsList>
        {output && (
          <TabsContent value="memories">
            <ExtractionView output={output} />
          </TabsContent>
        )}
        {output && (
          <TabsContent value="json">
            <JsonView value={run.output} />
          </TabsContent>
        )}
        {run.raw_output && (
          <TabsContent value="raw">
            <JsonView value={run.raw_output} />
          </TabsContent>
        )}
        {call && (
          <TabsContent value="call">
            <CallSummary call={call} />
          </TabsContent>
        )}
        <TabsContent value="input">
          <ol className="space-y-2 text-sm">
            {run.messages.map((message) => (
              <li key={message.index} className="rounded-md border p-3">
                <div className="mb-1 text-xs text-muted-foreground">
                  Message {message.index}
                  {message.sent_at && `, written ${new Date(message.sent_at).toLocaleString()}`}
                </div>
                <div className="whitespace-pre-wrap">{message.text}</div>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs text-muted-foreground">Timezone {run.timezone_name}</p>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function History({ currentId }: { currentId: string | null }) {
  const history = usePlaygroundRuns({ limit: 12 });
  return (
    <QueryState
      query={history}
      isEmpty={(data) => data.items.length === 0}
      empty={<p className="text-sm text-muted-foreground">No test call has been made yet.</p>}
    >
      {(data) => (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Note</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Result</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((item) => (
              <TableRow key={item.id} data-state={item.id === currentId ? "selected" : undefined}>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                  {formatRelative(item.created_at)}
                </TableCell>
                <TableCell className="max-w-md truncate">
                  <Link to={`/playground/${item.id}`} className="hover:underline">
                    {item.preview || "(empty)"}
                  </Link>
                  {item.message_count > 1 && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      +{item.message_count - 1} more
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-xs">{modelLabel(item.requested_model)}</TableCell>
                <TableCell>
                  <StatusBadge status={item.status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </QueryState>
  );
}

function Result({ runId }: { runId: string }) {
  const run = usePlaygroundRun(runId);
  return <QueryState query={run}>{(data) => <RunResult key={data.id} run={data} />}</QueryState>;
}

export function PlaygroundPage({ runId }: { runId: string | null }) {
  const config = useConfig();
  return (
    <>
      <PageHeader
        title="Playground"
        description="Send one note to the model and see exactly what comes back, and in what format."
        actions={<ContractDialog />}
      />
      <div className="grid gap-10 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
        <section>
          <SectionTitle>Test call</SectionTitle>
          <QueryState query={config}>{(data) => <TestForm config={data} />}</QueryState>
        </section>
        <section className="min-w-0">
          <SectionTitle>Result</SectionTitle>
          {runId === null ? (
            <EmptyState title="No test selected">
              Run a test call, or open an earlier one from the list below.
            </EmptyState>
          ) : (
            <Result runId={runId} />
          )}
        </section>
      </div>
      <section className="mt-12">
        <SectionTitle>Recent test calls</SectionTitle>
        <History currentId={runId} />
      </section>
    </>
  );
}
