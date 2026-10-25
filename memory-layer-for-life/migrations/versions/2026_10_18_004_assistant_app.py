"""Assistant app: users, chat, scheduled tasks, and app connections

Moves the mobile app's data into this database, where it had lived in Supabase tables
that the app queried directly:

* ``app_users``: people who signed in through Supabase Auth, keyed by their Supabase id.
* ``chat_threads`` and ``chat_messages``: conversations with the assistant.
* ``scheduled_tasks`` and ``scheduled_task_runs``: tasks the assistant runs on a schedule,
  and the history of each run.
* ``tool_connections``: each user's connections to apps through Composio.

The model call log learns two operations and two origins, for the assistant's calls.

Nothing in the memory pipeline changes.

Revision ID: 004
Revises: 003
Create Date: 2026-10-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPERATIONS_003 = "'extraction','judge','connection_check'"
_ORIGINS_003 = "'pipeline','playground','evaluation','other'"
_OPERATIONS_004 = "'extraction','judge','connection_check','chat','scheduled_task'"
_ORIGINS_004 = "'pipeline','playground','evaluation','other','assistant','scheduler'"
_WEEKDAYS = "'monday','tuesday','wednesday','thursday','friday','saturday','sunday'"


def _replace_llm_call_vocabularies(operations: str, origins: str) -> None:
    # ``op.f`` marks a name as final, so the naming convention is not applied twice.
    op.drop_constraint(op.f("ck_llm_calls_valid_operation"), "llm_calls", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_valid_operation"), "llm_calls", f"operation IN ({operations})"
    )
    op.drop_constraint(op.f("ck_llm_calls_valid_origin"), "llm_calls", type_="check")
    op.create_check_constraint(
        op.f("ck_llm_calls_valid_origin"), "llm_calls", f"origin IN ({origins})"
    )


def upgrade() -> None:
    # --- app_users ---------------------------------------------------------------------
    op.create_table(
        "app_users",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_users")),
    )

    # --- chat_threads ------------------------------------------------------------------
    op.create_table(
        "chat_threads",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_threads")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_chat_threads_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('main','side')", name=op.f("ck_chat_threads_valid_kind")),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_chat_threads_non_empty_title")),
    )
    op.create_index(
        "uq_chat_threads_one_main_per_user",
        "chat_threads",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'main'"),
    )
    op.create_index("ix_chat_threads_user_id_updated_at", "chat_threads", ["user_id", "updated_at"])

    # --- chat_messages -----------------------------------------------------------------
    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_threads.id"],
            name="fk_chat_messages_thread_id_chat_threads",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant')", name=op.f("ck_chat_messages_valid_role")
        ),
        sa.CheckConstraint("length(content) > 0", name=op.f("ck_chat_messages_non_empty_content")),
    )
    op.create_index(
        "ix_chat_messages_thread_id_created_at", "chat_messages", ["thread_id", "created_at"]
    )

    # --- scheduled_tasks ---------------------------------------------------------------
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_thread_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("original_prompt", sa.Text, nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("local_time", sa.Time(timezone=False), nullable=False),
        sa.Column("weekday", sa.String(10), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("delivery", sa.String(20), nullable=False),
        sa.Column("delivery_target", sa.String(200), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(10), nullable=True),
        sa.Column("last_run_summary", sa.Text, nullable=True),
        sa.Column("last_run_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_tasks")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_scheduled_tasks_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_thread_id"],
            ["chat_threads.id"],
            name="fk_scheduled_tasks_source_thread_id_chat_threads",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "frequency IN ('daily','weekly')", name=op.f("ck_scheduled_tasks_valid_frequency")
        ),
        sa.CheckConstraint(
            f"weekday IS NULL OR weekday IN ({_WEEKDAYS})",
            name=op.f("ck_scheduled_tasks_valid_weekday"),
        ),
        sa.CheckConstraint(
            "(frequency = 'weekly') = (weekday IS NOT NULL)",
            name=op.f("ck_scheduled_tasks_weekly_has_weekday"),
        ),
        sa.CheckConstraint(
            "delivery IN ('chat','slack','email','calendar','notion','teams','discord')",
            name=op.f("ck_scheduled_tasks_valid_delivery"),
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','cancelled')",
            name=op.f("ck_scheduled_tasks_valid_status"),
        ),
        sa.CheckConstraint(
            "last_run_status IS NULL OR last_run_status IN ('succeeded','failed')",
            name=op.f("ck_scheduled_tasks_valid_last_run_status"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR next_run_at IS NOT NULL",
            name=op.f("ck_scheduled_tasks_active_has_next_run"),
        ),
        sa.CheckConstraint("length(title) > 0", name=op.f("ck_scheduled_tasks_non_empty_title")),
        sa.CheckConstraint("length(task) > 0", name=op.f("ck_scheduled_tasks_non_empty_task")),
    )
    op.create_index(
        "ix_scheduled_tasks_due",
        "scheduled_tasks",
        ["next_run_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_scheduled_tasks_user_id_created_at", "scheduled_tasks", ["user_id", "created_at"]
    )

    # --- scheduled_task_runs -----------------------------------------------------------
    op.create_table(
        "scheduled_task_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="running"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("chat_message_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_task_runs")),
        sa.ForeignKeyConstraint(
            ["scheduled_task_id"],
            ["scheduled_tasks.id"],
            name="fk_scheduled_task_runs_scheduled_task_id_scheduled_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_messages.id"],
            name="fk_scheduled_task_runs_chat_message_id_chat_messages",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "trigger IN ('schedule','manual')", name=op.f("ck_scheduled_task_runs_valid_trigger")
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name=op.f("ck_scheduled_task_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "(trigger = 'schedule') = (scheduled_for IS NOT NULL)",
            name=op.f("ck_scheduled_task_runs_scheduled_has_slot"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_scheduled_task_runs_finished_when_not_running"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL",
            name=op.f("ck_scheduled_task_runs_failed_has_error_code"),
        ),
    )
    op.create_index(
        "uq_scheduled_task_runs_slot",
        "scheduled_task_runs",
        ["scheduled_task_id", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("scheduled_for IS NOT NULL"),
    )
    op.create_index(
        "uq_scheduled_task_runs_one_running",
        "scheduled_task_runs",
        ["scheduled_task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_scheduled_task_runs_task_id_started_at",
        "scheduled_task_runs",
        ["scheduled_task_id", "started_at"],
    )

    # --- tool_connections --------------------------------------------------------------
    op.create_table(
        "tool_connections",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("toolkit_slug", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("composio_connected_account_id", sa.String(100), nullable=True),
        sa.Column("composio_connection_request_id", sa.String(100), nullable=True),
        sa.Column("connected_label", sa.String(200), nullable=True),
        sa.Column("connected_email", sa.String(320), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_connections")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_tool_connections_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "toolkit_slug", name="uq_tool_connections_user_toolkit"),
        sa.CheckConstraint(
            "status IN ('pending','connected','failed','revoked')",
            name=op.f("ck_tool_connections_valid_status"),
        ),
    )

    # --- llm_calls ---------------------------------------------------------------------
    _replace_llm_call_vocabularies(_OPERATIONS_004, _ORIGINS_004)


def downgrade() -> None:
    # Restoring the old vocabularies fails while the log holds calls made by the
    # assistant. That is deliberate: the log is append-only, and deciding to delete those
    # rows belongs to the operator, not to a migration.
    _replace_llm_call_vocabularies(_OPERATIONS_003, _ORIGINS_003)
    op.drop_table("tool_connections")
    op.drop_table("scheduled_task_runs")
    op.drop_table("scheduled_tasks")
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
    op.drop_table("app_users")
