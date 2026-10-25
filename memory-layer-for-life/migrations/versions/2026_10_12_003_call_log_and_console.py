"""Model call log, test calls, and stored evaluations

Adds what the test console needs:

* ``llm_calls``: an append-only log with one row per call to a model provider. It holds
  facts about the call and never its content.
* ``playground_runs``: single test calls made from the console, with what was sent and
  what came back.
* ``evaluation_runs`` and ``evaluation_case_results``: golden-dataset evaluations, so
  output quality can be compared across models and prompt versions.

Nothing existing is changed.

Revision ID: 003
Revises: 002
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISPOSITIONS = "'extract','context','abstain'"


def upgrade() -> None:
    # --- playground_runs ---------------------------------------------------------------
    op.create_table(
        "playground_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("messages", JSONB, nullable=False),
        sa.Column("timezone_name", sa.String(64), nullable=True),
        sa.Column("requested_model", sa.String(100), nullable=False),
        sa.Column("effort", sa.String(10), nullable=False),
        sa.Column("output", JSONB, nullable=True),
        sa.Column("raw_output", sa.Text, nullable=True),
        sa.Column("corrections", JSONB, nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playground_runs")),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name=op.f("ck_playground_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(messages) > 0", name=op.f("ck_playground_runs_has_messages")
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_playground_runs_finished_when_not_running"),
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR output IS NOT NULL",
            name=op.f("ck_playground_runs_succeeded_has_output"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL",
            name=op.f("ck_playground_runs_failed_has_error_code"),
        ),
    )
    op.create_index("ix_playground_runs_created_at", "playground_runs", ["created_at"])

    # --- evaluation_runs ---------------------------------------------------------------
    op.create_table(
        "evaluation_runs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("dataset_name", sa.String(255), nullable=False),
        sa.Column("extractor_model", sa.String(100), nullable=True),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("extraction_effort", sa.String(10), nullable=True),
        sa.Column("judge_model", sa.String(100), nullable=True),
        sa.Column("judge_effort", sa.String(10), nullable=True),
        sa.Column("judge_prompt_version", sa.String(20), nullable=True),
        sa.Column("concurrency", sa.Integer, nullable=True),
        sa.Column("cases_total", sa.Integer, nullable=False),
        sa.Column("cases_passed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cases_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cases_not_evaluated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("check_totals", JSONB, nullable=False, server_default="{}"),
        sa.Column("not_gating", JSONB, nullable=False, server_default="{}"),
        sa.Column("usage", JSONB, nullable=False, server_default="{}"),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("calls_logged", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("source_report", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
        sa.UniqueConstraint("source_report", name=op.f("uq_evaluation_runs_source_report")),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled','interrupted')",
            name=op.f("ck_evaluation_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "trigger IN ('console','cli','import')",
            name=op.f("ck_evaluation_runs_valid_trigger"),
        ),
        sa.CheckConstraint(
            "cases_total >= 0 AND cases_passed >= 0 AND cases_failed >= 0 "
            "AND cases_not_evaluated >= 0",
            name=op.f("ck_evaluation_runs_non_negative_case_counts"),
        ),
        sa.CheckConstraint(
            "cases_passed + cases_failed + cases_not_evaluated <= cases_total",
            name=op.f("ck_evaluation_runs_counted_cases_within_total"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_evaluation_runs_finished_when_not_running"),
        ),
        sa.CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name=op.f("ck_evaluation_runs_non_negative_cost"),
        ),
    )
    op.create_index("ix_evaluation_runs_started_at", "evaluation_runs", ["started_at"])
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])

    # --- evaluation_case_results -------------------------------------------------------
    op.create_table(
        "evaluation_case_results",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("expected_outcome", sa.String(20), nullable=False),
        sa.Column("produced_disposition", sa.String(20), nullable=True),
        sa.Column("failed_checks", JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_case_results")),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_evaluation_case_results_evaluation_run_id_evaluation_runs",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "evaluation_run_id", "case_id", name="uq_evaluation_case_results_run_case"
        ),
        sa.CheckConstraint(
            "outcome IN ('passed','failed','not_evaluated')",
            name=op.f("ck_evaluation_case_results_valid_outcome"),
        ),
        sa.CheckConstraint(
            f"expected_outcome IN ({_DISPOSITIONS})",
            name=op.f("ck_evaluation_case_results_valid_expected_outcome"),
        ),
        sa.CheckConstraint(
            f"produced_disposition IS NULL OR produced_disposition IN ({_DISPOSITIONS})",
            name=op.f("ck_evaluation_case_results_valid_produced_disposition"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_evaluation_case_results_non_negative_position")
        ),
    )
    op.create_index(
        "ix_evaluation_case_results_run_position",
        "evaluation_case_results",
        ["evaluation_run_id", "position"],
    )
    op.create_index("ix_evaluation_case_results_case_id", "evaluation_case_results", ["case_id"])

    # --- llm_calls ---------------------------------------------------------------------
    op.create_table(
        "llm_calls",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_model", sa.String(100), nullable=False),
        sa.Column("response_model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("effort", sa.String(10), nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("refusal_fallback", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("stop_reason", sa.String(50), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("provider_error_type", sa.String(100), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_creation_input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("processing_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_number", sa.Integer, nullable=True),
        sa.Column("evaluation_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("evaluation_case_id", sa.String(100), nullable=True),
        sa.Column("playground_run_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_llm_calls_processing_run_id_processing_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            name="fk_llm_calls_evaluation_run_id_evaluation_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["playground_run_id"],
            ["playground_runs.id"],
            name="fk_llm_calls_playground_run_id_playground_runs",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN ('extraction','judge','connection_check')",
            name=op.f("ck_llm_calls_valid_operation"),
        ),
        sa.CheckConstraint(
            "origin IN ('pipeline','playground','evaluation','other')",
            name=op.f("ck_llm_calls_valid_origin"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded','failed')", name=op.f("ck_llm_calls_valid_status")
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_llm_calls_failed_has_error_code"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cache_read_input_tokens >= 0 "
            "AND cache_creation_input_tokens >= 0",
            name=op.f("ck_llm_calls_non_negative_tokens"),
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_llm_calls_non_negative_duration")),
        sa.CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name=op.f("ck_llm_calls_non_negative_cost"),
        ),
        sa.CheckConstraint(
            "(origin <> 'pipeline' OR processing_run_id IS NOT NULL) "
            "AND (origin <> 'playground' OR playground_run_id IS NOT NULL) "
            "AND (origin <> 'evaluation' OR evaluation_run_id IS NOT NULL)",
            name=op.f("ck_llm_calls_origin_has_link"),
        ),
    )
    op.create_index("ix_llm_calls_started_at", "llm_calls", ["started_at"])
    op.create_index("ix_llm_calls_origin_started_at", "llm_calls", ["origin", "started_at"])
    op.create_index("ix_llm_calls_processing_run_id", "llm_calls", ["processing_run_id"])
    op.create_index("ix_llm_calls_evaluation_run_id", "llm_calls", ["evaluation_run_id"])
    op.create_index("ix_llm_calls_playground_run_id", "llm_calls", ["playground_run_id"])


def downgrade() -> None:
    # The log references the other three tables, so it goes first.
    op.drop_table("llm_calls")
    op.drop_table("evaluation_case_results")
    op.drop_table("evaluation_runs")
    op.drop_table("playground_runs")
