"""Versions of the pipeline components and the fingerprint that identifies a configuration.

Bump a component version whenever its behavior changes in a way that can change stored
output. A changed fingerprint yields a new processing identity, so replaying a unit
creates a new historical run instead of silently rewriting the old one.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Final

# Human-readable label stored on every processing run.
PIPELINE_VERSION: Final = "1.0.0"

NORMALIZER_VERSION: Final = "1"
EXTRACTION_SCHEMA_VERSION: Final = "1.1"
RESOLVER_VERSION: Final = "1"
MEMORY_BUILDER_VERSION: Final = "2"


@dataclass(frozen=True, slots=True)
class ExtractorDescriptor:
    """Identifies one extractor implementation and its configuration."""

    provider: str
    model: str | None
    prompt_version: str

    @property
    def version(self) -> str:
        """Compact identifier stored in ``extraction_results.extractor_version``."""
        return f"{self.provider}:{self.prompt_version}"


@dataclass(frozen=True, slots=True)
class PipelineFingerprint:
    """Everything that can change what a processing run produces."""

    pipeline_version: str
    normalizer_version: str
    schema_version: str
    extractor_provider: str
    extractor_model: str | None
    extractor_prompt_version: str
    resolver_version: str
    memory_builder_version: str

    @classmethod
    def for_extractor(cls, extractor: ExtractorDescriptor) -> "PipelineFingerprint":
        return cls(
            pipeline_version=PIPELINE_VERSION,
            normalizer_version=NORMALIZER_VERSION,
            schema_version=EXTRACTION_SCHEMA_VERSION,
            extractor_provider=extractor.provider,
            extractor_model=extractor.model,
            extractor_prompt_version=extractor.prompt_version,
            resolver_version=RESOLVER_VERSION,
            memory_builder_version=MEMORY_BUILDER_VERSION,
        )

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)

    def digest(self) -> str:
        """Stable SHA-256 over the canonical JSON form of the fingerprint."""
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
