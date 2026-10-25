"""Daily prompt usage

* ``daily_usage``: per user and UTC day, the chat messages they sent and the scheduled
  runs started for them. The daily prompt limit is checked and counted against it.
* ``app_users.daily_prompt_limit``: an operator's override of the default limit for one
  user. Empty means the default; 0 means unlimited.

The table starts empty: usage before this revision is not counted.

Revision ID: 007
Revises: 006
Create Date: 2026-10-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_users", sa.Column("daily_prompt_limit", sa.Integer, nullable=True))
    op.create_check_constraint(
        op.f("ck_app_users_non_negative_daily_prompt_limit"),
        "app_users",
        "daily_prompt_limit IS NULL OR daily_prompt_limit >= 0",
    )

    op.create_table(
        "daily_usage",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("chat_messages", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scheduled_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_daily_usage")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_daily_usage_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "day", name=op.f("uq_daily_usage_user_id")),
        sa.CheckConstraint(
            "chat_messages >= 0 AND scheduled_runs >= 0",
            name=op.f("ck_daily_usage_non_negative_counts"),
        ),
    )

    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE daily_usage ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("daily_usage")
    op.drop_constraint(
        op.f("ck_app_users_non_negative_daily_prompt_limit"), "app_users", type_="check"
    )
    op.drop_column("app_users", "daily_prompt_limit")
