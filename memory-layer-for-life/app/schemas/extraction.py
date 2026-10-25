"""Extraction contract, schema version 1.0.

``ExtractionOutput`` is what an extractor returns for one processing unit. It is the
structured-output schema sent to the model, so every field is required and field
descriptions are written for the model. System-owned facts such as ids, timestamps, and
character offsets are deliberately absent: they are never requested from a model.

``ExtractionPayload`` is the envelope persisted in ``extraction_results.payload``.

Model output is untrusted. Nothing here is persisted before it validates, and
``app.services.processing.extraction`` adds the checks that need the source messages.
"""

import uuid
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    EntityType,
    ExtractionDisposition,
    MemoryState,
    MemoryType,
    Sensitivity,
)
from app.domain.versions import EXTRACTION_SCHEMA_VERSION


class ContractModel(BaseModel):
    """Base for contract types: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class EvidenceReference(ContractModel):
    message_index: int = Field(
        ge=0, description="Zero-based index of the message that supports the memory."
    )
    quote: str = Field(
        min_length=1,
        description="Words copied exactly from that message. Never paraphrase a quote.",
    )


class TemporalInfo(ContractModel):
    expression: str = Field(
        min_length=1,
        description="The time expression exactly as written, such as 'tomorrow' or 'Jan 14'.",
    )
    resolved_date: date | None = Field(
        description=(
            "The calendar date the expression refers to. Fill it only when the date is "
            "fully determined by the expression and the message date. Use null whenever "
            "the year, the week, or the day is uncertain."
        )
    )


class FinancialInfo(ContractModel):
    amount: float | None = Field(
        description=(
            "The single amount the note is about: the one stated number, or the result of "
            "simple arithmetic written in the message. Use null when there are several "
            "separate amounts or when no single amount is clear."
        )
    )
    component_amounts: list[float] = Field(
        description="Every money amount written in the messages, in order of appearance."
    )
    currency: str | None = Field(
        description=(
            "ISO 4217 code, only when a currency symbol, code, or name is written in the "
            "message. Use null otherwise. Never infer a currency from context or location."
        )
    )
    category: str | None = Field(
        description="Short lowercase spending category such as 'food', or null if unclear."
    )
    counterparty: str | None = Field(
        description="Person or merchant the amount relates to, as written, or null."
    )
    calculation: str | None = Field(
        description="The arithmetic exactly as written, such as '232 + 104', or null."
    )


class ExtractedMemory(ContractModel):
    memory_type: MemoryType
    content: str = Field(
        min_length=1,
        description="One clear, self-contained statement of the memory, grounded in the source.",
    )
    state: MemoryState = Field(
        description=(
            "'done' only when the source explicitly says it happened or was completed. "
            "'open' for an action, question, or issue not stated as resolved. 'planned' "
            "when it is placed in a plan or schedule. 'not_applicable' for everything else."
        )
    )
    confidence: float = Field(
        ge=0, le=1, description="How sure you are that this reading is correct, from 0 to 1."
    )
    sensitivity: Sensitivity = Field(
        description="'sensitive' for health, emotional, or otherwise private personal content."
    )
    evidence: list[EvidenceReference] = Field(
        min_length=1, description="The messages this memory rests on. At least one."
    )
    ambiguity: str | None = Field(
        description="What is unclear or could be read differently, or null if nothing is."
    )
    temporal: TemporalInfo | None = Field(
        description="Present only when the source contains a time expression for this memory."
    )
    financial: FinancialInfo | None = Field(
        description="Present only when the memory involves an amount of money."
    )
    entity_mention_indexes: list[int] = Field(
        description=(
            "Zero-based positions in this output's entity_mentions list of the entities this "
            "memory involves. Every value must be a valid position in that list. Use an empty "
            "list when the memory involves none."
        )
    )


class ExtractedEntityMention(ContractModel):
    entity_type: EntityType
    mention_text: str = Field(
        min_length=1,
        max_length=1000,
        description="The name exactly as written in the message. Do not expand or correct it.",
    )
    message_index: int = Field(
        ge=0, description="Zero-based index of the message that contains the mention."
    )
    confidence: float = Field(ge=0, le=1)


class ExtractionOutput(ContractModel):
    """Everything an extractor returns for one processing unit."""

    disposition: ExtractionDisposition
    disposition_reason: str = Field(
        min_length=1, description="One sentence explaining the disposition."
    )
    memories: list[ExtractedMemory]
    entity_mentions: list[ExtractedEntityMention]

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> Self:
        abstained = self.disposition is ExtractionDisposition.ABSTAIN
        if abstained and self.memories:
            raise ValueError("An abstaining extraction cannot contain memories.")
        if not abstained and not self.memories:
            raise ValueError("A non-abstaining extraction needs at least one memory.")

        mention_count = len(self.entity_mentions)
        for position, memory in enumerate(self.memories):
            indexes = memory.entity_mention_indexes
            if len(set(indexes)) != len(indexes):
                raise ValueError(f"Memory {position} lists an entity mention more than once.")
            if any(index < 0 or index >= mention_count for index in indexes):
                raise ValueError(f"Memory {position} points at an entity mention out of range.")
        return self


class ExtractionPayload(ContractModel):
    """Persisted form of an extraction result.

    ``message_ids`` records which raw message each ``message_index`` of the output refers
    to, so the payload stays interpretable on its own.
    """

    schema_version: Literal["1.0"] = EXTRACTION_SCHEMA_VERSION
    normalizer_version: str
    message_ids: list[uuid.UUID] = Field(min_length=1)
    output: ExtractionOutput
