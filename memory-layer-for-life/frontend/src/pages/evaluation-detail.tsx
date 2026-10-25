import { useState } from "react";
import { toast } from "sonner";

import { describeError, type EvaluationCaseOutcome, type EvaluationRun } from "@/api/client";
import {
  useCancelEvaluation,
  useEvaluation,
  useEvaluationCase,
  useEvaluationCases,
} from "@/api/hooks";
import { BarList } from "@/components/shared/charts";
import { ExtractionView } from "@/components/shared/extraction-view";
import { JsonView } from "@/components/shared/json-view";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { Pager } from "@/components/shared/pager";
import { Stat, StatRow } from "@/components/shared/stat";
import { EmptyState, QueryState } from "@/components/shared/states";
import { StatusBadge } from "@/components/shared/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { agreement, asCaseDocument, type CaseDocument, checkTotals } from "@/lib/evaluation";
import { asExtractionOutput } from "@/lib/extraction";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  formatUsd,
  modelLabel,
  truncate,
} from "@/lib/format";

const PAGE_SIZE = 100;
type OutcomeFilter = EvaluationCaseOutcome | "all";

function CaseBody({ document }: { document: CaseDocument }) {
  const produced = asExtractionOutput(document.produced);
  return (
    <div className="space-y-6 text-sm">
      <section>
        <SectionTitle>Source messages</SectionTitle>
        <ol className="space-y-1.5">
          {document.messages.map((message, index) => (
            <li key={index} className="whitespace-pre-wrap rounded-md border px-3 py-2">
              <span className="mr-2 font-mono text-xs text-muted-foreground">[{index}]</span>
              {message}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <SectionTitle hint={<StatusBadge status={document.expected.outcome} />}>
          What the label expects
        </SectionTitle>
        {document.expected.memories.length === 0 ? (
          <p className="text-muted-foreground">No memory: the system should abstain.</p>
        ) : (
          <ul className="space-y-1.5">
            {document.expected.memories.map((memory, index) => (
              <li key={index}>
                <Badge variant="secondary" className="mr-2 font-normal">
                  {memory.type}
                </Badge>
                <span className="mr-2 text-xs text-muted-foreground">{memory.status}</span>
                {memory.summary}
              </li>
            ))}
          </ul>
        )}
        {document.expected.must_not.length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-muted-foreground">It must not</div>
            <ul className="list-disc pl-5">
              {document.expected.must_not.map((rule, index) => (
                <li key={index}>{rule}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section>
        <SectionTitle>What the model produced</SectionTitle>
        {produced ? (
          <ExtractionView output={produced} />
        ) : (
          <p className="text-muted-foreground">Nothing. {document.error}</p>
        )}
      </section>

      {document.checks.length > 0 && (
        <section>
          <SectionTitle>Checks</SectionTitle>
          <Table>
            <TableBody>
              {document.checks.map((check) => (
                <TableRow key={check.name}>
                  <TableCell className="w-48 align-top font-mono text-xs">{check.name}</TableCell>
                  <TableCell className="w-20 align-top">
                    <StatusBadge status={check.passed ? "passed" : "failed"} />
                  </TableCell>
                  <TableCell className="whitespace-normal text-muted-foreground">{check.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {document.judge.map((verdict, index) => (
        <section key={index}>
          <SectionTitle hint={<StatusBadge status={verdict.coverage} />}>
            Judge verdict{document.judge.length > 1 ? ` ${index + 1}` : ""}
          </SectionTitle>
          <p>{verdict.coverage_explanation}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Memories that convey it: {verdict.covering_memory_indexes.join(", ") || "none"}. Main
            memory: {verdict.primary_memory_index ?? "none"}.
          </p>
          {verdict.rule_verdicts.length > 0 && (
            <ul className="mt-2 space-y-1">
              {verdict.rule_verdicts.map((rule) => (
                <li key={rule.rule_index} className={rule.violated ? "text-destructive" : undefined}>
                  <span className="mr-2 font-mono text-xs">rule {rule.rule_index}</span>
                  {rule.violated ? "broken. " : "kept. "}
                  <span className="text-muted-foreground">{rule.explanation}</span>
                </li>
              ))}
            </ul>
          )}
          {verdict.unsupported_claims.length > 0 && (
            <div className="mt-2 text-destructive">
              Unsupported:{" "}
              {verdict.unsupported_claims
                .map((claim) => `memory ${claim.memory_index}: ${claim.claim}`)
                .join("; ")}
            </div>
          )}
        </section>
      ))}

      {document.error && produced && (
        <Alert variant="destructive">
          <AlertTitle>This case could not be scored</AlertTitle>
          <AlertDescription>{document.error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function CaseDialog({ runId, caseId, onClose }: { runId: string; caseId: string | null; onClose: () => void }) {
  const detail = useEvaluationCase(runId, caseId);
  return (
    <Dialog open={caseId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="font-mono text-base">{caseId}</DialogTitle>
          <DialogDescription>
            The source, the label, the model's answer, and how each check judged it.
          </DialogDescription>
        </DialogHeader>
        {caseId !== null && (
          <QueryState query={detail}>
            {(data) => {
              const document = asCaseDocument(data.document);
              return document ? <CaseBody document={document} /> : <JsonView value={data.document} />;
            }}
          </QueryState>
        )}
      </DialogContent>
    </Dialog>
  );
}

function CasesSection({ run }: { run: EvaluationRun }) {
  const [outcome, setOutcome] = useState<OutcomeFilter>(
    run.cases_failed > 0 ? "failed" : run.cases_not_evaluated > 0 ? "not_evaluated" : "all",
  );
  const [offset, setOffset] = useState(0);
  const [openCase, setOpenCase] = useState<string | null>(null);
  const cases = useEvaluationCases(
    run.id,
    { outcome: outcome === "all" ? null : outcome, limit: PAGE_SIZE, offset },
    { live: run.status === "running" },
  );

  return (
    <section className="mt-10">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium">Cases</h2>
        <Tabs
          value={outcome}
          onValueChange={(value) => {
            setOutcome(value as OutcomeFilter);
            setOffset(0);
          }}
        >
          <TabsList>
            <TabsTrigger value="failed">Failed {run.cases_failed}</TabsTrigger>
            <TabsTrigger value="not_evaluated">Not evaluated {run.cases_not_evaluated}</TabsTrigger>
            <TabsTrigger value="passed">Passed {run.cases_passed}</TabsTrigger>
            <TabsTrigger value="all">All {run.cases_done}</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <QueryState
        query={cases}
        isEmpty={(data) => data.total === 0}
        empty={<EmptyState title="No case in this group" />}
      >
        {(data) => (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>Outcome</TableHead>
                  <TableHead>Label says</TableHead>
                  <TableHead>Model said</TableHead>
                  <TableHead>Failed checks</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((item) => (
                  <TableRow key={item.case_id} className="cursor-pointer" onClick={() => setOpenCase(item.case_id)}>
                    <TableCell>
                      <button type="button" className="font-mono text-xs hover:underline">
                        {item.case_id}
                      </button>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={item.outcome} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={item.expected_outcome} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={item.produced_disposition} />
                    </TableCell>
                    <TableCell className="whitespace-normal text-xs">
                      {item.failed_checks.length > 0
                        ? item.failed_checks.join(", ")
                        : item.error
                          ? truncate(item.error, 90)
                          : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager total={data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
          </>
        )}
      </QueryState>
      <CaseDialog runId={run.id} caseId={openCase} onClose={() => setOpenCase(null)} />
    </section>
  );
}

function RunDetail({ run }: { run: EvaluationRun }) {
  const cancel = useCancelEvaluation();
  const evaluated = run.cases_passed + run.cases_failed;
  const checks = checkTotals(run.check_totals).filter((check) => check.evaluated > 0);
  const disposition = agreement(run.not_gating, "disposition");
  const state = agreement(run.not_gating, "state");
  // A run read from a report file records when it ended, not how long it took.
  const duration =
    run.finished_at !== null && run.trigger !== "import"
      ? new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
      : null;

  return (
    <>
      <PageHeader
        title={`Evaluation of ${modelLabel(run.extractor_model)}`}
        description={
          <>
            <Link to="/evaluations" className="text-primary hover:underline">
              All evaluations
            </Link>
            {" · "}started {formatDateTime(run.started_at)} · {run.trigger}
            {run.source_report && ` · report ${run.source_report}`}
          </>
        }
        actions={
          <>
            <StatusBadge status={run.status} />
            {run.status === "running" && (
              <Button
                size="sm"
                variant="outline"
                disabled={cancel.isPending}
                onClick={() =>
                  cancel.mutate(run.id, { onError: (error) => toast.error(describeError(error)) })
                }
              >
                Cancel
              </Button>
            )}
          </>
        }
      />

      {run.status === "running" && (
        <div className="mb-6">
          <Progress value={(run.cases_done / Math.max(run.cases_total, 1)) * 100} />
          <p className="mt-1 text-xs text-muted-foreground">
            {run.cases_done} of {run.cases_total} cases done. This page updates by itself.
          </p>
        </div>
      )}
      {run.error_message && (
        <Alert variant="destructive" className="mb-6">
          <AlertTitle>The run did not complete</AlertTitle>
          <AlertDescription>{run.error_message}</AlertDescription>
        </Alert>
      )}
      {run.cases_not_evaluated > 0 && run.status !== "running" && (
        <Alert className="mb-6">
          <AlertTitle>{run.cases_not_evaluated} cases could not be evaluated</AlertTitle>
          <AlertDescription>
            The provider or the judge gave no answer for them. They count as neither passed nor
            failed.
          </AlertDescription>
        </Alert>
      )}

      <StatRow>
        <Stat label="Passed" value={`${run.cases_passed} of ${evaluated}`} hint={formatPercent(run.pass_rate, 1)} />
        <Stat label="Failed" value={run.cases_failed} />
        <Stat label="Not evaluated" value={run.cases_not_evaluated} />
        <Stat
          label="Estimated cost"
          value={formatUsd(run.estimated_cost_usd)}
          hint={run.calls_logged ? <Link to={`/calls?evaluation_run_id=${run.id}`}>see its calls</Link> : "calls not logged"}
        />
        <Stat label="Took" value={formatDuration(duration)} />
        <Stat
          label="Judge"
          value={modelLabel(run.judge_model)}
          hint={run.judge_effort ? `effort ${run.judge_effort}` : undefined}
        />
      </StatRow>

      <div className="mt-10 grid gap-10 md:grid-cols-2">
        <section>
          <SectionTitle hint="cases that pass each check">Checks</SectionTitle>
          {checks.length === 0 ? (
            <p className="text-sm text-muted-foreground">No case has been scored yet.</p>
          ) : (
            <BarList
              items={checks.map((check) => ({
                key: check.name,
                label: <span className="font-mono text-xs">{check.name}</span>,
                value: check.passed / check.evaluated,
                hint: `${check.passed} of ${check.evaluated}`,
                color: check.passed === check.evaluated ? "var(--success)" : "var(--warning)",
              }))}
              max={1}
              format={(value) => formatPercent(value, 1)}
            />
          )}
        </section>
        <section>
          <SectionTitle hint="reported, not counted">Agreement with the labels</SectionTitle>
          <p className="mb-3 text-xs text-muted-foreground">
            The dataset's own labels are not consistent on these two points, so they never fail a
            case.
          </p>
          <BarList
            items={[
              ...(disposition
                ? [
                    {
                      key: "disposition",
                      label: "Extract versus context",
                      value: disposition.compared > 0 ? disposition.agree / disposition.compared : 0,
                      hint: `${disposition.agree} of ${disposition.compared}`,
                    },
                  ]
                : []),
              ...(state
                ? [
                    {
                      key: "state",
                      label: "Pending versus done",
                      value: state.compared > 0 ? state.agree / state.compared : 0,
                      hint: `${state.agree} of ${state.compared}`,
                    },
                  ]
                : []),
            ]}
            max={1}
            format={(value) => formatPercent(value, 1)}
          />
        </section>
      </div>

      <CasesSection run={run} />
    </>
  );
}

export function EvaluationDetailPage({ runId }: { runId: string }) {
  const run = useEvaluation(runId);
  return <QueryState query={run}>{(data) => <RunDetail run={data} />}</QueryState>;
}
