"""Memory management

* ``memory_events``: the change history of each memory (accepted, edited, corrected,
  merged, ...), deleted with its memory.
* ``memories.created_by``: ``pipeline`` or ``user``. Existing memories were all made by
  the pipeline.
* ``memories``: a trigram index on ``normalized_content``, to find memories that say
  nearly the same thing.
* ``memory_sources.extraction_result_id`` may be empty: the user tied the message to the
  memory (a memory saved from a message the pipeline held back). A partial unique index
  keeps those unique per memory and message.
* ``processing_run_events``: the event ``reviewed``, for a held-back run its owner saved
  a memory from or dismissed.
* Embeddings of sensitive memories are deleted: sensitive memories are never sent to a
  model provider (ADR-044).

Revision ID: 011
Revises: 010
Create Date: 2026-10-24 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES_002 = (
    "'queued','claimed','extraction_stored','extraction_reused','retry_scheduled',"
    "'succeeded','needs_review','failed','requeued','lease_expired'"
)
_EVENT_TYPES_011 = f"{_EVENT_TYPES_002},'reviewed'"
_ACTIONS = (
    "'created','accepted','retracted','restored','edited','corrected','superseded',"
    "'merged','replaced','suggestion_dismissed'"
)


def _replace_event_types(values: str) -> None:
    name = op.f("ck_processing_run_events_valid_event_type")
    op.drop_constraint(name, "processing_run_events", type_="check")
    op.create_check_constraint(name, "processing_run_events", f"event_type IN ({values})")


def upgrade() -> None:
    op.create_table(
        "memory_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("details", JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_events")),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name=op.f("fk_memory_events_memory_id_memories"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"action IN ({_ACTIONS})", name=op.f("ck_memory_events_valid_action")),
    )
    op.create_index("ix_memory_events_memory_created", "memory_events", ["memory_id", "created_at"])
    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE memory_events ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "memories",
        sa.Column("created_by", sa.String(20), server_default="pipeline", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_memories_valid_created_by"), "memories", "created_by IN ('pipeline','user')"
    )
    op.create_index(
        "ix_memories_normalized_content_trgm",
        "memories",
        ["normalized_content"],
        postgresql_using="gin",
        postgresql_ops={"normalized_content": "gin_trgm_ops"},
    )

    op.alter_column("memory_sources", "extraction_result_id", nullable=True)
    op.create_index(
        "uq_memory_sources_memory_message_by_user",
        "memory_sources",
        ["memory_id", "raw_message_id"],
        unique=True,
        postgresql_where=sa.text("extraction_result_id IS NULL"),
    )

    _replace_event_types(_EVENT_TYPES_011)

    op.execute(
        "DELETE FROM memory_embeddings WHERE memory_id IN "
        "(SELECT id FROM memories WHERE metadata->>'sensitivity' = 'sensitive')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM processing_run_events WHERE event_type = 'reviewed'")
    _replace_event_types(_EVENT_TYPES_002)

    # Sources the user linked have no extraction result to fall back on.
    op.execute("DELETE FROM memory_sources WHERE extraction_result_id IS NULL")
    op.drop_index("uq_memory_sources_memory_message_by_user", table_name="memory_sources")
    op.alter_column("memory_sources", "extraction_result_id", nullable=False)

    op.drop_index("ix_memories_normalized_content_trgm", table_name="memories")
    op.drop_constraint(op.f("ck_memories_valid_created_by"), "memories", type_="check")
    op.drop_column("memories", "created_by")

    op.drop_table("memory_events")
    # Embeddings of sensitive memories are rebuilt by the indexer once it no longer skips
    # them.
