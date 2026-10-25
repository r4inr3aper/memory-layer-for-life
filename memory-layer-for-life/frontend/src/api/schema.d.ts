/**
 * Types of the API, generated from openapi.json. Do not edit by hand.
 * Regenerate after the backend contract changes: export openapi.json from the
 * application, then run `npm run api-types`.
 */
export interface components {
  schemas: {
    CaseFailureResponse: {
      case_id: string;
      failed: number;
      evaluated: number;
    };
    ConnectionCheckRequest: {
      /** Defaults to the configured model. */
      model?: string | null;
    };
    ConnectionCheckResponse: {
      ok: boolean;
      model: string;
      error_code: string | null;
      error_message: string | null;
      /** The logged call, when it was logged. */
      call: components["schemas"]["LlmCallResponse"] | null;
    };
    /** What the console needs to know about this deployment. It holds no secret. */
    ConsoleConfigResponse: {
      app_name: string;
      environment: string;
      /** Whether model calls can be made. */
      provider_configured: boolean;
      default_model: string;
      default_effort: string;
      default_timezone: string;
      effort_levels: string[];
      models: components["schemas"]["ModelOptionResponse"][];
      prices_checked_on: string;
      prices_source: string;
      /** The pipeline fingerprint in use. */
      pipeline: { [key: string]: string | null };
      limits: components["schemas"]["ConsoleLimitsResponse"];
      evaluation_running: boolean;
      dataset_available: boolean;
    };
    ConsoleLimitsResponse: {
      max_unit_messages: number;
      max_content_chars: number;
    };
    DailyUsageResponse: {
      calls: number;
      failed_calls: number;
      input_tokens: number;
      output_tokens: number;
      cache_read_input_tokens: number;
      cache_creation_input_tokens: number;
      estimated_cost_usd: number;
      /** Calls that are missing from the cost. */
      unpriced_calls: number;
      average_duration_ms: number | null;
      day: string;
      model: string;
    };
    DatasetCaseResponse: {
      case_id: string;
      expected_outcome: components["schemas"]["ExtractionDisposition"];
      tags: string[];
      message_count: number;
      preview: string;
    };
    DatasetResponse: {
      available: boolean;
      name: string;
      /** Why the dataset cannot be used, when it cannot. */
      problem: string | null;
      case_count: number;
      cases: components["schemas"]["DatasetCaseResponse"][];
    };
    /** Evaluation runs imported from report files. Their calls are not in the log. */
    EarlierEvaluationsResponse: {
      runs: number;
      estimated_cost_usd: number;
    };
    EntityType: "person" | "organization" | "project" | "concept" | "place" | "event" | "technology" | "topic";
    ErrorCountResponse: {
      error_code: string;
      calls: number;
      last_seen_at: string;
    };
    ErrorResponse: {
      error_code: string;
      message: string;
      detail?: string | null;
    };
    EvaluationCaseDetailResponse: {
      case_id: string;
      position: number;
      outcome: components["schemas"]["EvaluationCaseOutcome"];
      expected_outcome: components["schemas"]["ExtractionDisposition"];
      produced_disposition: components["schemas"]["ExtractionDisposition"] | null;
      failed_checks: string[];
      error: string | null;
      /** The whole case: source messages, expected memory, produced output, every check, and the judge's explanations. */
      document: { [key: string]: unknown };
    };
    /** Result of one case. ``NOT_EVALUATED`` neither passes nor fails. */
    EvaluationCaseOutcome: "passed" | "failed" | "not_evaluated";
    EvaluationCaseSummaryResponse: {
      case_id: string;
      position: number;
      outcome: components["schemas"]["EvaluationCaseOutcome"];
      expected_outcome: components["schemas"]["ExtractionDisposition"];
      produced_disposition: components["schemas"]["ExtractionDisposition"] | null;
      failed_checks: string[];
      error: string | null;
    };
    EvaluationRunResponse: {
      id: string;
      status: components["schemas"]["EvaluationRunStatus"];
      trigger: components["schemas"]["EvaluationTrigger"];
      dataset_name: string;
      extractor_model: string | null;
      extractor_version: string;
      extraction_effort: string | null;
      judge_model: string | null;
      judge_effort: string | null;
      judge_prompt_version: string | null;
      concurrency: number | null;
      cases_total: number;
      cases_passed: number;
      cases_failed: number;
      cases_not_evaluated: number;
      check_totals: { [key: string]: unknown };
      not_gating: { [key: string]: unknown };
      usage: { [key: string]: unknown };
      estimated_cost_usd: number | null;
      /** False for a run imported from a report file: only its totals are known. */
      calls_logged: boolean;
      source_report: string | null;
      error_message: string | null;
      started_at: string;
      heartbeat_at: string;
      finished_at: string | null;
      created_at: string;
      /** Cases scored or given up on so far. */
      cases_done: number;
      /** Passed cases as a share of evaluated cases. Null before any is evaluated. */
      pass_rate: number | null;
    };
    /** Lifecycle of one evaluation run. */
    EvaluationRunStatus: "running" | "completed" | "failed" | "cancelled" | "interrupted";
    /** Which cases to evaluate and with which models. */
    EvaluationStartRequest: {
      /** Defaults to the configured model. */
      extractor_model?: string | null;
      extraction_effort?: "low" | "medium" | "high" | "xhigh" | "max" | null;
      /** Defaults to the extractor model. */
      judge_model?: string | null;
      judge_effort?: "low" | "medium" | "high" | "xhigh" | "max";
      /** Only these cases. Leave out to run the whole dataset. */
      case_ids?: string[] | null;
      concurrency?: number;
    };
    /** How an evaluation run came to exist. */
    EvaluationTrigger: "console" | "cli" | "import";
    /** The format an extraction must have, for comparing with a test call's output. */
    ExtractionContractResponse: {
      schema_version: string;
      prompt_version: string;
      pipeline_version: string;
      /** JSON Schema of the validated output. */
      output_schema: { [key: string]: unknown };
      /** JSON Schema sent to the provider to constrain generation. */
      provider_schema: { [key: string]: unknown };
    };
    /** What the extractor decided to do with a processing unit. */
    ExtractionDisposition: "extract" | "context" | "abstain";
    ExtractionStatus: "pending" | "succeeded" | "failed" | "needs_review";
    ExtractionSummaryResponse: {
      id: string;
      schema_version: string;
      extractor_version: string;
      model_name: string | null;
      status: components["schemas"]["ExtractionStatus"];
      disposition: components["schemas"]["ExtractionDisposition"] | null;
    };
    HTTPValidationError: {
      detail?: components["schemas"]["ValidationError"][];
    };
    HealthResponse: {
      status: string;
      app_name: string;
      environment: string;
    };
    IngestBatchRequest: {
      units: components["schemas"]["IngestUnitRequest"][];
    };
    IngestBatchResponse: {
      units: components["schemas"]["IngestUnitResponse"][];
    };
    /** One processing unit: messages that belong together and are read together. */
    IngestUnitRequest: {
      messages: components["schemas"]["RawMessageCreate"][];
    };
    IngestUnitResponse: {
      messages: components["schemas"]["IngestedMessageResponse"][];
      processing_run: components["schemas"]["IngestedRunResponse"];
    };
    IngestedMessageResponse: {
      id: string;
      source: components["schemas"]["MessageSource"];
      source_message_id: string | null;
      ingested_at: string;
      /** False when this delivery matched a stored message. */
      created: boolean;
    };
    IngestedRunResponse: {
      id: string;
      status: components["schemas"]["ProcessingStatus"];
      pipeline_version: string;
      attempt_number: number;
      /** False when this unit already had a run for this version. */
      created: boolean;
    };
    JsonValue: unknown;
    LatencyResponse: {
      p50_ms: number | null;
      p95_ms: number | null;
    };
    /** Which part of the system made a model call. */
    LlmCallOrigin: "pipeline" | "playground" | "evaluation" | "other";
    /** One logged call to a model provider. Facts about the call, never its content. */
    LlmCallResponse: {
      id: string;
      provider: string;
      operation: components["schemas"]["LlmOperation"];
      origin: components["schemas"]["LlmCallOrigin"];
      status: components["schemas"]["LlmCallStatus"];
      requested_model: string;
      /** The model that answered. It differs after a refusal fallback. */
      response_model: string | null;
      prompt_version: string | null;
      effort: string | null;
      max_tokens: number | null;
      refusal_fallback: boolean;
      stop_reason: string | null;
      request_id: string | null;
      http_status: number | null;
      provider_error_type: string | null;
      error_code: string | null;
      error_message: string | null;
      input_tokens: number;
      output_tokens: number;
      cache_read_input_tokens: number;
      cache_creation_input_tokens: number;
      /** Estimate from list prices. Null when the model's price is not known. */
      estimated_cost_usd: number | null;
      started_at: string;
      duration_ms: number;
      processing_run_id: string | null;
      attempt_number: number | null;
      evaluation_run_id: string | null;
      evaluation_case_id: string | null;
      playground_run_id: string | null;
      created_at: string;
    };
    LlmCallStatus: "succeeded" | "failed";
    /** What a model call was made for. */
    LlmOperation: "extraction" | "judge" | "connection_check";
    MemoryDetailResponse: {
      id: string;
      memory_type: components["schemas"]["MemoryType"];
      content: string;
      normalized_content: string | null;
      status: components["schemas"]["MemoryStatus"];
      confidence: number | null;
      valid_from: string | null;
      valid_until: string | null;
      observed_at: string | null;
      supersedes_memory_id: string | null;
      metadata: { [key: string]: unknown };
      created_at: string;
      updated_at: string;
      sources: components["schemas"]["MemorySourceResponse"][];
      entities: components["schemas"]["MemoryEntityResponse"][];
    };
    MemoryEntityRelation: "mentions";
    MemoryEntityResponse: {
      entity_id: string;
      entity_type: components["schemas"]["EntityType"];
      canonical_name: string;
      relationship_type: components["schemas"]["MemoryEntityRelation"];
    };
    MemoryResponse: {
      id: string;
      memory_type: components["schemas"]["MemoryType"];
      content: string;
      normalized_content: string | null;
      status: components["schemas"]["MemoryStatus"];
      confidence: number | null;
      valid_from: string | null;
      valid_until: string | null;
      observed_at: string | null;
      supersedes_memory_id: string | null;
      metadata: { [key: string]: unknown };
      created_at: string;
      updated_at: string;
    };
    /** One piece of evidence behind a memory, with the original message it points to. */
    MemorySourceResponse: {
      raw_message_id: string;
      extraction_result_id: string;
      processing_run_id: string;
      source_role: components["schemas"]["SourceRole"];
      evidence_text: string | null;
      source: components["schemas"]["MessageSource"];
      source_message_id: string | null;
      source_created_at: string | null;
      content: string;
    };
    MemoryStatus: "proposed" | "active" | "superseded" | "retracted";
    MemoryType: "semantic_fact" | "episodic_event" | "preference" | "intention" | "task" | "commitment" | "goal" | "project" | "decision" | "idea" | "open_loop" | "plan" | "note" | "reflection" | "resource" | "financial_note";
    MessageSource: "whatsapp_import" | "manual_capture" | "api_input";
    /** A model that can be chosen for a test call or an evaluation. */
    ModelOptionResponse: {
      id: string;
      display_name: string;
      is_default: boolean;
      supports_refusal_fallback: boolean;
      /** Null when the price is not known. */
      prices: components["schemas"]["ModelPricesResponse"] | null;
    };
    /** List prices in US dollars per million tokens. */
    ModelPricesResponse: {
      input_usd_per_mtok: number;
      output_usd_per_mtok: number;
      cache_write_usd_per_mtok: number;
      cache_read_usd_per_mtok: number;
    };
    Page_EvaluationCaseSummaryResponse_: {
      items: components["schemas"]["EvaluationCaseSummaryResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    Page_EvaluationRunResponse_: {
      items: components["schemas"]["EvaluationRunResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    Page_LlmCallResponse_: {
      items: components["schemas"]["LlmCallResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    Page_MemoryResponse_: {
      items: components["schemas"]["MemoryResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    Page_PlaygroundRunSummaryResponse_: {
      items: components["schemas"]["PlaygroundRunSummaryResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    Page_ProcessingRunResponse_: {
      items: components["schemas"]["ProcessingRunResponse"][];
      total: number;
      limit: number;
      offset: number;
    };
    /** Stages of one processing run, in execution order. */
    PipelineStage: "normalize" | "extract" | "resolve" | "construct" | "persist";
    PipelineStatsResponse: {
      raw_messages: number;
      entities: number;
      runs_by_status: { [key: string]: number };
      extractions_by_disposition: { [key: string]: number };
      memories_by_type: { [key: string]: number };
      memories_by_status: { [key: string]: number };
      mentions_by_resolution: { [key: string]: number };
    };
    PlaygroundMessageInput: {
      text: string;
      /** When the message was written. Needed to read words like 'tomorrow'. */
      sent_at?: string | null;
    };
    PlaygroundMessageResponse: {
      index: number;
      text: string;
      sent_at: string | null;
    };
    /** One test call. Nothing it produces is stored as a raw message or a memory. */
    PlaygroundRunRequest: {
      messages: components["schemas"]["PlaygroundMessageInput"][];
      /** Defaults to the configured model. */
      model?: string | null;
      effort?: "low" | "medium" | "high" | "xhigh" | "max" | null;
      /** IANA timezone of the writer. */
      timezone?: string | null;
    };
    PlaygroundRunResponse: {
      id: string;
      status: components["schemas"]["PlaygroundRunStatus"];
      messages: components["schemas"]["PlaygroundMessageResponse"][];
      timezone_name: string | null;
      requested_model: string;
      effort: string;
      /** The validated extraction, after the checks the pipeline applies. */
      output: { [key: string]: unknown } | null;
      /** The text the model returned, as it came. */
      raw_output: string | null;
      /** What the system changed in the output. */
      corrections: string[];
      error_code: string | null;
      error_message: string | null;
      created_at: string;
      finished_at: string | null;
      /** The model call this test made. */
      call: components["schemas"]["LlmCallResponse"] | null;
    };
    PlaygroundRunStatus: "running" | "succeeded" | "failed";
    PlaygroundRunSummaryResponse: {
      id: string;
      status: components["schemas"]["PlaygroundRunStatus"];
      requested_model: string;
      effort: string;
      message_count: number;
      /** The start of the first message. */
      preview: string;
      error_code: string | null;
      created_at: string;
      finished_at: string | null;
    };
    ProcessingRunDetailResponse: {
      id: string;
      status: components["schemas"]["ProcessingStatus"];
      pipeline_version: string;
      attempt_number: number;
      /** The unit, in processing order. */
      raw_message_ids: string[];
      available_at: string;
      started_at: string | null;
      finished_at: string | null;
      error_code: string | null;
      error_message: string | null;
      created_at: string;
      events: components["schemas"]["ProcessingRunEventResponse"][];
      extraction: components["schemas"]["ExtractionSummaryResponse"] | null;
      memory_ids: string[];
    };
    ProcessingRunEventResponse: {
      id: string;
      attempt_number: number;
      event_type: components["schemas"]["RunEventType"];
      stage: components["schemas"]["PipelineStage"] | null;
      error_code: string | null;
      detail: string | null;
      created_at: string;
    };
    ProcessingRunResponse: {
      id: string;
      status: components["schemas"]["ProcessingStatus"];
      pipeline_version: string;
      attempt_number: number;
      /** The unit, in processing order. */
      raw_message_ids: string[];
      available_at: string;
      started_at: string | null;
      finished_at: string | null;
      error_code: string | null;
      error_message: string | null;
      created_at: string;
    };
    ProcessingStatus: "queued" | "running" | "succeeded" | "failed" | "needs_review";
    /** Source envelope of one incoming message. */
    RawMessageCreate: {
      source: components["schemas"]["MessageSource"];
      content: string;
      source_message_id?: string | null;
      source_created_at?: string | null;
      metadata?: { [key: string]: components["schemas"]["JsonValue"] };
    };
    ReadinessResponse: {
      status: string;
      database: string;
      details?: string | null;
    };
    /** What a replay request did for one processing unit. */
    ReplayAction: "created" | "requeued" | "unchanged";
    ReplayOutcomeResponse: {
      action: components["schemas"]["ReplayAction"];
      processing_run: components["schemas"]["ProcessingRunResponse"];
    };
    /** Selects which units to reprocess under the current pipeline configuration. */
    ReplayRequest: {
      raw_message_ids?: string[] | null;
      run_ids?: string[] | null;
      all_units?: boolean;
      limit?: number;
    };
    ReplayResponse: {
      outcomes: components["schemas"]["ReplayOutcomeResponse"][];
    };
    ReportResponse: {
      slug: string;
      title: string;
      markdown: string;
      updated_at: string;
    };
    /** Entries of the append-only processing run audit log. */
    RunEventType: "queued" | "claimed" | "extraction_stored" | "extraction_reused" | "retry_scheduled" | "succeeded" | "needs_review" | "failed" | "requeued" | "lease_expired";
    SourceRole: "supporting" | "contradicting" | "contextual";
    UsageGroupResponse: {
      calls: number;
      failed_calls: number;
      input_tokens: number;
      output_tokens: number;
      cache_read_input_tokens: number;
      cache_creation_input_tokens: number;
      estimated_cost_usd: number;
      /** Calls that are missing from the cost. */
      unpriced_calls: number;
      average_duration_ms: number | null;
      key: string;
    };
    UsageSummaryResponse: {
      totals: components["schemas"]["UsageTotalsResponse"];
      latency: components["schemas"]["LatencyResponse"];
      by_model: components["schemas"]["UsageGroupResponse"][];
      by_origin: components["schemas"]["UsageGroupResponse"][];
      by_operation: components["schemas"]["UsageGroupResponse"][];
      by_day: components["schemas"]["DailyUsageResponse"][];
      errors: components["schemas"]["ErrorCountResponse"][];
      earlier_evaluations: components["schemas"]["EarlierEvaluationsResponse"];
      first_day: string | null;
      last_day: string | null;
      /** Days are calendar days in this timezone. */
      timezone: string;
    };
    UsageTotalsResponse: {
      calls: number;
      failed_calls: number;
      input_tokens: number;
      output_tokens: number;
      cache_read_input_tokens: number;
      cache_creation_input_tokens: number;
      estimated_cost_usd: number;
      /** Calls that are missing from the cost. */
      unpriced_calls: number;
      average_duration_ms: number | null;
    };
    ValidationError: {
      loc: (string | number)[];
      msg: string;
      type: string;
      input?: unknown;
      ctx?: { [key: string]: unknown };
    };
  };
}
