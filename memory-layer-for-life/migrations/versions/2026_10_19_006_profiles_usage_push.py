"""Assistant profiles, usage attribution, reply leases, push tokens, and feedback

* ``app_users`` keeps how the user personalized their assistant and whether they want
  push notifications.
* ``llm_calls.user_id`` attributes each model call to the app user it was made for, so
  usage can be counted and limited per user. Set to NULL when the user is deleted.
* ``chat_threads.turn_lease_until`` reserves a thread while a reply runs, across every
  process serving the API.
* ``push_tokens``: Expo push tokens of the user's devices.
* ``feedback``: messages sent from Help & Feedback.

Both new tables get row level security, like every other (revision 005).

Revision ID: 006
Revises: 005
Create Date: 2026-10-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- app_users -----------------------------------------------------------------------
    op.add_column("app_users", sa.Column("assistant_name", sa.String(40), nullable=True))
    op.add_column("app_users", sa.Column("assistant_subtitle", sa.String(60), nullable=True))
    op.add_column("app_users", sa.Column("assistant_icon", sa.String(40), nullable=True))
    op.add_column("app_users", sa.Column("assistant_color", sa.String(20), nullable=True))
    op.add_column(
        "app_users",
        sa.Column("notifications_enabled", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_check_constraint(
        op.f("ck_app_users_assistant_name_not_blank"),
        "app_users",
        "assistant_name IS NULL OR length(trim(assistant_name)) > 0",
    )

    # --- llm_calls -----------------------------------------------------------------------
    op.add_column("llm_calls", sa.Column("user_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_llm_calls_user_id_app_users",
        "llm_calls",
        "app_users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_llm_calls_user_id_started_at", "llm_calls", ["user_id", "started_at"])

    # --- chat_threads --------------------------------------------------------------------
    op.add_column(
        "chat_threads", sa.Column("turn_lease_until", sa.DateTime(timezone=True), nullable=True)
    )

    # --- push_tokens ---------------------------------------------------------------------
    op.create_table(
        "push_tokens",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_tokens")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_push_tokens_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token", name=op.f("uq_push_tokens_token")),
        sa.CheckConstraint(
            "platform IN ('ios','android','web')", name=op.f("ck_push_tokens_valid_platform")
        ),
        sa.CheckConstraint("length(token) > 0", name=op.f("ck_push_tokens_non_empty_token")),
    )
    op.create_index("ix_push_tokens_user_id", "push_tokens", ["user_id"])

    # --- feedback ------------------------------------------------------------------------
    op.create_table(
        "feedback",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("platform", sa.String(10), nullable=True),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_feedback_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("length(trim(message)) > 0", name=op.f("ck_feedback_non_empty_message")),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])

    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE push_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE feedback ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("push_tokens")
    op.drop_column("chat_threads", "turn_lease_until")
    op.drop_index("ix_llm_calls_user_id_started_at", table_name="llm_calls")
    op.drop_constraint("fk_llm_calls_user_id_app_users", "llm_calls", type_="foreignkey")
    op.drop_column("llm_calls", "user_id")
    op.drop_constraint(op.f("ck_app_users_assistant_name_not_blank"), "app_users", type_="check")
    for column in (
        "notifications_enabled",
        "assistant_color",
        "assistant_icon",
        "assistant_subtitle",
        "assistant_name",
    ):
        op.drop_column("app_users", column)
