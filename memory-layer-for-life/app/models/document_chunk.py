import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import Document

# English stems weighted above exact words, as for memories and chat messages.
SEARCH_DOCUMENT_SQL = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)


class DocumentChunk(Base, UUIDMixin, TimestampMixin):
    """One passage of a document's text, in reading order. Passages are what the
    assistant's document search returns; read in order they are the whole text. Deleted
    with their document."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    # The PDF page the passage starts on, when the document has pages.
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Generated from ``content``; never written and never loaded, only searched.
    search_document: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_DOCUMENT_SQL, persisted=True), nullable=True, deferred=True
    )

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="non_negative_ordinal"),
        CheckConstraint("length(content) > 0", name="non_empty_content"),
        UniqueConstraint("document_id", "ordinal"),
        Index("ix_document_chunks_search_document", "search_document", postgresql_using="gin"),
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
