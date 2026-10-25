import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  type CallFilters,
  type EvaluationCaseOutcome,
  type EvaluationRunStatus,
  type EvaluationStartRequest,
  type IngestUnitRequest,
  type MemoryType,
  type Paging,
  type PlaygroundRequest,
  type ProcessingStatus,
  type ReplayRequest,
} from "./client";

export const keys = {
  config: ["config"] as const,
  readiness: ["readiness"] as const,
  pipelineStats: ["pipeline-stats"] as const,
  calls: (params: object) => ["calls", params] as const,
  usage: (params: object) => ["usage", params] as const,
  call: (id: string) => ["call", id] as const,
  playgroundRuns: (params: object) => ["playground", "runs", params] as const,
  playgroundRun: (id: string) => ["playground", "run", id] as const,
  contract: ["contract"] as const,
  evaluations: (params: object) => ["evaluations", params] as const,
  evaluation: (id: string) => ["evaluation", id] as const,
  evaluationCases: (id: string, params: object) => ["evaluation", id, "cases", params] as const,
  evaluationCase: (id: string, caseId: string) => ["evaluation", id, "case", caseId] as const,
  dataset: ["dataset"] as const,
  failingCases: (params: object) => ["failing-cases", params] as const,
  runs: (params: object) => ["runs", params] as const,
  run: (id: string) => ["run", id] as const,
  memories: (params: object) => ["memories", params] as const,
  memory: (id: string) => ["memory", id] as const,
  report: (slug: string) => ["report", slug] as const,
};

// --- Console -------------------------------------------------------------------------

export function useConfig() {
  return useQuery({ queryKey: keys.config, queryFn: api.console.config, staleTime: 60_000 });
}

export function useReadiness() {
  return useQuery({
    queryKey: keys.readiness,
    queryFn: api.health.ready,
    refetchInterval: 30_000,
    retry: false,
  });
}

export function usePipelineStats() {
  return useQuery({ queryKey: keys.pipelineStats, queryFn: api.console.pipelineStats });
}

export function useConnectionCheck() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (model?: string | null) => api.console.connectionCheck(model),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ["calls"] });
      void client.invalidateQueries({ queryKey: ["usage"] });
    },
  });
}

// --- Model calls ---------------------------------------------------------------------

export function useCalls(params: CallFilters & Paging) {
  return useQuery({ queryKey: keys.calls(params), queryFn: () => api.calls.list(params) });
}

export function useUsage(params: CallFilters) {
  return useQuery({ queryKey: keys.usage(params), queryFn: () => api.calls.usage(params) });
}

export function useCall(id: string | null) {
  return useQuery({
    queryKey: keys.call(id ?? ""),
    queryFn: () => api.calls.get(id as string),
    enabled: id !== null,
  });
}

// --- Playground ----------------------------------------------------------------------

export function usePlaygroundRuns(params: Paging) {
  return useQuery({
    queryKey: keys.playgroundRuns(params),
    queryFn: () => api.playground.list(params),
  });
}

export function usePlaygroundRun(id: string | null) {
  return useQuery({
    queryKey: keys.playgroundRun(id ?? ""),
    queryFn: () => api.playground.get(id as string),
    enabled: id !== null,
  });
}

export function useContract() {
  return useQuery({ queryKey: keys.contract, queryFn: api.playground.contract, staleTime: Infinity });
}

export function useRunPlayground() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PlaygroundRequest) => api.playground.run(body),
    onSuccess: (run) => {
      client.setQueryData(keys.playgroundRun(run.id), run);
      void client.invalidateQueries({ queryKey: ["playground", "runs"] });
      void client.invalidateQueries({ queryKey: ["calls"] });
      void client.invalidateQueries({ queryKey: ["usage"] });
    },
  });
}

// --- Evaluations ---------------------------------------------------------------------

export function useEvaluations(
  params: Paging & { status?: EvaluationRunStatus | null; extractor_model?: string | null },
) {
  return useQuery({
    queryKey: keys.evaluations(params),
    queryFn: () => api.evaluations.list(params),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => run.status === "running") ? 3000 : false,
  });
}

export function useEvaluation(id: string | null) {
  return useQuery({
    queryKey: keys.evaluation(id ?? ""),
    queryFn: () => api.evaluations.get(id as string),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
}

export function useEvaluationCases(
  id: string | null,
  params: Paging & { outcome?: EvaluationCaseOutcome | null },
  options?: { live?: boolean },
) {
  return useQuery({
    queryKey: keys.evaluationCases(id ?? "", params),
    queryFn: () => api.evaluations.cases(id as string, params),
    enabled: id !== null,
    refetchInterval: options?.live ? 2000 : false,
  });
}

export function useEvaluationCase(id: string | null, caseId: string | null) {
  return useQuery({
    queryKey: keys.evaluationCase(id ?? "", caseId ?? ""),
    queryFn: () => api.evaluations.case(id as string, caseId as string),
    enabled: id !== null && caseId !== null,
  });
}

export function useDataset() {
  return useQuery({ queryKey: keys.dataset, queryFn: api.evaluations.dataset, staleTime: 60_000 });
}

export function useFailingCases(params: { extractor_model?: string | null; limit?: number }) {
  return useQuery({
    queryKey: keys.failingCases(params),
    queryFn: () => api.evaluations.failingCases(params),
  });
}

export function useStartEvaluation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: EvaluationStartRequest) => api.evaluations.start(body),
    onSuccess: (run) => {
      client.setQueryData(keys.evaluation(run.id), run);
      void client.invalidateQueries({ queryKey: ["evaluations"] });
      void client.invalidateQueries({ queryKey: keys.config });
    },
  });
}

export function useCancelEvaluation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.evaluations.cancel(id),
    onSuccess: (run) => {
      client.setQueryData(keys.evaluation(run.id), run);
      void client.invalidateQueries({ queryKey: ["evaluations"] });
      void client.invalidateQueries({ queryKey: keys.config });
    },
  });
}

// --- Pipeline ------------------------------------------------------------------------

export function useRuns(
  params: Paging & { status?: ProcessingStatus | null; raw_message_id?: string | null },
) {
  return useQuery({ queryKey: keys.runs(params), queryFn: () => api.pipeline.runs(params) });
}

export function useRun(id: string | null) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: () => api.pipeline.run(id as string),
    enabled: id !== null,
    // A run that is still moving is watched until it settles.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });
}

export function useMemories(
  params: Paging & { status?: string | null; memory_type?: MemoryType | null; processing_run_id?: string | null },
) {
  return useQuery({ queryKey: keys.memories(params), queryFn: () => api.pipeline.memories(params) });
}

export function useMemory(id: string | null) {
  return useQuery({
    queryKey: keys.memory(id ?? ""),
    queryFn: () => api.pipeline.memory(id as string),
    enabled: id !== null,
  });
}

function invalidatePipeline(client: ReturnType<typeof useQueryClient>) {
  void client.invalidateQueries({ queryKey: ["runs"] });
  void client.invalidateQueries({ queryKey: ["run"] });
  void client.invalidateQueries({ queryKey: ["memories"] });
  void client.invalidateQueries({ queryKey: keys.pipelineStats });
  void client.invalidateQueries({ queryKey: ["calls"] });
  void client.invalidateQueries({ queryKey: ["usage"] });
}

export function useIngest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: IngestUnitRequest) => api.pipeline.ingest(body),
    onSuccess: () => invalidatePipeline(client),
  });
}

export function useReplay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReplayRequest) => api.pipeline.replay(body),
    onSuccess: () => invalidatePipeline(client),
  });
}

// --- Reports -------------------------------------------------------------------------

export function useReport(slug: string) {
  return useQuery({ queryKey: keys.report(slug), queryFn: () => api.reports.get(slug), retry: false });
}
