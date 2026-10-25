/** The extraction output as the pipeline validates it (contract version 1.0). */

export interface EvidenceReference {
  message_index: number;
  quote: string;
}

export interface TemporalInfo {
  expression: string;
  resolved_date: string | null;
}

export interface FinancialInfo {
  amount: number | null;
  component_amounts: number[];
  currency: string | null;
  category: string | null;
  counterparty: string | null;
  calculation: string | null;
}

export interface ExtractedMemory {
  memory_type: string;
  content: string;
  state: string;
  confidence: number;
  sensitivity: string;
  evidence: EvidenceReference[];
  ambiguity: string | null;
  temporal: TemporalInfo | null;
  financial: FinancialInfo | null;
  entity_mention_indexes: number[];
}

export interface EntityMention {
  entity_type: string;
  mention_text: string;
  message_index: number;
  confidence: number;
}

export interface ExtractionOutput {
  disposition: string;
  disposition_reason: string;
  memories: ExtractedMemory[];
  entity_mentions: EntityMention[];
}

/** Reads an untyped payload as an extraction output, or gives null when it is not one. */
export function asExtractionOutput(value: unknown): ExtractionOutput | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ExtractionOutput>;
  if (typeof candidate.disposition !== "string" || !Array.isArray(candidate.memories)) return null;
  return {
    disposition: candidate.disposition,
    disposition_reason: candidate.disposition_reason ?? "",
    memories: candidate.memories,
    entity_mentions: Array.isArray(candidate.entity_mentions) ? candidate.entity_mentions : [],
  };
}

export function describeFinancial(financial: FinancialInfo): string {
  const parts: string[] = [];
  if (financial.amount !== null) parts.push(`${financial.currency ?? ""} ${financial.amount}`.trim());
  if (financial.calculation) parts.push(`from ${financial.calculation}`);
  if (financial.counterparty) parts.push(`with ${financial.counterparty}`);
  if (financial.category) parts.push(`(${financial.category})`);
  if (financial.amount === null && financial.component_amounts.length > 0) {
    parts.push(`amounts ${financial.component_amounts.join(", ")}`);
  }
  return parts.join(" ") || "an amount, not specified";
}
