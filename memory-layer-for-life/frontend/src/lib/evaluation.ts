/** Reading stored evaluation results, and the figures the quality screens are built from. */

import type { EvaluationRun } from "@/api/client";
import type { ExtractionOutput } from "@/lib/extraction";

export interface CaseCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface JudgeVerdict {
  covering_memory_indexes: number[];
  primary_memory_index: number | null;
  coverage: string;
  coverage_explanation: string;
  rule_verdicts: { rule_index: number; violated: boolean; explanation: string }[];
  unsupported_claims: { memory_index: number; claim: string }[];
}

export interface ExpectedMemory {
  type: string;
  status: string;
  summary: string;
  attributes: Record<string, unknown>;
}

/** One case as the evaluation saw it: the shape of an entry in a report file. */
export interface CaseDocument {
  case_id: string;
  tags: string[];
  messages: string[];
  expected: { outcome: string; memories: ExpectedMemory[]; must_not: string[] };
  produced: ExtractionOutput | null;
  checks: CaseCheck[];
  judge: JudgeVerdict[];
  error: string | null;
}

export function asCaseDocument(value: unknown): CaseDocument | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<CaseDocument>;
  if (typeof candidate.case_id !== "string" || !Array.isArray(candidate.messages)) return null;
  return {
    case_id: candidate.case_id,
    tags: candidate.tags ?? [],
    messages: candidate.messages,
    expected: candidate.expected ?? { outcome: "", memories: [], must_not: [] },
    produced: candidate.produced ?? null,
    checks: candidate.checks ?? [],
    judge: candidate.judge ?? [],
    error: candidate.error ?? null,
  };
}

export interface CheckTotal {
  name: string;
  passed: number;
  evaluated: number;
}

export function checkTotals(totals: Record<string, unknown>): CheckTotal[] {
  return Object.entries(totals).flatMap(([name, value]) => {
    if (!value || typeof value !== "object") return [];
    const entry = value as { passed?: number; evaluated?: number };
    return [{ name, passed: entry.passed ?? 0, evaluated: entry.evaluated ?? 0 }];
  });
}

export interface Agreement {
  compared: number;
  agree: number;
}

/** Reads one of the comparisons that are reported but do not gate a case. */
export function agreement(notGating: Record<string, unknown>, key: string): Agreement | null {
  const entry = notGating[key];
  if (!entry || typeof entry !== "object") return null;
  const { compared, agree } = entry as { compared?: number; agree?: number };
  if (typeof compared !== "number" || typeof agree !== "number") return null;
  return { compared, agree };
}

export interface ModelScore {
  model: string;
  runs: number;
  fullRuns: number;
  best: number | null;
  worst: number | null;
  latest: number | null;
  casesTotal: number | null;
  totalCost: number;
  meanCostPerFullRun: number | null;
}

function modelOf(run: EvaluationRun): string {
  return run.extractor_model ?? "unknown";
}

/** The size of the dataset is the largest run anyone has done. */
export function datasetSize(runs: EvaluationRun[]): number {
  return runs.reduce((largest, run) => Math.max(largest, run.cases_total), 0);
}

/**
 * A run counts as full when it reached its end, covered the whole dataset, and scored
 * every case. A run the provider cut short says nothing about quality.
 */
export function fullRuns(runs: EvaluationRun[]): EvaluationRun[] {
  const size = datasetSize(runs);
  return runs
    .filter(
      (run) =>
        run.status === "completed" && run.cases_total === size && run.cases_not_evaluated === 0,
    )
    .sort((a, b) => a.started_at.localeCompare(b.started_at));
}

export function scoreboard(runs: EvaluationRun[]): ModelScore[] {
  const complete = fullRuns(runs);
  const models = Array.from(new Set(runs.map(modelOf))).sort();
  return models.map((model) => {
    const own = runs.filter((run) => modelOf(run) === model);
    const ownFull = complete.filter((run) => modelOf(run) === model);
    const priced = ownFull.filter((run) => run.estimated_cost_usd !== null);
    const scores = ownFull.map((run) => run.cases_passed);
    const latest = ownFull.at(-1);
    return {
      model,
      runs: own.length,
      fullRuns: ownFull.length,
      best: scores.length > 0 ? Math.max(...scores) : null,
      worst: scores.length > 0 ? Math.min(...scores) : null,
      latest: latest ? latest.cases_passed : null,
      casesTotal: latest ? latest.cases_total : null,
      totalCost: own.reduce((sum, run) => sum + (run.estimated_cost_usd ?? 0), 0),
      meanCostPerFullRun:
        priced.length > 0
          ? priced.reduce((sum, run) => sum + (run.estimated_cost_usd ?? 0), 0) / priced.length
          : null,
    };
  });
}
