"""Phase 1 pipeline schema

Adds what the ingestion pipeline needs and repairs defects of revision 001:

* Processing units of several messages (``processing_run_messages``).
* An append-only audit log of run attempts (``processing_run_events``).
* Scheduling of retries (``processing_runs.available_at``).
* Output identity for derived records, so re-materializing one extraction result can
  never create duplicates (``memories.origin_*``, ``entity_mentions.ordinal``).
* Provenance from one memory to several messages of the same extraction result.
* Immutability of raw messages, enforced by a trigger.
* CHECK constraints for every controlled vocabulary.
* Revision 001 created its CHECK constraints under doubled names such as
  ``ck_entities_ck_entities_no_self_merge``. They are renamed to the intended names.

Revision ID: 002
Revises: 001
Create Date: 2026-10-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, name created by revision 001, intended name)
_RENAMED_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("entities", "ck_entities_ck_entities_no_self_merge", "ck_entities_no_self_merge"),
    (
        "entities",
        "ck_entities_ck_entities_valid_entity_status",
        "ck_entities_valid_entity_status",
    ),
    ("entities", "ck_entities_ck_entities_valid_entity_type", "ck_entities_valid_entity_type"),
    (
        "entity_mentions",
        "ck_entity_mentions_ck_entity_mentions_valid_confidence",
        "ck_entity_mentions_valid_confidence",
    ),
    (
        "entity_mentions",
        "ck_entity_mentions_ck_entity_mentions_valid_offsets",
        "ck_entity_mentions_valid_offsets",
    ),
    (
        "extraction_results",
        "ck_extraction_results_ck_extraction_results_valid_extra_c485",
        "ck_extraction_results_valid_extraction_status",
    ),
    ("memories", "ck_memories_ck_memories_no_self_supersede", "ck_memories_no_self_supersede"),
    (
        "memories",
        "ck_memories_ck_memories_valid_memory_confidence",
        "ck_memories_valid_memory_confidence",
    ),
    (
        "memory_relations",
        "ck_memory_relations_ck_memory_relations_no_self_relation",
        "ck_memory_relations_no_self_relation",
    ),
    (
        "memory_relations",
        "ck_memory_relations_ck_memory_relations_valid_relation__17c8",
        "ck_memory_relations_valid_relation_confidence",
    ),
    (
        "processing_runs",
        "ck_processing_runs_ck_processing_runs_positive_attempt_number",
        "ck_processing_runs_positive_attempt_number",
    ),
    (
        "processing_runs",
        "ck_processing_runs_ck_processing_runs_valid_status",
        "ck_processing_runs_valid_status",
    ),
)

_ENTITY_TYPES = "'person','organization','project','concept','place','event','technology','topic'"
_MEMORY_TYPES = (
    "'semantic_fact','episodic_event','preference','intention','task','commitment','goal',"
    "'project','decision','idea','open_loop','plan','note','reflection','resource',"
    "'financial_note'"
)
_RUN_EVENT_TYPES = (
    "'queued','claimed','extraction_stored','extraction_reused','retry_scheduled',"
    "'succeeded','needs_review','failed','requeued','lease_expired'"
)
_PIPELINE_STAGES = "'normalize','extract','resolve','construct','persist'"


def upgrade() -> None:
    # --- Repair the CHECK constraint names created by revision 001 -------------------
    for table, old_name, new_name in _RENAMED_CHECKS:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{old_name}" TO "{new_name}"')

    # --- raw_messages: evidence integrity and immutability ---------------------------
    op.create_check_constraint(
        op.f("ck_raw_messages_non_empty_content"), "raw_messages", "length(content) > 0"
    )
    op.create_check_constraint(
        op.f("ck_raw_messages_valid_content_sha256"),
        "raw_messages",
        "content_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.execute(
        """
        CREATE FUNCTION raw_messages_reject_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'raw_messages rows are immutable source evidence'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_messages_immutable
        BEFORE UPDATE ON raw_messages
        FOR EACH ROW EXECUTE FUNCTION raw_messages_reject_update()
        """
    )

    # --- processing_runs: retry scheduling --------------------------------------------
    op.add_column(
        "processing_runs",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_processing_runs_status_available_at", "processing_runs", ["status", "available_at"]
    )

    # --- processing_run_messages: the ordered unit of a run ---------------------------
    op.create_table(
        "processing_run_messages",
        sa.Column("processing_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("raw_message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "processing_run_id", "raw_message_id", name=op.f("pk_processing_run_messages")
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_processing_run_messages_processing_run_id_processing_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["raw_messages.id"],
            name="fk_processing_run_messages_raw_message_id_raw_messages",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "processing_run_id", "position", name="uq_processing_run_messages_run_position"
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_processing_run_messages_non_negative_position")
        ),
    )
    op.create_index(
        "ix_processing_run_messages_raw_message_id", "processing_run_messages", ["raw_message_id"]
    )
    # Runs created before this revision processed exactly their anchor message.
    op.execute(
        """
        INSERT INTO processing_run_messages
            (processing_run_id, raw_message_id, position, created_at)
        SELECT id, raw_message_id, 0, created_at FROM processing_runs
        """
    )

    # --- processing_run_events: append-only audit log ---------------------------------
    op.create_table(
        "processing_run_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("processing_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("stage", sa.String(20), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_run_events")),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_processing_run_events_processing_run_id_processing_runs",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "attempt_number > 0", name=op.f("ck_processing_run_events_positive_attempt_number")
        ),
        sa.CheckConstraint(
            f"event_type IN ({_RUN_EVENT_TYPES})",
            name=op.f("ck_processing_run_events_valid_event_type"),
        ),
        sa.CheckConstraint(
            f"stage IS NULL OR stage IN ({_PIPELINE_STAGES})",
            name=op.f("ck_processing_run_events_valid_stage"),
        ),
    )
    op.create_index(
        "ix_processing_run_events_run_created",
        "processing_run_events",
        ["processing_run_id", "created_at"],
    )

    # --- extraction_results: operational metadata -------------------------------------
    op.add_column(
        "extraction_results",
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    # --- entities ----------------------------------------------------------------------
    op.create_check_constraint(
        op.f("ck_entities_merged_has_target"),
        "entities",
        "(status = 'merged') = (merged_into_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_entities_non_empty_normalized_name"), "entities", "length(normalized_name) > 0"
    )

    # --- entity_mentions: output identity and resolution consistency -------------------
    op.add_column("entity_mentions", sa.Column("ordinal", sa.Integer, nullable=True))
    op.execute(
        """
        UPDATE entity_mentions AS m
        SET ordinal = numbered.position
        FROM (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY extraction_result_id ORDER BY created_at, id
                   ) - 1 AS position
            FROM entity_mentions
        ) AS numbered
        WHERE m.id = numbered.id
        """
    )
    op.alter_column("entity_mentions", "ordinal", nullable=False)
    op.drop_constraint("uq_entity_mentions_extraction_mention", "entity_mentions", type_="unique")
    op.create_unique_constraint(
        "uq_entity_mentions_extraction_ordinal",
        "entity_mentions",
        ["extraction_result_id", "ordinal"],
    )
    op.create_check_constraint(
        op.f("ck_entity_mentions_non_negative_ordinal"), "entity_mentions", "ordinal >= 0"
    )
    op.create_check_constraint(
        op.f("ck_entity_mentions_valid_entity_type"),
        "entity_mentions",
        f"entity_type IN ({_ENTITY_TYPES})",
    )
    op.create_check_constraint(
        op.f("ck_entity_mentions_valid_resolution_status"),
        "entity_mentions",
        "resolution_status IN ('unresolved','resolved','ambiguous','rejected')",
    )
    op.create_check_constraint(
        op.f("ck_entity_mentions_resolved_has_entity"),
        "entity_mentions",
        "(resolution_status = 'resolved') = (resolved_entity_id IS NOT NULL)",
    )

    # --- memories: controlled vocabularies and output identity ------------------------
    op.add_column(
        "memories",
        sa.Column("origin_extraction_result_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column("memories", sa.Column("origin_ordinal", sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_memories_origin_extraction_result_id_extraction_results",
        "memories",
        "extraction_results",
        ["origin_extraction_result_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_memories_origin", "memories", ["origin_extraction_result_id", "origin_ordinal"]
    )
    op.create_check_constraint(
        op.f("ck_memories_valid_memory_type"), "memories", f"memory_type IN ({_MEMORY_TYPES})"
    )
    op.create_check_constraint(
        op.f("ck_memories_valid_memory_status"),
        "memories",
        "status IN ('proposed','active','superseded','retracted')",
    )
    op.create_check_constraint(
        op.f("ck_memories_non_empty_content"), "memories", "length(content) > 0"
    )
    op.create_check_constraint(
        op.f("ck_memories_valid_period_order"),
        "memories",
        "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
    )
    op.create_check_constraint(
        op.f("ck_memories_origin_pair_complete"),
        "memories",
        "(origin_extraction_result_id IS NULL) = (origin_ordinal IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_memories_non_negative_origin_ordinal"),
        "memories",
        "origin_ordinal IS NULL OR origin_ordinal >= 0",
    )

    # --- memory_sources: one memory may rest on several messages ----------------------
    op.drop_constraint("uq_memory_sources_memory_extraction", "memory_sources", type_="unique")
    op.create_unique_constraint(
        "uq_memory_sources_memory_message_extraction",
        "memory_sources",
        ["memory_id", "raw_message_id", "extraction_result_id"],
    )
    op.create_check_constraint(
        op.f("ck_memory_sources_valid_source_role"),
        "memory_sources",
        "source_role IN ('supporting','contradicting','contextual')",
    )

    # --- memory_entities and memory_relations: controlled vocabularies ----------------
    op.create_check_constraint(
        op.f("ck_memory_entities_valid_relationship_type"),
        "memory_entities",
        "relationship_type IN ('mentions')",
    )
    op.create_check_constraint(
        op.f("ck_memory_relations_valid_relation_type"),
        "memory_relations",
        "relation_type IN "
        "('depends_on','contradicts','supersedes','supports','elaborates','related_to')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_memory_relations_valid_relation_type"), "memory_relations", type_="check"
    )
    op.drop_constraint(
        op.f("ck_memory_entities_valid_relationship_type"), "memory_entities", type_="check"
    )

    op.drop_constraint(op.f("ck_memory_sources_valid_source_role"), "memory_sources", type_="check")
    op.drop_constraint(
        "uq_memory_sources_memory_message_extraction", "memory_sources", type_="unique"
    )
    # Fails if a memory has several sources from one extraction result: revision 001
    # cannot represent that data.
    op.create_unique_constraint(
        "uq_memory_sources_memory_extraction",
        "memory_sources",
        ["memory_id", "extraction_result_id"],
    )

    for name in (
        "ck_memories_non_negative_origin_ordinal",
        "ck_memories_origin_pair_complete",
        "ck_memories_valid_period_order",
        "ck_memories_non_empty_content",
        "ck_memories_valid_memory_status",
        "ck_memories_valid_memory_type",
    ):
        op.drop_constraint(op.f(name), "memories", type_="check")
    op.drop_constraint("uq_memories_origin", "memories", type_="unique")
    op.drop_constraint(
        "fk_memories_origin_extraction_result_id_extraction_results",
        "memories",
        type_="foreignkey",
    )
    op.drop_column("memories", "origin_ordinal")
    op.drop_column("memories", "origin_extraction_result_id")

    for name in (
        "ck_entity_mentions_resolved_has_entity",
        "ck_entity_mentions_valid_resolution_status",
        "ck_entity_mentions_valid_entity_type",
        "ck_entity_mentions_non_negative_ordinal",
    ):
        op.drop_constraint(op.f(name), "entity_mentions", type_="check")
    op.drop_constraint("uq_entity_mentions_extraction_ordinal", "entity_mentions", type_="unique")
    op.create_unique_constraint(
        "uq_entity_mentions_extraction_mention",
        "entity_mentions",
        ["extraction_result_id", "mention_text", "start_offset"],
    )
    op.drop_column("entity_mentions", "ordinal")

    op.drop_constraint(op.f("ck_entities_non_empty_normalized_name"), "entities", type_="check")
    op.drop_constraint(op.f("ck_entities_merged_has_target"), "entities", type_="check")

    op.drop_column("extraction_results", "metadata")

    op.drop_index("ix_processing_run_events_run_created", table_name="processing_run_events")
    op.drop_table("processing_run_events")

    op.drop_index("ix_processing_run_messages_raw_message_id", table_name="processing_run_messages")
    op.drop_table("processing_run_messages")

    op.drop_index("ix_processing_runs_status_available_at", table_name="processing_runs")
    op.drop_column("processing_runs", "available_at")

    op.execute("DROP TRIGGER trg_raw_messages_immutable ON raw_messages")
    op.execute("DROP FUNCTION raw_messages_reject_update()")
    op.drop_constraint(op.f("ck_raw_messages_valid_content_sha256"), "raw_messages", type_="check")
    op.drop_constraint(op.f("ck_raw_messages_non_empty_content"), "raw_messages", type_="check")

    for table, old_name, new_name in _RENAMED_CHECKS:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{new_name}" TO "{old_name}"')
