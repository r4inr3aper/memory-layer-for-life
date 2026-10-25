"""Memories of app users

Chats become memories, so the memory store now holds several people's data:

* ``raw_messages.owner_id``, ``entities.owner_id``, ``memories.owner_id``: the app user
  the data came from. Empty for the operator's own store (the console and imports), so
  every existing row keeps its meaning. Entity resolution only matches within one owner,
  and the unauthenticated console routes show only the operator's data.
* ``app_users.memory_capture_enabled``: whether a user's chat messages become memories.

The keys restrict deletion: deleting an account first deletes the user's memory data in
dependency order (``AccountService``), as derived records restrict deleting their sources.

Revision ID: 008
Revises: 007
Create Date: 2026-10-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNED = ("raw_messages", "entities", "memories")


def upgrade() -> None:
    for table in _OWNED:
        # Adding a nullable column rewrites no rows, so the raw_messages update trigger
        # (evidence is immutable) is not involved.
        op.add_column(table, sa.Column("owner_id", UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_owner_id_app_users",
            table,
            "app_users",
            ["owner_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_raw_messages_owner_id", "raw_messages", ["owner_id"])
    op.create_index("ix_entities_owner_id", "entities", ["owner_id"])
    op.create_index("ix_memories_owner_id_created_at", "memories", ["owner_id", "created_at"])

    op.add_column(
        "app_users",
        sa.Column("memory_capture_enabled", sa.Boolean, nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("app_users", "memory_capture_enabled")
    op.drop_index("ix_memories_owner_id_created_at", table_name="memories")
    op.drop_index("ix_entities_owner_id", table_name="entities")
    op.drop_index("ix_raw_messages_owner_id", table_name="raw_messages")
    for table in reversed(_OWNED):
        op.drop_constraint(f"fk_{table}_owner_id_app_users", table, type_="foreignkey")
        op.drop_column(table, "owner_id")
