import { describe, expect, it } from "vitest";

import type { EvaluationRun } from "@/api/client";

import { agreement, checkTotals, datasetSize, fullRuns, scoreboard } from "./evaluation";

function run(overrides: Partial<EvaluationRun>): EvaluationRun {
  return {
    id: "run",
    status: "completed",
    trigger: "import",
    dataset_name: "golden.jsonl",
    extractor_model: "claude-haiku-5-5",
    extractor_version: "anthropic:1",
    extraction_effort: "medium",
    judge_model: "claude-haiku-5-5",
    judge_effort: "high",
    judge_prompt_version: "1",
    concurrency: 8,
    cases_total: 124,
    cases_passed: 119,
    cases_failed: 5,
    cases_not_evaluated: 0,
    check_totals: {},
    not_gating: {},
    usage: {},
    estimated_cost_usd: 0.1,
    calls_logged: false,
    source_report: null,
    error_message: null,
    started_at: "2026-10-11T18:53:00Z",
    heartbeat_at: "2026-10-11T18:53:00Z",
    finished_at: "2026-10-11T18:53:00Z",
    created_at: "2026-10-11T18:53:00Z",
    cases_done: 124,
    pass_rate: 119 / 124,
    ...overrides,
  };
}

const SONNET = "claude-sonnet-5-5";
const RUNS = [
  run({ started_at: "2026-10-11T18:53:00Z", cases_passed: 97, cases_failed: 27 }),
  run({ started_at: "2026-10-11T19:09:00Z", cases_passed: 120, cases_failed: 4 }),
  run({
    started_at: "2026-10-11T19:17:00Z",
    extractor_model: SONNET,
    cases_total: 3,
    cases_passed: 3,
    cases_failed: 0,
    estimated_cost_usd: 0.07,
  }),
  run({
    started_at: "2026-10-11T19:19:00Z",
    extractor_model: SONNET,
    cases_passed: 121,
    cases_failed: 3,
    estimated_cost_usd: 1.0,
  }),
  run({
    started_at: "2026-10-11T19:29:00Z",
    extractor_model: SONNET,
    cases_passed: 122,
    cases_failed: 2,
    estimated_cost_usd: 1.2,
  }),
  run({
    started_at: "2026-10-11T19:30:00Z",
    extractor_model: SONNET,
    cases_passed: 75,
    cases_failed: 1,
    cases_not_evaluated: 48,
    estimated_cost_usd: 0.6,
  }),
];

describe("scoreboard", () => {
  it("knows the dataset size from the largest run", () => {
    expect(datasetSize(RUNS)).toBe(124);
    expect(datasetSize([])).toBe(0);
  });

  it("counts only runs that scored the whole dataset as full", () => {
    expect(fullRuns(RUNS).map((entry) => entry.cases_passed)).toEqual([97, 120, 121, 122]);
  });

  it("scores each model by its full runs and adds up the cost of all its runs", () => {
    const [haiku, sonnet] = scoreboard(RUNS);
    expect(haiku).toMatchObject({
      model: "claude-haiku-5-5",
      runs: 2,
      fullRuns: 2,
      best: 120,
      worst: 97,
      latest: 120,
    });
    expect(haiku.meanCostPerFullRun).toBeCloseTo(0.1);
    expect(sonnet).toMatchObject({ model: SONNET, runs: 4, fullRuns: 2, best: 122, latest: 122 });
    expect(sonnet.totalCost).toBeCloseTo(2.87);
    expect(sonnet.meanCostPerFullRun).toBeCloseTo(1.1);
  });
});

describe("stored figures", () => {
  it("reads check totals and ignores anything else", () => {
    expect(
      checkTotals({
        valid_output: { evaluated: 124, passed: 124 },
        odd: "x",
        grounded: { passed: 115 },
      }),
    ).toEqual([
      { name: "valid_output", passed: 124, evaluated: 124 },
      { name: "grounded", passed: 115, evaluated: 0 },
    ]);
  });

  it("reads an agreement count only when it is complete", () => {
    expect(agreement({ disposition: { compared: 124, agree: 118 } }, "disposition")).toEqual({
      compared: 124,
      agree: 118,
    });
    expect(agreement({ disposition: { compared: 124 } }, "disposition")).toBeNull();
    expect(agreement({}, "state")).toBeNull();
  });
});
