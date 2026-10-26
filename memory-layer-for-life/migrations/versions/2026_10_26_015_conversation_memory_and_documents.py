"""Conversation memory and documents

* ``chat_threads.memory_captured_through``: the time of the last message the memory
  pipeline has seen in this chat. Chats are captured once they go quiet, as one unit
  (ADR-048). Existing chats start at their latest activity, so history captured message
  by message before this revision is never captured a second time.
* ``chat_threads.title_generated``: whether the title was written by the model from the
  conversation, after which it is never replaced.
* ``memory_events.action`` may be ``mentioned_again``: the pipeline met a memory it
  already had and gave it the new evidence instead of saving a duplicate.
* ``documents`` and ``document_chunks``: files the user uploads for the assistant to read,
  their text in ordered passages, searchable by words; deleted with their document or
  with the user (ADR-049).

Revision ID: 015
Revises: 014
Create Date: 2026-10-26 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

# revision identifiers
revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIONS_012 = (
    "'created','accepted','retracted','restored','edited','corrected','superseded',"
    "'merged','replaced','suggestion_dismissed','completed','dropped','reopened',"
    "'scheduled','reminded'"
)
_ACTIONS_015 = f"{_ACTIONS_012},'mentioned_again'"
_EXTRACTIONS = "'text_layer','docx','plain_text','vision'"
_SEARCH_DOCUMENT = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, expression)


def upgrade() -> None:
    # --- Conversation memory -----------------------------------------------------------
    op.add_column(
        "chat_threads",
        sa.Column("memory_captured_through", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_threads",
        sa.Column("title_generated", sa.Boolean(), server_default="false", nullable=False),
    )
    # Every message sent before this revision was captured on its own when it was sent.
    op.execute("UPDATE chat_threads SET memory_captured_through = updated_at")
    _replace_check("memory_events", "ck_memory_events_valid_action", f"action IN ({_ACTIONS_015})")

    # --- Documents -----------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("is_resume", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("extraction", sa.String(20), nullable=False),
        sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_documents_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "file_sha256", name=op.f("uq_documents_user_id")),
        sa.CheckConstraint(
            f"extraction IN ({_EXTRACTIONS})", name=op.f("ck_documents_valid_extraction")
        ),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_documents_non_empty_title")),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_documents_non_negative_size")),
        sa.CheckConstraint("text_chars > 0", name=op.f("ck_documents_has_text")),
    )
    op.create_index("ix_documents_user_id_updated_at", "documents", ["user_id", "updated_at"])
    # At most one resume per user.
    op.create_index(
        "uq_documents_one_resume_per_user",
        "documents",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_resume"),
    )
    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "document_chunks",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "search_document",
            TSVECTOR(),
            sa.Computed(_SEARCH_DOCUMENT, persisted=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("document_id", "ordinal", name=op.f("uq_document_chunks_document_id")),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_document_chunks_non_negative_ordinal")),
        sa.CheckConstraint(
            "length(content) > 0", name=op.f("ck_document_chunks_non_empty_content")
        ),
    )
    op.create_index(
        "ix_document_chunks_search_document",
        "document_chunks",
        ["search_document"],
        postgresql_using="gin",
    )
    op.execute("ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.execute("DELETE FROM memory_events WHERE action = 'mentioned_again'")
    _replace_check("memory_events", "ck_memory_events_valid_action", f"action IN ({_ACTIONS_012})")
    op.drop_column("chat_threads", "title_generated")
    op.drop_column("chat_threads", "memory_captured_through")
