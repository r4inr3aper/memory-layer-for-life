import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import DocumentExtraction

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk


class Document(Base, UUIDMixin, UpdateTimestampMixin):
    """A file the user uploaded for the assistant to read when it is relevant, such as a
    resume (ADR-049).

    Its text is kept in ordered passages (``document_chunks``), and since ADR-050 the
    original file too (``document_files``, ``has_file``), so the assistant can attach it
    to an email. A document is reference material, not memories: nothing is extracted
    from it, so deleting it (or the user) removes everything the assistant could read or
    send of it. The same file twice is the same document (``file_sha256``). At most one
    document per user is their resume, enforced by a partial unique index.
    """

    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    is_resume: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    extraction: Mapped[str] = mapped_column(String(20), nullable=False)
    text_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Whether the original file is kept (``document_files``); false for documents uploaded
    # before revision 016, of which only the text was kept.
    has_file: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        CheckConstraint(enum_check("extraction", DocumentExtraction), name="valid_extraction"),
        CheckConstraint("length(title) > 0", name="non_empty_title"),
        CheckConstraint("size_bytes >= 0", name="non_negative_size"),
        CheckConstraint("text_chars > 0", name="has_text"),
        UniqueConstraint("user_id", "file_sha256"),
        Index("ix_documents_user_id_updated_at", "user_id", "updated_at"),
        Index(
            "uq_documents_one_resume_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("is_resume"),
        ),
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        order_by="DocumentChunk.ordinal",
        passive_deletes=True,
    )
