"""Row level security on every table

The application database is a Supabase project. Supabase publishes the public schema
through its Data API to anyone holding the project's publishable key, and that key is
built into the mobile app. A table without row level security would be readable and
writable through that API, past the application and its checks.

Row level security without a policy denies every role but the table's owner. The API
connects as the owner, which row level security does not restrict, so the application
is unaffected; the Data API sees nothing. A table added by a later migration must
enable it as well: ``tests/integration/test_row_level_security.py`` fails otherwise.

Revision ID: 005
Revises: 004
Create Date: 2026-10-18 00:00:01.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "alembic_version",
    "raw_messages",
    "processing_runs",
    "processing_run_messages",
    "processing_run_events",
    "extraction_results",
    "entities",
    "entity_mentions",
    "memories",
    "memory_sources",
    "memory_entities",
    "memory_relations",
    "playground_runs",
    "evaluation_runs",
    "evaluation_case_results",
    "llm_calls",
    "app_users",
    "chat_threads",
    "chat_messages",
    "scheduled_tasks",
    "scheduled_task_runs",
    "tool_connections",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
