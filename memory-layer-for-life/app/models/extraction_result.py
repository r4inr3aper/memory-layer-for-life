import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import ExtractionStatus

if TYPE_CHECKING:
    from app.models.entity_mention import EntityMention
    from app.models.memory_source import MemorySource
    from app.models.processing_run import ProcessingRun


class ExtractionResult(Base, UUIDMixin, TimestampMixin):
    """Validated, versioned output of the extraction stage. One per processing run.

    ``payload`` always conforms to the contract named by ``schema_version``: output that
    fails validation is never stored. ``metadata`` holds operational facts such as token
    usage, never provider reasoning or raw responses.
    """

    __tablename__ = "extraction_results"

    processing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ExtractionStatus.PENDING.value,
        server_default=ExtractionStatus.PENDING.value,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        CheckConstraint(enum_check("status", ExtractionStatus), name="valid_extraction_status"),
        Index("ix_extraction_results_processing_run_id", "processing_run_id"),
        Index("ix_extraction_results_versions", "schema_version", "extractor_version"),
    )

    processing_run: Mapped["ProcessingRun"] = relationship(
        "ProcessingRun", back_populates="extraction_result"
    )
    entity_mentions: Mapped[list["EntityMention"]] = relationship(
        "EntityMention", back_populates="extraction_result"
    )
    memory_sources: Mapped[list["MemorySource"]] = relationship(
        "MemorySource", back_populates="extraction_result"
    )
