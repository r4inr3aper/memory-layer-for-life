"""Memory retrieval

* Extensions: ``vector`` (pgvector) for embeddings, ``pg_trgm`` for names written slightly
  differently. Both are trusted extensions on PostgreSQL 13 and later, and both are
  available on Neon.
* ``memories.search_document``: a generated ``tsvector`` of the memory's text (stemmed
  English, plus the text unstemmed for names and other languages), with a GIN index.
* ``entities``: a trigram index on ``normalized_name``.
* ``memory_embeddings``: one vector per memory and embedding space, derived and
  rebuildable, deleted with its memory. The vector column has no fixed dimension; a check
  constraint ties each row's vector to its space's dimensions. No approximate (HNSW)
  index yet: searches are restricted to one owner first and scanned exactly, which is
  exact and fast at that size (ADR-038).
* ``llm_calls``: the operations ``embedding`` and ``rerank`` and the origins ``indexing``
  and ``retrieval``.

Revision ID: 009
Revises: 008
Create Date: 2026-10-24 18:00:00.000000

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID

# revision identifiers
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEARCH_DOCUMENT = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)
_OPERATIONS_004 = "'extraction','judge','connection_check','chat','scheduled_task'"
_ORIGINS_004 = "'pipeline','playground','evaluation','other','assistant','scheduler'"
_OPERATIONS_009 = f"{_OPERATIONS_004},'embedding','rerank'"
_ORIGINS_009 = f"{_ORIGINS_004},'indexing','retrieval'"


class _Vector(sa.types.UserDefinedType[Any]):
    """pgvector's type, as of this revision."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector"


def _replace_llm_call_vocabularies(operations: str, origins: str) -> None:
    op.drop_constraint(op.f("ck_llm_calls_valid_operation"), "llm_calls", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_valid_operation"), "llm_calls", f"operation IN ({operations})"
    )
    op.drop_constraint(op.f("ck_llm_calls_valid_origin"), "llm_calls", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_valid_origin"), "llm_calls", f"origin IN ({origins})"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- Full-text search over memories ------------------------------------------------
    op.add_column(
        "memories",
        sa.Column(
            "search_document",
            TSVECTOR(),
            sa.Computed(_SEARCH_DOCUMENT, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_memories_search_document", "memories", ["search_document"], postgresql_using="gin"
    )

    # --- Names written slightly differently ----------------------------------------------
    op.create_index(
        "ix_entities_normalized_name_trgm",
        "entities",
        ["normalized_name"],
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )

    # --- Embeddings ----------------------------------------------------------------------
    op.create_table(
        "memory_embeddings",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_space", sa.String(100), nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column("embedding", _Vector(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("document_version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_embeddings")),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_embeddings_memory_id_memories",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "memory_id", "embedding_space", name=op.f("uq_memory_embeddings_memory_id")
        ),
        sa.CheckConstraint("dimensions > 0", name=op.f("ck_memory_embeddings_positive_dimensions")),
        sa.CheckConstraint(
            "vector_dims(embedding) = dimensions",
            name=op.f("ck_memory_embeddings_dimensions_match"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_memory_embeddings_valid_content_sha256"),
        ),
        sa.CheckConstraint(
            "length(embedding_space) > 0",
            name=op.f("ck_memory_embeddings_non_empty_embedding_space"),
        ),
    )
    op.create_index(
        "ix_memory_embeddings_embedding_space", "memory_embeddings", ["embedding_space"]
    )
    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE memory_embeddings ENABLE ROW LEVEL SECURITY")

    # --- The call log knows embedding and reranking ---------------------------------------
    _replace_llm_call_vocabularies(_OPERATIONS_009, _ORIGINS_009)


def downgrade() -> None:
    op.execute(
        "DELETE FROM llm_calls WHERE operation IN ('embedding','rerank') "
        "OR origin IN ('indexing','retrieval')"
    )
    _replace_llm_call_vocabularies(_OPERATIONS_004, _ORIGINS_004)
    op.drop_table("memory_embeddings")
    op.drop_index("ix_entities_normalized_name_trgm", table_name="entities")
    op.drop_index("ix_memories_search_document", table_name="memories")
    op.drop_column("memories", "search_document")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS vector")
