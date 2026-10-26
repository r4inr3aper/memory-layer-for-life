"""Memory construction: turn validated extraction output into memory drafts.

This module is pure. It reads the extraction output, the unit's messages, and the
resolution results, and returns drafts. Persisting them is the runner's job.

Rules that hold for every draft:

* Status is always ``proposed``. Whether a draft is accepted on its own, or is a memory
  the user already has, is decided when it is persisted (``app.domain.memory_policy``,
  ADR-048), with the user's existing memories in view.
* Every draft has at least one supporting source. The other messages of the unit are
  linked as contextual sources, because they were read together with the evidence.
* A quote is stored as evidence only when it really occurs in the cited message. A quote
  that cannot be verified is dropped, while the link to the message is kept.
* No validity period is derived. Dates the extractor resolved stay in the metadata.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.domain.enums import MemoryStatus, MemoryType, SourceRole
from app.domain.life_state import LIFE_TYPES
from app.domain.memory_policy import clean_title
from app.domain.normalization import contains_quote, normalize_for_matching
from app.models.raw_message import RawMessage
from app.schemas.extraction import ExtractedMemory, ExtractionOutput
from app.schemas.memory_metadata import MemoryMetadata

_QUOTE_SEPARATOR = "\n"


@dataclass(frozen=True, slots=True)
class SourceDraft:
    raw_message_id: uuid.UUID
    source_role: SourceRole
    evidence_text: str | None


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    ordinal: int
    memory_type: str
    content: str
    normalized_content: str
    status: MemoryStatus
    confidence: float
    observed_at: datetime | None
    metadata: dict[str, Any]
    sources: tuple[SourceDraft, ...]
    entity_ids: tuple[uuid.UUID, ...]
    # When an item someone acts on is due: the date the extractor resolved, if any.
    due_on: date | None = None


class MemoryBuilder:
    def build(
        self,
        output: ExtractionOutput,
        messages: Sequence[RawMessage],
        resolved_entities: Mapping[int, uuid.UUID],
    ) -> list[MemoryDraft]:
        """Build one draft per extracted memory.

        ``resolved_entities`` maps an entity mention's index to the entity it resolved to.
        Mentions that are unresolved or ambiguous are absent and produce no link.
        """
        return [
            self._build_one(ordinal, memory, output, messages, resolved_entities)
            for ordinal, memory in enumerate(output.memories)
        ]

    def _build_one(
        self,
        ordinal: int,
        memory: ExtractedMemory,
        output: ExtractionOutput,
        messages: Sequence[RawMessage],
        resolved_entities: Mapping[int, uuid.UUID],
    ) -> MemoryDraft:
        quotes_by_message: dict[int, list[str]] = {}
        for evidence in memory.evidence:
            quotes = quotes_by_message.setdefault(evidence.message_index, [])
            verified = contains_quote(messages[evidence.message_index].content, evidence.quote)
            if verified and evidence.quote not in quotes:
                quotes.append(evidence.quote)

        sources: list[SourceDraft] = []
        for index, message in enumerate(messages):
            if index in quotes_by_message:
                quotes = quotes_by_message[index]
                sources.append(
                    SourceDraft(
                        raw_message_id=message.id,
                        source_role=SourceRole.SUPPORTING,
                        evidence_text=_QUOTE_SEPARATOR.join(quotes) if quotes else None,
                    )
                )
            else:
                sources.append(
                    SourceDraft(
                        raw_message_id=message.id,
                        source_role=SourceRole.CONTEXTUAL,
                        evidence_text=None,
                    )
                )

        # The memory was observed when its latest supporting message was written.
        supporting_times = [
            sent_at
            for index in quotes_by_message
            if (sent_at := messages[index].source_created_at) is not None
        ]
        observed_at = max(supporting_times, default=None)

        metadata = MemoryMetadata(
            disposition=output.disposition,
            state=memory.state,
            sensitivity=memory.sensitivity,
            ambiguity=memory.ambiguity,
            temporal=memory.temporal,
            financial=memory.financial,
            title=(clean_title(memory.title) or None) if memory.title else None,
        )

        entity_ids: list[uuid.UUID] = []
        for mention_index in memory.entity_mention_indexes:
            entity_id = resolved_entities.get(mention_index)
            if entity_id is not None and entity_id not in entity_ids:
                entity_ids.append(entity_id)

        return MemoryDraft(
            ordinal=ordinal,
            memory_type=memory.memory_type.value,
            content=memory.content,
            normalized_content=normalize_for_matching(memory.content),
            status=MemoryStatus.PROPOSED,
            confidence=round(memory.confidence, 2),
            observed_at=observed_at,
            metadata=metadata.model_dump(mode="json"),
            sources=tuple(sources),
            entity_ids=tuple(entity_ids),
            due_on=(
                memory.temporal.resolved_date
                if memory.temporal is not None and MemoryType(memory.memory_type) in LIFE_TYPES
                else None
            ),
        )
