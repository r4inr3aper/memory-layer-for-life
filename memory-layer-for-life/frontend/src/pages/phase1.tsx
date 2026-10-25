import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ApiError, type EvaluationRun } from "@/api/client";
import { useEvaluations, useFailingCases, useReport } from "@/api/hooks";
import { BarList } from "@/components/shared/charts";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { EmptyState, ErrorNotice, Loading, QueryState } from "@/components/shared/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { modelColor } from "@/lib/colors";
import { checkTotals, datasetSize, fullRuns, scoreboard } from "@/lib/evaluation";
import { formatDateTime, formatPercent, formatUsd, modelLabel } from "@/lib/format";

function Scoreboard({ runs }: { runs: EvaluationRun[] }) {
  const board = scoreboard(runs);
  const total = datasetSize(runs);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Model</TableHead>
          <TableHead className="text-right">Full runs</TableHead>
          <TableHead className="text-right">Best</TableHead>
          <TableHead className="text-right">Latest</TableHead>
          <TableHead className="text-right">Lowest</TableHead>
          <TableHead className="text-right">Cost of a full run</TableHead>
          <TableHead className="text-right">Spent in total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {board.map((score) => (
          <TableRow key={score.model}>
            <TableCell>
              <span className="mr-2 inline-block size-2 rounded-sm" style={{ background: modelColor(score.model) }} />
              {modelLabel(score.model)}
            </TableCell>
            <TableCell className="tabular text-right">{score.fullRuns}</TableCell>
            <TableCell className="tabular text-right font-medium">
              {score.best !== null ? `${score.best} of ${total}` : "n/a"}
            </TableCell>
            <TableCell className="tabular text-right">{score.latest ?? "n/a"}</TableCell>
            <TableCell className="tabular text-right">{score.worst ?? "n/a"}</TableCell>
            <TableCell className="tabular text-right">{formatUsd(score.meanCostPerFullRun)}</TableCell>
            <TableCell className="tabular text-right">{formatUsd(score.totalCost)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RunHistory({ runs }: { runs: EvaluationRun[] }) {
  const ordered = [...runs].sort((a, b) => a.started_at.localeCompare(b.started_at));
  const total = datasetSize(runs);
  return (
    <BarList
      max={total}
      items={ordered.map((run, index) => {
        const partial = run.cases_total < total || run.cases_not_evaluated > 0;
        return {
          key: run.id,
          label: (
            <Link to={`/evaluations/${run.id}`} className="hover:underline">
              <span className="tabular mr-2 text-xs text-muted-foreground">run {index + 1}</span>
              {modelLabel(run.extractor_model)}
              <span className="ml-2 text-xs text-muted-foreground">{formatDateTime(run.started_at)}</span>
            </Link>
          ),
          value: run.cases_passed,
          hint: partial
            ? run.cases_not_evaluated > 0
              ? `${run.cases_not_evaluated} not evaluated`
              : `trial of ${run.cases_total} cases`
            : undefined,
          color: partial ? "var(--muted-foreground)" : modelColor(run.extractor_model),
        };
      })}
      format={(value) => `${value} passed`}
    />
  );
}

function LatestChecks({ runs }: { runs: EvaluationRun[] }) {
  const complete = fullRuns(runs);
  const models = Array.from(new Set(complete.map((run) => run.extractor_model ?? "unknown"))).sort();
  return (
    <div className="grid gap-10 md:grid-cols-2">
      {models.map((model) => {
        const latest = complete.filter((run) => (run.extractor_model ?? "unknown") === model).at(-1);
        if (!latest) return null;
        const checks = checkTotals(latest.check_totals).filter((check) => check.evaluated > 0);
        return (
          <div key={model}>
            <SectionTitle hint={`${latest.cases_passed} of ${latest.cases_total} cases passed`}>
              {modelLabel(model)}, latest full run
            </SectionTitle>
            <BarList
              max={1}
              items={checks.map((check) => ({
                key: check.name,
                label: <span className="font-mono text-xs">{check.name}</span>,
                value: check.passed / check.evaluated,
                hint: `${check.passed} of ${check.evaluated}`,
                color: check.passed === check.evaluated ? "var(--success)" : "var(--warning)",
              }))}
              format={(value) => formatPercent(value, 1)}
            />
          </div>
        );
      })}
    </div>
  );
}

function WrittenReport() {
  const report = useReport("phase-1");
  if (report.isPending) return <Loading rows={6} />;
  if (report.isError) {
    if (report.error instanceof ApiError && report.error.status === 404) {
      return (
        <EmptyState title="The written report is not in this copy of the project">
          It is the file PHASE1_REPORT.md at the project root.
        </EmptyState>
      );
    }
    return <ErrorNotice error={report.error} />;
  }
  return (
    <>
      <p className="mb-6 text-xs text-muted-foreground">
        From PHASE1_REPORT.md, last changed {formatDateTime(report.data.updated_at)}.
      </p>
      <article className="prose prose-invert max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-2xl prose-h2:mt-10 prose-h2:border-b prose-h2:pb-2 prose-h2:text-xl prose-h3:text-base prose-a:text-primary prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:text-[0.85em] prose-code:before:content-none prose-code:after:content-none prose-pre:bg-muted/40 prose-table:text-sm prose-th:text-left">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.data.markdown}</ReactMarkdown>
      </article>
    </>
  );
}

export function Phase1Page() {
  const evaluations = useEvaluations({ limit: 200 });
  const failing = useFailingCases({ limit: 10 });

  return (
    <>
      <PageHeader
        title="Phase 1 results"
        description="How the ingestion pipeline scored on the golden notes, model by model, followed by the written report."
      />

      <QueryState
        query={evaluations}
        isEmpty={(data) => data.total === 0}
        empty={
          <EmptyState title="No evaluation is stored in this database">
            Import the earlier report files with the import script, or start a run on the{" "}
            <Link to="/evaluations">Evaluations</Link> screen.
          </EmptyState>
        }
      >
        {(data) => (
          <div className="space-y-12">
            <section>
              <SectionTitle hint="a full run scored every case of the dataset">Scoreboard</SectionTitle>
              <Scoreboard runs={data.items} />
            </section>
            <section className="max-w-3xl">
              <SectionTitle hint="oldest first; grey runs are partial">Every run</SectionTitle>
              <RunHistory runs={data.items} />
            </section>
            <section>
              <LatestChecks runs={data.items} />
            </section>
          </div>
        )}
      </QueryState>

      <section className="mt-12 max-w-2xl">
        <SectionTitle hint="across completed runs">Cases that failed most often</SectionTitle>
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

      <section className="mt-14 border-t pt-10">
        <h2 className="mb-4 text-base font-semibold">Written report</h2>
        <WrittenReport />
      </section>
    </>
  );
}
