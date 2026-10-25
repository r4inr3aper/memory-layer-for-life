import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import EntityType, MentionResolutionStatus

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.extraction_result import ExtractionResult
    from app.models.raw_message import RawMessage


class EntityMention(Base, UUIDMixin, TimestampMixin):
    """One mention of an entity in a raw message, as found by an extraction result.

    The mention is kept as written even after it is resolved. ``ordinal`` is the
    mention's index within its extraction result and is the output identity that makes
    re-materializing the same result impossible to duplicate.
    """

    __tablename__ = "entity_mentions"

    raw_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_messages.id", ondelete="RESTRICT"), nullable=False
    )
    extraction_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mention_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    normalized_mention: Mapped[str] = mapped_column(String(1000), nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=MentionResolutionStatus.UNRESOLVED.value,
        server_default=MentionResolutionStatus.UNRESOLVED.value,
    )
    resolved_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2, asdecimal=False), nullable=True)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="non_negative_ordinal"),
        CheckConstraint(enum_check("entity_type", EntityType), name="valid_entity_type"),
        CheckConstraint(
            enum_check("resolution_status", MentionResolutionStatus),
            name="valid_resolution_status",
        ),
        CheckConstraint(
            "(resolution_status = 'resolved') = (resolved_entity_id IS NOT NULL)",
            name="resolved_has_entity",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="valid_confidence"
        ),
        CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR (start_offset IS NOT NULL AND end_offset IS NOT NULL AND start_offset >= 0 AND end_offset >= start_offset)",  # noqa: E501
            name="valid_offsets",
        ),
        UniqueConstraint(
            "extraction_result_id", "ordinal", name="uq_entity_mentions_extraction_ordinal"
        ),
        Index("ix_entity_mentions_extraction_result_id", "extraction_result_id"),
        Index("ix_entity_mentions_raw_message_id", "raw_message_id"),
        Index("ix_entity_mentions_resolved_entity_id", "resolved_entity_id"),
        Index("ix_entity_mentions_resolution_status", "resolution_status"),
    )

    raw_message: Mapped["RawMessage"] = relationship("RawMessage", back_populates="entity_mentions")
    extraction_result: Mapped["ExtractionResult"] = relationship(
        "ExtractionResult", back_populates="entity_mentions"
    )
    resolved_entity: Mapped["Entity | None"] = relationship("Entity", back_populates="mentions")
