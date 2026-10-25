import { useState } from "react";
import { toast } from "sonner";

import { describeError, type MemoryType, type ProcessingStatus } from "@/api/client";
import {
  useMemories,
  useMemory,
  usePipelineStats,
  useReplay,
  useRun,
  useRuns,
} from "@/api/hooks";
import { FilterSelect } from "@/components/shared/filter-select";
import { JsonView } from "@/components/shared/json-view";
import { KeyValues } from "@/components/shared/key-value";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { Pager } from "@/components/shared/pager";
import { EmptyState, QueryState } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDateTime, formatPercent, formatRelative, truncate } from "@/lib/format";
import { navigate } from "@/lib/router";

const PAGE_SIZE = 50;
const ALL = "all";

const RUN_STATUSES = [
  { value: ALL, label: "Any status" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "needs_review", label: "Needs review" },
  { value: "failed", label: "Failed" },
];

function MemoryDetail({ memoryId }: { memoryId: string }) {
  const memory = useMemory(memoryId);
  return (
    <QueryState query={memory}>
      {(data) => (
        <div className="space-y-6 text-sm">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="font-normal">
                {data.memory_type.replace(/_/g, " ")}
              </Badge>
              <StatusBadge status={data.status} />
              <span className="text-xs text-muted-foreground">
                confidence {formatPercent(data.confidence)}
              </span>
            </div>
            <p className="text-base">{data.content}</p>
          </div>
          <section>
            <SectionTitle hint="every memory is traceable to what was written">Evidence</SectionTitle>
            <ul className="space-y-2">
              {data.sources.map((source) => (
                <li key={`${source.raw_message_id}-${source.source_role}`} className="rounded-md border p-3">
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline" className="font-normal">
                      {source.source_role}
                    </Badge>
                    {source.source_created_at && <span>written {formatDateTime(source.source_created_at)}</span>}
                    <Link to={`/pipeline/${source.processing_run_id}`} className="text-primary hover:underline">
                      its run
                    </Link>
                  </div>
                  {source.evidence_text && <p className="mb-1">Quote: “{source.evidence_text}”</p>}
                  <p className="whitespace-pre-wrap text-muted-foreground">{source.content}</p>
                </li>
              ))}
            </ul>
          </section>
          {data.entities.length > 0 && (
            <section>
              <SectionTitle>Entities</SectionTitle>
              <div className="flex flex-wrap gap-2">
                {data.entities.map((entity) => (
                  <Badge key={entity.entity_id} variant="outline" className="font-normal">
                    {entity.canonical_name} · {entity.entity_type}
                  </Badge>
                ))}
              </div>
            </section>
          )}
          <section>
            <SectionTitle>Details stored with the memory</SectionTitle>
            <JsonView value={data.metadata} maxHeight="16rem" />
          </section>
        </div>
      )}
    </QueryState>
  );
}

function RunDetail({ runId, onOpenMemory }: { runId: string; onOpenMemory: (id: string) => void }) {
  const run = useRun(runId);
  const memories = useMemories({ processing_run_id: runId, limit: 50 });
  const replay = useReplay();
  return (
    <QueryState query={run}>
      {(data) => (
        <div className="space-y-6 text-sm">
          <KeyValues
            entries={[
              { label: "Status", value: <StatusBadge status={data.status} /> },
              { label: "Attempt", value: data.attempt_number },
              { label: "Messages in the unit", value: data.raw_message_ids.length },
              { label: "Pipeline version", value: data.pipeline_version },
              { label: "Created", value: formatDateTime(data.created_at) },
              { label: "Finished", value: formatDateTime(data.finished_at) },
              {
                label: "Error",
                value: data.error_code ? `${data.error_code}: ${data.error_message ?? ""}` : "none",
              },
              {
                label: "Extraction",
                value: data.extraction
                  ? `${data.extraction.disposition ?? "unknown"}, ${data.extraction.model_name ?? "unknown model"}, contract ${data.extraction.schema_version}`
                  : "none stored",
              },
            ]}
          />
          <div className="flex flex-wrap gap-3">
            <Link to={`/calls?processing_run_id=${data.id}`} className="text-primary hover:underline">
              Model calls of this run
            </Link>
            {(data.status === "failed" || data.status === "needs_review") && (
              <Button
                size="sm"
                variant="outline"
                disabled={replay.isPending}
                onClick={() =>
                  replay.mutate(
                    { run_ids: [data.id], all_units: false, limit: 1 },
                    {
                      onSuccess: (result) =>
                        toast.success(`Replay: ${result.outcomes.map((item) => item.action).join(", ")}`),
                      onError: (error) => toast.error(describeError(error)),
                    },
                  )
                }
              >
                Replay this unit, calling the model
              </Button>
            )}
          </div>

          <section>
            <SectionTitle>Memories it produced</SectionTitle>
            <QueryState
              query={memories}
              isEmpty={(page) => page.items.length === 0}
              empty={<p className="text-muted-foreground">None.</p>}
            >
              {(page) => (
                <ul className="space-y-1.5">
                  {page.items.map((memory) => (
                    <li key={memory.id}>
                      <button
                        type="button"
                        className="w-full rounded-md border px-3 py-2 text-left hover:bg-muted/40"
                        onClick={() => onOpenMemory(memory.id)}
                      >
                        <Badge variant="secondary" className="mr-2 font-normal">
                          {memory.memory_type.replace(/_/g, " ")}
                        </Badge>
                        {memory.content}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </section>

          <section>
            <SectionTitle hint="every attempt is kept">What happened</SectionTitle>
            <ol className="space-y-1">
              {data.events.map((event) => (
                <li key={event.id} className="flex flex-wrap items-baseline gap-2">
                  <span className="tabular w-36 shrink-0 text-xs text-muted-foreground">
                    {formatDateTime(event.created_at)}
                  </span>
                  <span className="font-mono text-xs">{event.event_type}</span>
                  {event.stage && <span className="text-xs text-muted-foreground">at {event.stage}</span>}
                  <span className="text-xs text-muted-foreground">attempt {event.attempt_number}</span>
                  {event.detail && <span className="text-muted-foreground">{event.detail}</span>}
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </QueryState>
  );
}

function RunsTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [status, setStatus] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const runs = useRuns({
    status: status === ALL ? null : (status as ProcessingStatus),
    limit: PAGE_SIZE,
    offset,
  });
  return (
    <>
      <div className="mb-3">
        <FilterSelect
          label="Status"
          value={status}
          options={RUN_STATUSES}
          onChange={(value) => {
            setStatus(value);
            setOffset(0);
          }}
        />
      </div>
      <QueryState
        query={runs}
        isEmpty={(data) => data.total === 0}
        empty={
          <EmptyState title="No processing run matches">
            Capture a note from the <Link to="/playground">Playground</Link> with "Save through the
            pipeline" switched on.
          </EmptyState>
        }
      >
        {(data) => (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Captured</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Messages</TableHead>
                  <TableHead className="text-right">Attempt</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((run) => (
                  <TableRow key={run.id} className="cursor-pointer" onClick={() => onOpen(run.id)}>
                    <TableCell className="whitespace-nowrap" title={formatDateTime(run.created_at)}>
                      <button type="button" className="hover:underline">
                        {formatRelative(run.created_at)}
                      </button>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="tabular text-right">{run.raw_message_ids.length}</TableCell>
                    <TableCell className="tabular text-right">{run.attempt_number}</TableCell>
                    <TableCell className="whitespace-normal text-xs text-muted-foreground">
                      {run.error_code ? `${run.error_code}: ${truncate(run.error_message ?? "", 90)}` : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>
    </>
  );
}

function MemoriesTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [type, setType] = useState(ALL);
  const [offset, setOffset] = useState(0);
  const stats = usePipelineStats();
  const memories = useMemories({
    memory_type: type === ALL ? null : (type as MemoryType),
    limit: PAGE_SIZE,
    offset,
  });
  const types = Object.keys(stats.data?.memories_by_type ?? {}).sort();
  return (
    <>
      <div className="mb-3">
        <FilterSelect
          label="Type"
          value={type}
          options={[
            { value: ALL, label: "Any type" },
            ...types.map((name) => ({ value: name, label: name.replace(/_/g, " ") })),
          ]}
          onChange={(value) => {
            setType(value);
            setOffset(0);
          }}
        />
      </div>
      <QueryState
        query={memories}
        isEmpty={(data) => data.total === 0}
        empty={<EmptyState title="No memory has been built yet" />}
      >
        {(data) => (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Built</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Content</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((memory) => (
                  <TableRow key={memory.id} className="cursor-pointer" onClick={() => onOpen(memory.id)}>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatRelative(memory.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-normal">
                        {memory.memory_type.replace(/_/g, " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xl whitespace-normal">
                      <button type="button" className="text-left hover:underline">
                        {truncate(memory.content, 160)}
                      </button>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={memory.status} />
                    </TableCell>
                    <TableCell className="tabular text-right">{formatPercent(memory.confidence)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>
    </>
  );
}

export function PipelinePage({ runId }: { runId: string | null }) {
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [openMemory, setOpenMemory] = useState<string | null>(null);
  const openRun = selectedRun ?? runId;

  function closeRun() {
    setSelectedRun(null);
    if (runId !== null) navigate("/pipeline");
  }

  return (
    <>
      <PageHeader
        title="Pipeline"
        description="Notes that were captured, how their processing went, and the memories that came out."
      />
      <Tabs defaultValue="runs">
        <TabsList>
          <TabsTrigger value="runs">Processing runs</TabsTrigger>
          <TabsTrigger value="memories">Memories</TabsTrigger>
        </TabsList>
        <TabsContent value="runs">
          <RunsTab onOpen={setSelectedRun} />
        </TabsContent>
        <TabsContent value="memories">
          <MemoriesTab onOpen={setOpenMemory} />
        </TabsContent>
      </Tabs>

      <Dialog open={openRun !== null && openMemory === null} onOpenChange={(open) => !open && closeRun()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Processing run</DialogTitle>
            <DialogDescription className="font-mono text-xs">{openRun}</DialogDescription>
          </DialogHeader>
          {openRun !== null && <RunDetail runId={openRun} onOpenMemory={setOpenMemory} />}
        </DialogContent>
      </Dialog>

      <Dialog open={openMemory !== null} onOpenChange={(open) => !open && setOpenMemory(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Memory</DialogTitle>
            <DialogDescription>Proposed by the pipeline, with the evidence it rests on.</DialogDescription>
          </DialogHeader>
          {openMemory !== null && <MemoryDetail memoryId={openMemory} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
