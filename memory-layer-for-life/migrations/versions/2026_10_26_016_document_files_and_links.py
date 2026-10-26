"""Document files and saved links

* ``documents.has_file`` and ``document_files``: the original file of a document, kept so
  the assistant can attach it to an email, such as a resume to a job application
  (ADR-050). Documents uploaded before this revision kept only their text; uploading the
  same file again keeps it.
* ``saved_links``: links the user saves for the assistant to share for them, such as a
  resume on Google Drive; at most one is the resume. Deleted with the user.

Revision ID: 016
Revises: 015
Create Date: 2026-10-26 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINK_KINDS = "'resume','portfolio','linkedin','github','website','other'"


def upgrade() -> None:
    # --- Document files ------------------------------------------------------------------
    op.add_column(
        "documents",
        sa.Column("has_file", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "document_files",
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_document_files")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_files_document_id_documents"),
            ondelete="CASCADE",
        ),
    )
    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE document_files ENABLE ROW LEVEL SECURITY")

    # --- Saved links ---------------------------------------------------------------------
    op.create_table(
        "saved_links",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_links")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_saved_links_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "url", name=op.f("uq_saved_links_user_id")),
        sa.CheckConstraint(f"kind IN ({_LINK_KINDS})", name=op.f("ck_saved_links_valid_kind")),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_saved_links_non_empty_title")),
        sa.CheckConstraint("length(url) > 0", name=op.f("ck_saved_links_non_empty_url")),
    )
    op.create_index("ix_saved_links_user_id_updated_at", "saved_links", ["user_id", "updated_at"])
    # At most one resume link per user.
    op.create_index(
        "uq_saved_links_one_resume_per_user",
        "saved_links",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'resume'"),
    )
    op.execute("ALTER TABLE saved_links ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("saved_links")
    op.drop_table("document_files")
    op.drop_column("documents", "has_file")
