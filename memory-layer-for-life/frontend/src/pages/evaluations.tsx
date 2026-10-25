import { useState } from "react";
import { toast } from "sonner";

import {
  type ConsoleConfig,
  describeError,
  type EffortLevel,
  type EvaluationRun,
} from "@/api/client";
import {
  useConfig,
  useDataset,
  useEvaluations,
  useFailingCases,
  useStartEvaluation,
} from "@/api/hooks";
import { BarList } from "@/components/shared/charts";
import { FilterSelect } from "@/components/shared/filter-select";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { Pager } from "@/components/shared/pager";
import { EmptyState, Loading, QueryState } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { scoreboard } from "@/lib/evaluation";
import {
  formatDateTime,
  formatPercent,
  formatRelative,
  formatUsd,
  modelLabel,
} from "@/lib/format";
import { navigate } from "@/lib/router";

const PAGE_SIZE = 25;
const SAME_AS_EXTRACTOR = "same";

function StartForm({ config, onDone }: { config: ConsoleConfig; onDone: () => void }) {
  const [model, setModel] = useState(config.default_model);
  const [effort, setEffort] = useState(config.default_effort);
  const [judgeModel, setJudgeModel] = useState(SAME_AS_EXTRACTOR);
  const [judgeEffort, setJudgeEffort] = useState("high");
  const [scope, setScope] = useState<"all" | "some">("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const dataset = useDataset();
  const runs = useEvaluations({ limit: 200 });
  const start = useStartEvaluation();

  const modelOptions = config.models.map((option) => ({
    value: option.id,
    label: option.is_default ? `${option.display_name} (configured)` : option.display_name,
  }));
  const effortOptions = config.effort_levels.map((level) => ({ value: level, label: level }));

  const cases = dataset.data?.cases ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? cases.filter(
        (item) =>
          item.case_id.includes(needle) ||
          item.preview.toLowerCase().includes(needle) ||
          item.tags.some((tag) => tag.toLowerCase().includes(needle)),
      )
    : cases;
  const count = scope === "all" ? cases.length : selected.length;

  const score = scoreboard(runs.data?.items ?? []).find((entry) => entry.model === model);
  const perCase =
    score?.meanCostPerFullRun != null && score.casesTotal
      ? score.meanCostPerFullRun / score.casesTotal
      : null;

  const blocked = !config.provider_configured
    ? "No API key is configured, so no model can be called."
    : dataset.data && !dataset.data.available
      ? (dataset.data.problem ?? "The dataset is not available.")
      : config.evaluation_running
        ? "An evaluation is already running. Wait for it or cancel it first."
        : null;

  function toggle(caseId: string) {
    setSelected((current) =>
      current.includes(caseId) ? current.filter((id) => id !== caseId) : [...current, caseId],
    );
  }

  function submit() {
    start.mutate(
      {
        extractor_model: model,
        extraction_effort: effort as EffortLevel,
        judge_model: judgeModel === SAME_AS_EXTRACTOR ? null : judgeModel,
        judge_effort: judgeEffort as EffortLevel,
        case_ids: scope === "all" ? null : selected,
        concurrency: 6,
      },
      {
        onSuccess: (run) => {
          onDone();
          navigate(`/evaluations/${run.id}`);
        },
        onError: (error) => toast.error(describeError(error)),
      },
    );
  }

  return (
    <div className="space-y-5">
      {blocked && (
        <Alert variant="destructive">
          <AlertTitle>An evaluation cannot start</AlertTitle>
          <AlertDescription>{blocked}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label>Model to test</Label>
          <FilterSelect label="Model" value={model} options={modelOptions} onChange={setModel} className="w-full" />
        </div>
        <div className="space-y-1.5">
          <Label>Effort</Label>
          <FilterSelect label="Effort" value={effort} options={effortOptions} onChange={setEffort} className="w-full" />
        </div>
        <div className="space-y-1.5">
          <Label>Judge model</Label>
          <FilterSelect
            label="Judge model"
            value={judgeModel}
            options={[{ value: SAME_AS_EXTRACTOR, label: "Same as the model tested" }, ...modelOptions]}
            onChange={setJudgeModel}
            className="w-full"
          />
        </div>
        <div className="space-y-1.5">
          <Label>Judge effort</Label>
          <FilterSelect label="Judge effort" value={judgeEffort} options={effortOptions} onChange={setJudgeEffort} className="w-full" />
        </div>
      </div>

      <div className="space-y-2">
        <Label>Cases</Label>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant={scope === "all" ? "default" : "outline"} onClick={() => setScope("all")}>
            All {cases.length} cases
          </Button>
          <Button type="button" size="sm" variant={scope === "some" ? "default" : "outline"} onClick={() => setScope("some")}>
            Chosen cases
          </Button>
        </div>
        {scope === "some" && (
          <div className="space-y-2">
            <div className="flex gap-2">
              <Input
                value={filter}
                placeholder="Filter by id, text, or tag"
                aria-label="Filter cases"
                onChange={(event) => setFilter(event.target.value)}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() =>
                  setSelected((current) => Array.from(new Set([...current, ...shown.map((item) => item.case_id)])))
                }
              >
                Add shown
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setSelected([])}>
                Clear
              </Button>
            </div>
            <ul className="max-h-56 overflow-y-auto rounded-md border text-sm">
              {shown.map((item) => (
                <li key={item.case_id} className="border-b last:border-b-0">
                  <label className="flex cursor-pointer items-center gap-2 px-2 py-1.5 hover:bg-muted/40">
                    <input
                      type="checkbox"
                      className="accent-[var(--primary)]"
                      checked={selected.includes(item.case_id)}
                      onChange={() => toggle(item.case_id)}
                    />
                    <span className="w-36 shrink-0 font-mono text-xs">{item.case_id}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.preview}</span>
                    <StatusBadge status={item.expected_outcome} />
                  </label>
                </li>
              ))}
              {shown.length === 0 && <li className="px-2 py-3 text-muted-foreground">No case matches.</li>}
            </ul>
          </div>
        )}
      </div>

      <p className="text-sm">
        <span className="font-medium">{count} cases.</span>{" "}
        <span className="text-muted-foreground">
          Each case calls the model once to extract and usually once more to judge.{" "}
          {perCase !== null
            ? `Earlier full runs on this model suggest about ${formatUsd(perCase * count)}.`
            : "There is no earlier full run on this model to estimate the cost from."}{" "}
          The dataset's messages are sent to the provider.
        </span>
      </p>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button type="button" disabled={blocked !== null || count === 0 || start.isPending} onClick={submit}>
          {start.isPending ? "Starting" : `Start, calling the model for ${count} cases`}
        </Button>
      </DialogFooter>
    </div>
  );
}

function StartEvaluationDialog() {
  const [open, setOpen] = useState(false);
  const config = useConfig();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">Start evaluation</Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Start an evaluation</DialogTitle>
          <DialogDescription>
            Runs golden cases through a model and scores every answer. It costs money.
          </DialogDescription>
        </DialogHeader>
        {config.data ? <StartForm config={config.data} onDone={() => setOpen(false)} /> : <Loading />}
      </DialogContent>
    </Dialog>
  );
}

function RunsTable({ runs }: { runs: EvaluationRun[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Started</TableHead>
          <TableHead>Model</TableHead>
          <TableHead>Passed</TableHead>
          <TableHead className="text-right">Not evaluated</TableHead>
          <TableHead className="text-right">Cost</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Source</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => {
          const evaluated = run.cases_passed + run.cases_failed;
          return (
            <TableRow key={run.id}>
              <TableCell className="whitespace-nowrap">
                <Link to={`/evaluations/${run.id}`} className="hover:underline" title={formatDateTime(run.started_at)}>
                  {formatRelative(run.started_at)}
                </Link>
              </TableCell>
              <TableCell>
                {modelLabel(run.extractor_model)}
                {run.extraction_effort && (
                  <span className="ml-1 text-xs text-muted-foreground">{run.extraction_effort}</span>
                )}
              </TableCell>
              <TableCell className="tabular">
                {run.status === "running" ? (
                  <div className="w-40">
                    <Progress value={(run.cases_done / Math.max(run.cases_total, 1)) * 100} />
                    <div className="mt-1 text-xs text-muted-foreground">
                      {run.cases_done} of {run.cases_total} done
                    </div>
                  </div>
                ) : (
                  <>
                    {run.cases_passed} of {evaluated}
                    <span className="ml-2 text-xs text-muted-foreground">{formatPercent(run.pass_rate, 1)}</span>
                  </>
                )}
              </TableCell>
              <TableCell className="tabular text-right">{run.cases_not_evaluated || ""}</TableCell>
              <TableCell className="tabular text-right">{formatUsd(run.estimated_cost_usd)}</TableCell>
              <TableCell>
                <StatusBadge status={run.status} />
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {run.trigger}
                {run.source_report && <span className="ml-1 font-mono">{run.source_report}</span>}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function EvaluationsPage() {
  const [offset, setOffset] = useState(0);
  const runs = useEvaluations({ limit: PAGE_SIZE, offset });
  const failing = useFailingCases({ limit: 12 });

  return (
    <>
      <PageHeader
        title="Evaluations"
        description="Each run sends the golden cases to a model and scores every answer against the labels."
        actions={<StartEvaluationDialog />}
      />
      <QueryState
        query={runs}
        isEmpty={(data) => data.total === 0}
        empty={
          <EmptyState title="No evaluation is stored yet">
            Start one here, or import earlier report files with the import script.
          </EmptyState>
        }
      >
        {(data) => (
          <>
            <RunsTable runs={data.items} />
            <Pager total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>

      <section className="mt-12 max-w-2xl">
        <SectionTitle hint="across completed runs">Cases that fail most often</SectionTitle>
        <p className="mb-3 text-xs text-muted-foreground">
          A case that fails every time points at the case or its label. One that fails now and then
          points at the model or the judge.
        </p>
        <QueryState query={failing}>
          {(data) => (
            <BarList
              items={data.map((item) => ({
                key: item.case_id,
                label: <span className="font-mono text-xs">{item.case_id}</span>,
                value: item.failed,
                hint: `of ${item.evaluated} runs`,
                color: "var(--destructive)",
              }))}
              format={(value) => `failed ${value}`}
            />
          )}
        </QueryState>
      </section>
    </>
  );
}
