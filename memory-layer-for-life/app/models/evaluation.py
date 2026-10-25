import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check, nullable_enum_check
from app.domain.enums import (
    EvaluationCaseOutcome,
    EvaluationRunStatus,
    EvaluationTrigger,
    ExtractionDisposition,
)


class EvaluationRun(Base, UUIDMixin, TimestampMixin):
    """One run of the golden dataset through a model, and its scores.

    The case counters grow while the run is in progress, so a running evaluation can be
    watched. ``check_totals``, ``not_gating``, and ``usage`` are written when it ends.

    ``heartbeat_at`` moves every time a case finishes. A run that is still ``running``
    long after its last heartbeat belongs to a process that stopped.

    ``calls_logged`` is false for a run imported from a report file: its model calls
    were made before the call log existed, so only its totals are known.
    """

    __tablename__ = "evaluation_runs"

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EvaluationRunStatus.RUNNING.value,
        server_default=EvaluationRunStatus.RUNNING.value,
    )
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False)

    extractor_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    extraction_effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    judge_effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    judge_prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    concurrency: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cases_total: Mapped[int] = mapped_column(Integer, nullable=False)
    cases_passed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cases_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cases_not_evaluated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    check_totals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    not_gating: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    calls_logged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Folder name of the report file an imported run came from. Importing is idempotent.
    source_report: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(enum_check("status", EvaluationRunStatus), name="valid_status"),
        CheckConstraint(enum_check("trigger", EvaluationTrigger), name="valid_trigger"),
        CheckConstraint(
            "cases_total >= 0 AND cases_passed >= 0 AND cases_failed >= 0 "
            "AND cases_not_evaluated >= 0",
            name="non_negative_case_counts",
        ),
        CheckConstraint(
            "cases_passed + cases_failed + cases_not_evaluated <= cases_total",
            name="counted_cases_within_total",
        ),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_when_not_running"
        ),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0", name="non_negative_cost"
        ),
        Index("ix_evaluation_runs_started_at", "started_at"),
        Index("ix_evaluation_runs_status", "status"),
    )


class EvaluationCaseResult(Base, UUIDMixin, TimestampMixin):
    """Result of one golden case in one evaluation run.

    ``document`` is the whole case as the evaluation saw it: the source messages, the
    expected memory, what the model produced, every check, and the judge's explanations.
    It has the shape of one entry of a ``report.json`` file, so imported and live runs
    are stored alike. The dataset is built from private messages, and so is this column.
    """

    __tablename__ = "evaluation_case_results"

    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Position of the case in the dataset, so results read in dataset order.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    produced_disposition: Mapped[str | None] = mapped_column(String(20), nullable=True)
    failed_checks: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "evaluation_run_id", "case_id", name="uq_evaluation_case_results_run_case"
        ),
        CheckConstraint(enum_check("outcome", EvaluationCaseOutcome), name="valid_outcome"),
        CheckConstraint(
            enum_check("expected_outcome", ExtractionDisposition), name="valid_expected_outcome"
        ),
        CheckConstraint(
            nullable_enum_check("produced_disposition", ExtractionDisposition),
            name="valid_produced_disposition",
        ),
        CheckConstraint("position >= 0", name="non_negative_position"),
        Index("ix_evaluation_case_results_run_position", "evaluation_run_id", "position"),
        Index("ix_evaluation_case_results_case_id", "case_id"),
    )
