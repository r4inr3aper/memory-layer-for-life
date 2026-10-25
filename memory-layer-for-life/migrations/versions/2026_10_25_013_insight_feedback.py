"""Insight feedback

* ``insight_feedback``: whether a user found an insight useful, one row per user and
  insight key, deleted with the user (ADR-046).

Revision ID: 013
Revises: 012
Create Date: 2026-10-25 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "'money','people.top','people.quiet','follow_through','goal.quiet','theme'"


def upgrade() -> None:
    op.create_table(
        "insight_feedback",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("insight_key", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insight_feedback")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_insight_feedback_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "insight_key", name=op.f("uq_insight_feedback_user_id")),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name=op.f("ck_insight_feedback_valid_kind")),
        sa.CheckConstraint(
            "length(insight_key) > 0", name=op.f("ck_insight_feedback_non_empty_insight_key")
        ),
    )
    # Revision 005: every table denies everyone but its owner.
    op.execute("ALTER TABLE insight_feedback ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("insight_feedback")
