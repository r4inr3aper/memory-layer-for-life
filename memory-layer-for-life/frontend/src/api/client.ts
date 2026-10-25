/**
 * Typed access to the console's API.
 *
 * The shapes come from the OpenAPI document the backend publishes (`npm run api-types`
 * regenerates `schema.d.ts` from `openapi.json`), so a changed response fails the build
 * here instead of failing a page at runtime.
 */
import type { components } from "./schema";

export type Schemas = components["schemas"];

export type ConsoleConfig = Schemas["ConsoleConfigResponse"];
export type ModelOption = Schemas["ModelOptionResponse"];
export type ConnectionCheck = Schemas["ConnectionCheckResponse"];
export type PipelineStats = Schemas["PipelineStatsResponse"];
export type LlmCall = Schemas["LlmCallResponse"];
export type LlmCallOrigin = Schemas["LlmCallOrigin"];
export type LlmOperation = Schemas["LlmOperation"];
export type LlmCallStatus = Schemas["LlmCallStatus"];
export type UsageSummary = Schemas["UsageSummaryResponse"];
export type UsageTotals = Schemas["UsageTotalsResponse"];
export type UsageGroup = Schemas["UsageGroupResponse"];
export type DailyUsage = Schemas["DailyUsageResponse"];
export type PlaygroundRun = Schemas["PlaygroundRunResponse"];
export type PlaygroundRunSummary = Schemas["PlaygroundRunSummaryResponse"];
export type PlaygroundRequest = Schemas["PlaygroundRunRequest"];
export type PlaygroundMessageInput = Schemas["PlaygroundMessageInput"];
export type ExtractionContract = Schemas["ExtractionContractResponse"];
export type EvaluationRun = Schemas["EvaluationRunResponse"];
export type EvaluationRunStatus = Schemas["EvaluationRunStatus"];
export type EvaluationStartRequest = Schemas["EvaluationStartRequest"];
export type EvaluationCaseSummary = Schemas["EvaluationCaseSummaryResponse"];
export type EvaluationCaseDetail = Schemas["EvaluationCaseDetailResponse"];
export type EvaluationCaseOutcome = Schemas["EvaluationCaseOutcome"];
export type Dataset = Schemas["DatasetResponse"];
export type CaseFailure = Schemas["CaseFailureResponse"];
export type ProcessingRun = Schemas["ProcessingRunResponse"];
export type ProcessingRunDetail = Schemas["ProcessingRunDetailResponse"];
export type ProcessingStatus = Schemas["ProcessingStatus"];
export type Memory = Schemas["MemoryResponse"];
export type MemoryDetail = Schemas["MemoryDetailResponse"];
export type MemoryType = Schemas["MemoryType"];
export type ReplayRequest = Schemas["ReplayRequest"];
export type ReplayResponse = Schemas["ReplayResponse"];
export type IngestUnitRequest = Schemas["IngestUnitRequest"];
export type IngestUnitResponse = Schemas["IngestUnitResponse"];
export type Report = Schemas["ReportResponse"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type EffortLevel = "low" | "medium" | "high" | "xhigh" | "max";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Paging {
  limit?: number;
  offset?: number;
}

export interface CallFilters {
  origin?: LlmCallOrigin | null;
  operation?: LlmOperation | null;
  status?: LlmCallStatus | null;
  model?: string | null;
  processing_run_id?: string | null;
  evaluation_run_id?: string | null;
  playground_run_id?: string | null;
  started_from?: string | null;
  started_before?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | null;

  constructor(status: number, code: string, message: string, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail ? `${error.message} ${error.detail}` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

type Query = Record<string, string | number | boolean | null | undefined>;

const API_PREFIX = "/api/v1";

function queryString(params?: Query): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

function requestId(): string {
  return `ui-${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: Partial<ErrorResponse> = {};
  try {
    body = (await response.json()) as Partial<ErrorResponse>;
  } catch {
    // Not a JSON body: the status is all there is.
  }
  return new ApiError(
    response.status,
    body.error_code ?? `HTTP_${response.status}`,
    body.message ?? (response.statusText || "The request failed."),
    body.detail ?? null,
  );
}

async function request<T>(method: string, path: string, body?: unknown, params?: Query): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}${queryString(params)}`, {
    method,
    headers: {
      Accept: "application/json",
      "X-Request-ID": requestId(),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

export const api = {
  health: {
    ready: () => request<ReadinessResponse>("GET", "/health/ready"),
  },
  console: {
    config: () => request<ConsoleConfig>("GET", "/console/config"),
    connectionCheck: (model?: string | null) =>
      request<ConnectionCheck>("POST", "/console/connection-check", { model: model ?? null }),
    pipelineStats: () => request<PipelineStats>("GET", "/console/pipeline-stats"),
  },
  calls: {
    list: (params: CallFilters & Paging) =>
      request<Page<LlmCall>>("GET", "/llm-calls", undefined, params as Query),
    usage: (params: CallFilters) =>
      request<UsageSummary>("GET", "/llm-calls/usage", undefined, params as Query),
    get: (id: string) => request<LlmCall>("GET", `/llm-calls/${id}`),
  },
  playground: {
    run: (body: PlaygroundRequest) => request<PlaygroundRun>("POST", "/playground/extractions", body),
    list: (params: Paging) =>
      request<Page<PlaygroundRunSummary>>("GET", "/playground/extractions", undefined, params as Query),
    get: (id: string) => request<PlaygroundRun>("GET", `/playground/extractions/${id}`),
    contract: () => request<ExtractionContract>("GET", "/playground/contract"),
  },
  evaluations: {
    list: (params: Paging & { status?: EvaluationRunStatus | null; extractor_model?: string | null }) =>
      request<Page<EvaluationRun>>("GET", "/evaluations", undefined, params as Query),
    start: (body: EvaluationStartRequest) => request<EvaluationRun>("POST", "/evaluations", body),
    get: (id: string) => request<EvaluationRun>("GET", `/evaluations/${id}`),
    cases: (id: string, params: Paging & { outcome?: EvaluationCaseOutcome | null }) =>
      request<Page<EvaluationCaseSummary>>("GET", `/evaluations/${id}/cases`, undefined, params as Query),
    case: (id: string, caseId: string) =>
      request<EvaluationCaseDetail>("GET", `/evaluations/${id}/cases/${encodeURIComponent(caseId)}`),
    dataset: () => request<Dataset>("GET", "/evaluations/dataset"),
    failingCases: (params: { extractor_model?: string | null; limit?: number }) =>
      request<CaseFailure[]>("GET", "/evaluations/failing-cases", undefined, params as Query),
    cancel: (id: string) => request<EvaluationRun>("POST", `/evaluations/${id}/cancel`),
  },
  pipeline: {
    runs: (params: Paging & { status?: ProcessingStatus | null; raw_message_id?: string | null }) =>
      request<Page<ProcessingRun>>("GET", "/processing/runs", undefined, params as Query),
    run: (id: string) => request<ProcessingRunDetail>("GET", `/processing/runs/${id}`),
    replay: (body: ReplayRequest) => request<ReplayResponse>("POST", "/processing/replays", body),
    memories: (params: Paging & { status?: string | null; memory_type?: MemoryType | null; processing_run_id?: string | null }) =>
      request<Page<Memory>>("GET", "/memories", undefined, params as Query),
    memory: (id: string) => request<MemoryDetail>("GET", `/memories/${id}`),
    ingest: (body: IngestUnitRequest) => request<IngestUnitResponse>("POST", "/ingestion/units", body),
  },
  reports: {
    get: (slug: string) => request<Report>("GET", `/reports/${slug}`),
  },
};
