import { useState } from "react";

import type { EvaluationRun, PipelineStats, UsageSummary } from "@/api/client";
import { useEvaluations, usePipelineStats, useUsage } from "@/api/hooks";
import { BarList, type ColumnDatum, StackedColumns } from "@/components/shared/charts";
import { FilterSelect } from "@/components/shared/filter-select";
import { Link } from "@/components/shared/link";
import { PageHeader, SectionTitle } from "@/components/shared/page-header";
import { Stat, StatRow } from "@/components/shared/stat";
import { EmptyState, QueryState } from "@/components/shared/states";
import { modelColor } from "@/lib/colors";
import { datasetSize, scoreboard } from "@/lib/evaluation";
import {
  cacheHitRate,
  formatDate,
  formatDuration,
  formatInteger,
  formatPercent,
  formatRelative,
  formatTokens,
  formatUsd,
  modelLabel,
} from "@/lib/format";

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "all", label: "All time" },
];

function startOfRange(value: string): string | null {
  if (value === "all") return null;
  const start = new Date(Date.now() - Number(value) * 86_400_000);
  start.setHours(0, 0, 0, 0);
  return start.toISOString();
}

function sum(values: Record<string, number>): number {
  return Object.values(values).reduce((total, value) => total + value, 0);
}

function countItems(values: Record<string, number>) {
  return Object.entries(values)
    .sort((a, b) => b[1] - a[1])
    .map(([key, value]) => ({ key, label: key.replace(/_/g, " "), value }));
}

function UsageSection({ usage }: { usage: UsageSummary }) {
  const totals = usage.totals;
  const prompt =
    totals.input_tokens + totals.cache_read_input_tokens + totals.cache_creation_input_tokens;
  const models = usage.by_model.map((entry) => entry.key);
  const days = Array.from(new Set(usage.by_day.map((entry) => entry.day)));
  const columns: ColumnDatum[] = days.map((day) => ({
    label: formatDate(day),
    values: Object.fromEntries(
      usage.by_day
        .filter((entry) => entry.day === day)
        .map((entry) => [modelLabel(entry.model), entry.estimated_cost_usd]),
    ),
  }));

  return (
    <div className="space-y-8">
      <StatRow>
        <Stat
          label="Model calls"
          value={formatInteger(totals.calls)}
          hint={`${formatInteger(totals.failed_calls)} failed`}
        />
        <Stat
          label="Estimated cost"
          value={formatUsd(totals.estimated_cost_usd)}
          hint={
            totals.unpriced_calls > 0
              ? `${totals.unpriced_calls} calls have no known price`
              : "from list prices"
          }
        />
        <Stat
          label="Prompt tokens"
          value={formatTokens(prompt)}
          hint={`${formatPercent(
            cacheHitRate(
              totals.cache_read_input_tokens,
              totals.cache_creation_input_tokens,
              totals.input_tokens,
            ),
          )} read from cache`}
        />
        <Stat label="Output tokens" value={formatTokens(totals.output_tokens)} />
        <Stat
          label="Median duration"
          value={formatDuration(usage.latency.p50_ms)}
          hint={`95th percentile ${formatDuration(usage.latency.p95_ms)}`}
        />
        <Stat
          label="Failure rate"
          value={formatPercent(totals.calls > 0 ? totals.failed_calls / totals.calls : null, 1)}
        />
      </StatRow>

      <div>
        <SectionTitle hint={`days in ${usage.timezone}`}>Estimated cost per day</SectionTitle>
        <StackedColumns
          data={columns}
          series={models.map(modelLabel)}
          colors={models.map(modelColor)}
          format={(value) => formatUsd(value)}
          label="Estimated cost per day, by model"
        />
      </div>

      <div className="grid gap-8 md:grid-cols-3">
        <div>
          <SectionTitle>By model</SectionTitle>
          <BarList
            items={usage.by_model.map((entry) => ({
              key: entry.key,
              label: modelLabel(entry.key),
              value: entry.estimated_cost_usd,
              hint: `${formatInteger(entry.calls)} calls`,
              color: modelColor(entry.key),
            }))}
            format={(value) => formatUsd(value)}
          />
        </div>
        <div>
          <SectionTitle>By origin</SectionTitle>
          <BarList
            items={usage.by_origin.map((entry) => ({
              key: entry.key,
              label: entry.key,
              value: entry.calls,
              hint: formatUsd(entry.estimated_cost_usd),
            }))}
            format={(value) => `${formatInteger(value)} calls`}
          />
        </div>
        <div>
          <SectionTitle>By operation</SectionTitle>
          <BarList
            items={usage.by_operation.map((entry) => ({
              key: entry.key,
              label: entry.key.replace(/_/g, " "),
              value: entry.calls,
              hint: formatUsd(entry.estimated_cost_usd),
            }))}
            format={(value) => `${formatInteger(value)} calls`}
          />
        </div>
      </div>

      {usage.errors.length > 0 && (
        <div>
          <SectionTitle hint={<Link to="/calls?status=failed">see the failed calls</Link>}>
            Failures by cause
          </SectionTitle>
          <BarList
            items={usage.errors.map((entry) => ({
              key: entry.error_code,
              label: <span className="font-mono text-xs">{entry.error_code}</span>,
              value: entry.calls,
              hint: `last ${formatRelative(entry.last_seen_at)}`,
              color: "var(--destructive)",
            }))}
            format={(value) => `${formatInteger(value)} calls`}
          />
        </div>
      )}
    </div>
  );
}

function QualitySection({ runs }: { runs: EvaluationRun[] }) {
  const board = scoreboard(runs).filter((score) => score.fullRuns > 0);
  const total = datasetSize(runs);
  if (board.length === 0) {
    return (
      <EmptyState title="No full evaluation is stored yet">
        Start one on the <Link to="/evaluations">Evaluations</Link> screen.
      </EmptyState>
    );
  }
  return (
    <BarList
      max={total}
      items={board.map((score) => ({
        key: score.model,
        label: modelLabel(score.model),
        value: score.best ?? 0,
        hint: `latest ${score.latest} of ${total}, ${score.fullRuns} full runs`,
        color: modelColor(score.model),
      }))}
      format={(value) => `best ${value} of ${total}`}
    />
  );
}

function PipelineSection({ stats }: { stats: PipelineStats }) {
  const runs = sum(stats.runs_by_status);
  if (stats.raw_messages === 0 && runs === 0) {
    return (
      <EmptyState title="Nothing has been captured yet">
        Send a note through the pipeline from the <Link to="/playground">Playground</Link>.
      </EmptyState>
    );
  }
  return (
    <div className="space-y-6">
      <StatRow className="lg:grid-cols-4">
        <Stat label="Messages captured" value={formatInteger(stats.raw_messages)} />
        <Stat label="Processing runs" value={formatInteger(runs)} />
        <Stat label="Memories" value={formatInteger(sum(stats.memories_by_type))} />
        <Stat label="Entities" value={formatInteger(stats.entities)} />
      </StatRow>
      <div className="grid gap-8 md:grid-cols-3">
        <div>
          <SectionTitle>Runs by status</SectionTitle>
          <BarList items={countItems(stats.runs_by_status)} format={formatInteger} />
        </div>
        <div>
          <SectionTitle>Memories by type</SectionTitle>
          <BarList items={countItems(stats.memories_by_type)} format={formatInteger} />
        </div>
        <div>
          <SectionTitle>What the model decided</SectionTitle>
          <BarList items={countItems(stats.extractions_by_disposition)} format={formatInteger} />
        </div>
      </div>
    </div>
  );
}

export function OverviewPage() {
  const [range, setRange] = useState(() => ({ value: "30", from: startOfRange("30") }));
  const usage = useUsage({ started_from: range.from });
  const evaluations = useEvaluations({ limit: 200 });
  const stats = usePipelineStats();

  return (
    <>
      <PageHeader
        title="Overview"
        description="What the model calls cost, how good the output is, and what the pipeline holds."
        actions={
          <FilterSelect
            label="Period"
            value={range.value}
            options={RANGES}
            onChange={(value) => setRange({ value, from: startOfRange(value) })}
          />
        }
      />

      <section>
        <h2 className="mb-4 text-base font-semibold">Usage and cost</h2>
        <QueryState query={usage}>
          {(data) => (
            <>
              {data.totals.calls === 0 ? (
                <EmptyState title="No model call has been logged in this period">
                  Every call made from now on appears here. Make one in the{" "}
                  <Link to="/playground">Playground</Link>.
                </EmptyState>
              ) : (
                <UsageSection usage={data} />
              )}
              {data.earlier_evaluations.runs > 0 && (
                <p className="mt-4 text-xs text-muted-foreground">
                  Not included above: {data.earlier_evaluations.runs} evaluation runs made before
                  calls were logged, estimated at{" "}
                  {formatUsd(data.earlier_evaluations.estimated_cost_usd)} in total.
                </p>
              )}
            </>
          )}
        </QueryState>
      </section>

      <section className="mt-12">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Output quality</h2>
          <Link to="/phase-1" className="text-xs text-primary hover:underline">
            Phase 1 results
          </Link>
        </div>
        <QueryState query={evaluations}>{(data) => <QualitySection runs={data.items} />}</QueryState>
      </section>

      <section className="mt-12">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Pipeline</h2>
          <Link to="/pipeline" className="text-xs text-primary hover:underline">
            Runs and memories
          </Link>
        </div>
        <QueryState query={stats}>{(data) => <PipelineSection stats={data} />}</QueryState>
      </section>
    </>
  );
}
