"""Validated shape of ``memories.metadata``.

JSONB is used for attributes that vary by memory type. It is still a contract: the
pipeline and the memory service write this model and readers can validate against it.
``disposition`` is the extractor's; a memory the user wrote has none.
"""

from typing import Literal

from app.domain.enums import ExtractionDisposition, MemoryState, Sensitivity
from app.schemas.extraction import ContractModel, FinancialInfo, TemporalInfo

MEMORY_METADATA_VERSION: Literal["1.0"] = "1.0"


class MemoryMetadata(ContractModel):
    schema_version: Literal["1.0"] = MEMORY_METADATA_VERSION
    disposition: ExtractionDisposition | None = None
    state: MemoryState
    sensitivity: Sensitivity
    ambiguity: str | None = None
    temporal: TemporalInfo | None = None
    financial: FinancialInfo | None = None
