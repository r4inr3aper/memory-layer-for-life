"""Life state, reminders, the daily brief, and message search

* ``memories``: ``due_on``, ``remind_at``, ``closed_at`` and ``close_reason`` (done or
  dropped). Open items already holding a resolved date get it as ``due_on``.
  ``created_by`` may be ``assistant`` (a reminder Cooper created on request).
* ``memory_events``: the actions ``completed``, ``dropped``, ``reopened``, ``scheduled``,
  and ``reminded``.
* ``app_users``: ``timezone``, the daily brief (``brief_enabled``, ``brief_time``,
  ``last_brief_on``), ``reminders_enabled``, and quiet hours.
* ``chat_messages.search_document``: a generated ``tsvector`` with a GIN index, for
  searching one's own chats (ADR-045).

Revision ID: 012
Revises: 011
Create Date: 2026-10-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

# revision identifiers
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIONS_011 = (
    "'created','accepted','retracted','restored','edited','corrected','superseded',"
    "'merged','replaced','suggestion_dismissed'"
)
_ACTIONS_012 = f"{_ACTIONS_011},'completed','dropped','reopened','scheduled','reminded'"
_LIFE_TYPES = "'task','commitment','open_loop','plan','intention','goal','project'"
_SEARCH_DOCUMENT = (
    "setweight(to_tsvector('english'::regconfig, content), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, content), 'B')"
)


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, expression)


def upgrade() -> None:
    # --- Life state on memories -----------------------------------------------------------
    op.add_column("memories", sa.Column("due_on", sa.Date(), nullable=True))
    op.add_column("memories", sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memories", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memories", sa.Column("close_reason", sa.String(10), nullable=True))
    op.create_check_constraint(
        op.f("ck_memories_valid_close_reason"),
        "memories",
        "close_reason IS NULL OR close_reason IN ('done','dropped')",
    )
    op.create_check_constraint(
        op.f("ck_memories_closed_has_reason"),
        "memories",
        "(closed_at IS NULL) = (close_reason IS NULL)",
    )
    _replace_check(
        "memories", "ck_memories_valid_created_by", "created_by IN ('pipeline','user','assistant')"
    )
    op.create_index("ix_memories_owner_id_due_on", "memories", ["owner_id", "due_on"])
    op.create_index(
        "ix_memories_remind_at",
        "memories",
        ["remind_at"],
        postgresql_where=sa.text("remind_at IS NOT NULL"),
    )
    op.execute(
        "UPDATE memories SET due_on = (metadata->'temporal'->>'resolved_date')::date "
        f"WHERE memory_type IN ({_LIFE_TYPES}) "
        "AND metadata->'temporal'->>'resolved_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"
    )
    _replace_check("memory_events", "ck_memory_events_valid_action", f"action IN ({_ACTIONS_012})")

    # --- Preferences ------------------------------------------------------------------------
    op.add_column("app_users", sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column(
        "app_users",
        sa.Column("brief_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "app_users",
        sa.Column("brief_time", sa.Time(timezone=False), server_default="08:00", nullable=False),
    )
    op.add_column("app_users", sa.Column("last_brief_on", sa.Date(), nullable=True))
    op.add_column(
        "app_users",
        sa.Column("reminders_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "app_users", sa.Column("quiet_hours_start", sa.Time(timezone=False), nullable=True)
    )
    op.add_column("app_users", sa.Column("quiet_hours_end", sa.Time(timezone=False), nullable=True))
    op.create_check_constraint(
        op.f("ck_app_users_quiet_hours_complete"),
        "app_users",
        "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
    )

    # --- Searching one's chats ------------------------------------------------------------
    op.add_column(
        "chat_messages",
        sa.Column(
            "search_document",
            TSVECTOR(),
            sa.Computed(_SEARCH_DOCUMENT, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chat_messages_search_document",
        "chat_messages",
        ["search_document"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_search_document", table_name="chat_messages")
    op.drop_column("chat_messages", "search_document")

    op.drop_constraint(op.f("ck_app_users_quiet_hours_complete"), "app_users", type_="check")
    for column in (
        "quiet_hours_end",
        "quiet_hours_start",
        "reminders_enabled",
        "last_brief_on",
        "brief_time",
        "brief_enabled",
        "timezone",
    ):
        op.drop_column("app_users", column)

    op.execute(
        "DELETE FROM memory_events WHERE action IN "
        "('completed','dropped','reopened','scheduled','reminded')"
    )
    _replace_check("memory_events", "ck_memory_events_valid_action", f"action IN ({_ACTIONS_011})")
    op.execute("UPDATE memories SET created_by = 'user' WHERE created_by = 'assistant'")
    _replace_check("memories", "ck_memories_valid_created_by", "created_by IN ('pipeline','user')")
    op.drop_index("ix_memories_remind_at", table_name="memories")
    op.drop_index("ix_memories_owner_id_due_on", table_name="memories")
    op.drop_constraint(op.f("ck_memories_closed_has_reason"), "memories", type_="check")
    op.drop_constraint(op.f("ck_memories_valid_close_reason"), "memories", type_="check")
    for column in ("close_reason", "closed_at", "remind_at", "due_on"):
        op.drop_column("memories", column)
