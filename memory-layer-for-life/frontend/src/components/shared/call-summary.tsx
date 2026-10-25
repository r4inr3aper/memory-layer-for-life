import type { LlmCall } from "@/api/client";
import { KeyValues } from "@/components/shared/key-value";
import { StatusBadge } from "@/components/shared/status-badge";
import { cacheHitRate, formatDateTime, formatDuration, formatPercent, formatTokens, formatUsd } from "@/lib/format";

/** Everything the log knows about one model call. Used wherever a call is shown. */
export function CallSummary({ call }: { call: LlmCall }) {
  const hitRate = cacheHitRate(call.cache_read_input_tokens, call.cache_creation_input_tokens, call.input_tokens);
  return (
    <KeyValues
      entries={[
        { label: "Status", value: <StatusBadge status={call.status} /> },
        { label: "Operation", value: `${call.operation} from ${call.origin}` },
        { label: "Requested model", value: call.requested_model, mono: true },
        {
          label: "Answered by",
          value: call.response_model ?? "no answer",
          mono: true,
        },
        { label: "Effort", value: call.effort ?? "n/a" },
        { label: "Prompt version", value: call.prompt_version ?? "n/a" },
        { label: "Refusal fallback", value: call.refusal_fallback ? "requested" : "off" },
        { label: "Stop reason", value: call.stop_reason ?? "n/a" },
        {
          label: "Tokens",
          value: `${formatTokens(call.input_tokens)} in, ${formatTokens(call.output_tokens)} out, ${formatTokens(call.cache_read_input_tokens)} cached, ${formatTokens(call.cache_creation_input_tokens)} cache writes`,
        },
        { label: "Cache hit rate", value: formatPercent(hitRate) },
        { label: "Estimated cost", value: formatUsd(call.estimated_cost_usd, { precise: true }) },
        { label: "Duration", value: formatDuration(call.duration_ms) },
        { label: "Started", value: formatDateTime(call.started_at) },
        { label: "Request id", value: call.request_id ?? "n/a", mono: true },
        {
          label: "Error",
          value: call.error_code ? `${call.error_code}: ${call.error_message ?? ""}` : "none",
        },
        {
          label: "Provider error",
          value: call.http_status
            ? `HTTP ${call.http_status}${call.provider_error_type ? ` (${call.provider_error_type})` : ""}`
            : call.provider_error_type ?? "none",
        },
        { label: "Call id", value: call.id, mono: true },
      ]}
    />
  );
}
