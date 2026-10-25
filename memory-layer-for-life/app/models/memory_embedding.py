import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.vector import Vector


class MemoryEmbedding(Base, UUIDMixin, UpdateTimestampMixin):
    """Where one memory sits in one embedding space. Derived data: it can be deleted and
    rebuilt from the memory at any time, and the memory stays the source of truth.

    ``embedding_space`` names the provider, model, and dimensions that made the vector;
    vectors are only ever compared within one space. A memory has at most one embedding
    per space. ``content_sha256`` is the hash of the exact text embedded and
    ``document_version`` the builder that wrote it, so an embedding whose memory, entities,
    or document format changed is recognized as stale and replaced, never trusted.
    Deleted with its memory.
    """

    __tablename__ = "memory_embeddings"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    embedding_space: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False, deferred=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("memory_id", "embedding_space"),
        CheckConstraint("dimensions > 0", name="positive_dimensions"),
        CheckConstraint("vector_dims(embedding) = dimensions", name="dimensions_match"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="valid_content_sha256"),
        CheckConstraint("length(embedding_space) > 0", name="non_empty_embedding_space"),
        Index("ix_memory_embeddings_embedding_space", "embedding_space"),
    )
