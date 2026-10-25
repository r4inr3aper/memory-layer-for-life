"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Table: raw_messages
    op.create_table(
        "raw_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_message_id", sa.String(255), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source", "source_message_id", name="uq_raw_messages_source_source_message_id"
        ),
    )
    op.create_index("ix_raw_messages_source", "raw_messages", ["source"])
    op.create_index("ix_raw_messages_ingested_at", "raw_messages", ["ingested_at"])
    op.create_index("ix_raw_messages_source_created_at", "raw_messages", ["source_created_at"])

    # Table: processing_runs
    op.create_table(
        "processing_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("raw_message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            name="fk_processing_runs_raw_message_id_raw_messages",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_processing_runs_idempotency_key"),
        sa.CheckConstraint("attempt_number > 0", name="ck_processing_runs_positive_attempt_number"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','needs_review')",
            name="ck_processing_runs_valid_status",
        ),
    )
    op.create_index("ix_processing_runs_raw_message_id", "processing_runs", ["raw_message_id"])
    op.create_index("ix_processing_runs_status", "processing_runs", ["status"])
    op.create_index("ix_processing_runs_created_at", "processing_runs", ["created_at"])

    # Table: extraction_results
    op.create_table(
        "extraction_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("processing_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_extraction_results_processing_run_id_processing_runs",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("processing_run_id", name="uq_extraction_results_processing_run_id"),
        sa.CheckConstraint(
            "status IN ('pending','succeeded','failed','needs_review')",
            name="ck_extraction_results_valid_extraction_status",
        ),
    )
    op.create_index(
        "ix_extraction_results_processing_run_id", "extraction_results", ["processing_run_id"]
    )
    op.create_index(
        "ix_extraction_results_versions",
        "extraction_results",
        ["schema_version", "extractor_version"],
    )

    # Table: entities
    op.create_table(
        "entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("canonical_name", sa.String(500), nullable=False),
        sa.Column("normalized_name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("merged_into_id", UUID(as_uuid=True), nullable=True),
        sa.Column("attributes", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["entities.id"],
            name="fk_entities_merged_into_id_entities",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("merged_into_id != id", name="ck_entities_no_self_merge"),
        sa.CheckConstraint(
            "entity_type IN ('person','organization','project','concept','place','event','technology','topic')",
            name="ck_entities_valid_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','merged','archived')", name="ck_entities_valid_entity_status"
        ),
    )
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index(
        "ix_entities_type_normalized_name", "entities", ["entity_type", "normalized_name"]
    )

    # Table: memories
    op.create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("memory_type", sa.String(30), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("normalized_content", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_memory_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supersedes_memory_id"],
            ["memories.id"],
            name="fk_memories_supersedes_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("supersedes_memory_id != id", name="ck_memories_no_self_supersede"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memories_valid_memory_confidence",
        ),
    )
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
    op.create_index("ix_memories_status", "memories", ["status"])

    # Table: entity_mentions
    op.create_table(
        "entity_mentions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("raw_message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_result_id", UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("mention_text", sa.String(1000), nullable=False),
        sa.Column("normalized_mention", sa.String(1000), nullable=False),
        sa.Column("start_offset", sa.Integer, nullable=True),
        sa.Column("end_offset", sa.Integer, nullable=True),
        sa.Column("resolution_status", sa.String(20), nullable=False, server_default="unresolved"),
        sa.Column("resolved_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            name="fk_entity_mentions_raw_message_id_raw_messages",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_result_id"],
            ["extraction_results.id"],
            name="fk_entity_mentions_extraction_result_id_extraction_results",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_entity_id"],
            ["entities.id"],
            name="fk_entity_mentions_resolved_entity_id_entities",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "extraction_result_id",
            "mention_text",
            "start_offset",
            name="uq_entity_mentions_extraction_mention",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_entity_mentions_valid_confidence",
        ),
        sa.CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR (start_offset IS NOT NULL AND end_offset IS NOT NULL AND start_offset >= 0 AND end_offset >= start_offset)",
            name="ck_entity_mentions_valid_offsets",
        ),
    )
    op.create_index(
        "ix_entity_mentions_extraction_result_id", "entity_mentions", ["extraction_result_id"]
    )
    op.create_index("ix_entity_mentions_raw_message_id", "entity_mentions", ["raw_message_id"])
    op.create_index(
        "ix_entity_mentions_resolved_entity_id", "entity_mentions", ["resolved_entity_id"]
    )
    op.create_index(
        "ix_entity_mentions_resolution_status", "entity_mentions", ["resolution_status"]
    )

    # Table: memory_sources
    op.create_table(
        "memory_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("raw_message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_result_id", UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_text", sa.Text, nullable=True),
        sa.Column("source_role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_sources_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            name="fk_memory_sources_raw_message_id_raw_messages",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_result_id"],
            ["extraction_results.id"],
            name="fk_memory_sources_extraction_result_id_extraction_results",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "memory_id", "extraction_result_id", name="uq_memory_sources_memory_extraction"
        ),
    )
    op.create_index("ix_memory_sources_memory_id", "memory_sources", ["memory_id"])
    op.create_index("ix_memory_sources_raw_message_id", "memory_sources", ["raw_message_id"])
    op.create_index(
        "ix_memory_sources_extraction_result_id", "memory_sources", ["extraction_result_id"]
    )

    # Table: memory_entities
    op.create_table(
        "memory_entities",
        sa.Column("memory_id", UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("relationship_type", sa.String(50), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_entities_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name="fk_memory_entities_entity_id_entities",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_memory_entities_entity_id", "memory_entities", ["entity_id"])

    # Table: memory_relations
    op.create_table(
        "memory_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_source_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_target_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relation_type",
            name="uq_memory_relations_source_target_type",
        ),
        sa.CheckConstraint(
            "source_memory_id != target_memory_id", name="ck_memory_relations_no_self_relation"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memory_relations_valid_relation_confidence",
        ),
    )
    op.create_index(
        "ix_memory_relations_source_memory_id", "memory_relations", ["source_memory_id"]
    )
    op.create_index(
        "ix_memory_relations_target_memory_id", "memory_relations", ["target_memory_id"]
    )


def downgrade() -> None:
    op.drop_table("memory_relations")
    op.drop_table("memory_entities")
    op.drop_table("memory_sources")
    op.drop_table("entity_mentions")
    op.drop_table("memories")
    op.drop_table("entities")
    op.drop_table("extraction_results")
    op.drop_table("processing_runs")
    op.drop_table("raw_messages")
