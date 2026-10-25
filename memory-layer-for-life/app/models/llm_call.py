import uuid
from datetime import datetime
from decimal import Decimal

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation


class LlmCall(Base, UUIDMixin, TimestampMixin):
    """Append-only log of calls to a model provider. One row per call.

    A row holds facts about a call: what was asked for, how long it took, what it cost,
    and how it ended. It never holds the prompt, the messages, or the model's output.
    What a call was about is found through the run it links to, and ``origin`` says which
    link applies.

    ``estimated_cost_usd`` is computed from list prices when the row is written and is
    never recomputed. It is NULL when the model's price is not known.
    """

    __tablename__ = "llm_calls"

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    requested_model: Mapped[str] = mapped_column(String(100), nullable=False)
    # The model that answered. It differs from the requested one after a refusal fallback.
    response_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refusal_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    stop_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_read_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cache_creation_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    processing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=True
    )
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="RESTRICT"), nullable=True
    )
    evaluation_case_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    playground_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("playground_runs.id", ondelete="RESTRICT"), nullable=True
    )
    # The app user a call was made for, which is how usage is counted per user. Set to
    # NULL when the user deletes their account: the call's facts stay, its owner goes.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(enum_check("operation", LlmOperation), name="valid_operation"),
        CheckConstraint(enum_check("origin", LlmCallOrigin), name="valid_origin"),
        CheckConstraint(enum_check("status", LlmCallStatus), name="valid_status"),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_error_code"
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cache_read_input_tokens >= 0 "
            "AND cache_creation_input_tokens >= 0",
            name="non_negative_tokens",
        ),
        CheckConstraint("duration_ms >= 0", name="non_negative_duration"),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0", name="non_negative_cost"
        ),
        # A call made for a run always names that run.
        CheckConstraint(
            "(origin <> 'pipeline' OR processing_run_id IS NOT NULL) "
            "AND (origin <> 'playground' OR playground_run_id IS NOT NULL) "
            "AND (origin <> 'evaluation' OR evaluation_run_id IS NOT NULL)",
            name="origin_has_link",
        ),
        Index("ix_llm_calls_started_at", "started_at"),
        Index("ix_llm_calls_origin_started_at", "origin", "started_at"),
        Index("ix_llm_calls_processing_run_id", "processing_run_id"),
        Index("ix_llm_calls_evaluation_run_id", "evaluation_run_id"),
        Index("ix_llm_calls_playground_run_id", "playground_run_id"),
        Index("ix_llm_calls_user_id_started_at", "user_id", "started_at"),
    )
