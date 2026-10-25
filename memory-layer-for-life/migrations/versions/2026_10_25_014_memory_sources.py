"""New memory sources: chat imports, files, and connected apps

* ``chat_imports``: WhatsApp exports brought in by a user, from upload to pipeline.
* ``synced_items``: items of a connected app (calendar events) and the memory each became.
* ``tool_connections``: ``memory_sync_enabled``, ``last_synced_at``, ``sync_error``.
* ``memories.created_by`` may be ``app``.
* ``llm_calls``: the operation ``transcription`` and the origin ``capture`` (reading a
  photo or PDF the user gave to remember). ADR-047.

Revision ID: 014
Revises: 013
Create Date: 2026-10-25 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPERATIONS_009 = (
    "'extraction','judge','connection_check','chat','scheduled_task','embedding','rerank'"
)
_ORIGINS_009 = (
    "'pipeline','playground','evaluation','other','assistant','scheduler','indexing','retrieval'"
)


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, expression)


def upgrade() -> None:
    op.create_table(
        "chat_imports",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("participants", JSONB(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("conversation_count", sa.Integer(), nullable=False),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_name", sa.String(200), nullable=True),
        sa.Column("since", sa.Date(), nullable=True),
        sa.Column("unit_count", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_imports")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_chat_imports_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "file_sha256", name=op.f("uq_chat_imports_user_id")),
        sa.CheckConstraint(
            "status IN ('previewed','queued')", name=op.f("ck_chat_imports_valid_status")
        ),
        sa.CheckConstraint("source IN ('whatsapp')", name=op.f("ck_chat_imports_valid_source")),
    )
    op.execute("ALTER TABLE chat_imports ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "synced_items",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("external_updated", sa.String(64), nullable=True),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synced_items")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_synced_items_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name=op.f("fk_synced_items_memory_id_memories"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "user_id", "source", "external_id", name=op.f("uq_synced_items_user_id")
        ),
    )
    op.create_index("ix_synced_items_memory_id", "synced_items", ["memory_id"])
    op.execute("ALTER TABLE synced_items ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "tool_connections",
        sa.Column("memory_sync_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "tool_connections", sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("tool_connections", sa.Column("sync_error", sa.Text(), nullable=True))

    _replace_check(
        "memories",
        "ck_memories_valid_created_by",
        "created_by IN ('pipeline','user','assistant','app')",
    )
    _replace_check(
        "llm_calls",
        "ck_llm_calls_valid_operation",
        f"operation IN ({_OPERATIONS_009},'transcription')",
    )
    _replace_check(
        "llm_calls", "ck_llm_calls_valid_origin", f"origin IN ({_ORIGINS_009},'capture')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM llm_calls WHERE operation = 'transcription' OR origin = 'capture'")
    _replace_check("llm_calls", "ck_llm_calls_valid_origin", f"origin IN ({_ORIGINS_009})")
    _replace_check("llm_calls", "ck_llm_calls_valid_operation", f"operation IN ({_OPERATIONS_009})")
    op.execute("UPDATE memories SET created_by = 'user' WHERE created_by = 'app'")
    _replace_check(
        "memories",
        "ck_memories_valid_created_by",
        "created_by IN ('pipeline','user','assistant')",
    )
    op.drop_column("tool_connections", "sync_error")
    op.drop_column("tool_connections", "last_synced_at")
    op.drop_column("tool_connections", "memory_sync_enabled")
    op.drop_table("synced_items")
    op.drop_table("chat_imports")
