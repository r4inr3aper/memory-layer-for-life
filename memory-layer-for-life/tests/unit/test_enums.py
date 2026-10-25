"""The controlled vocabularies. A value added here needs a migration, so changes are loud."""

from app.db.constraints import enum_check, nullable_enum_check
from app.domain.enums import (
    CloseReason,
    EntityType,
    ExtractionDisposition,
    ExtractionStatus,
    ImportStatus,
    InsightKind,
    InsightTarget,
    LifeBucket,
    MemoryEntityRelation,
    MemoryEventAction,
    MemoryOrigin,
    MemoryState,
    MemoryStatus,
    MemoryType,
    MessageSource,
    PipelineStage,
    ProcessingStatus,
    RelationType,
    ReplayAction,
    RunEventType,
    Sensitivity,
    SourceRole,
    SuggestionKind,
)


def values(enum: type) -> set[str]:
    return {item.value for item in enum}  # type: ignore[attr-defined]


def test_message_source_values() -> None:
    assert values(MessageSource) == {
        "whatsapp_import",
        "manual_capture",
        "api_input",
        "app_chat",
        "file_upload",
    }


def test_processing_status_values() -> None:
    assert values(ProcessingStatus) == {"queued", "running", "succeeded", "failed", "needs_review"}


def test_pipeline_stages_are_listed_in_execution_order() -> None:
    assert [stage.value for stage in PipelineStage] == [
        "normalize",
        "extract",
        "resolve",
        "construct",
        "persist",
    ]


def test_run_event_values() -> None:
    assert values(RunEventType) == {
        "queued",
        "claimed",
        "extraction_stored",
        "extraction_reused",
        "retry_scheduled",
        "succeeded",
        "needs_review",
        "failed",
        "requeued",
        "lease_expired",
        "reviewed",
    }


def test_extraction_status_values() -> None:
    assert values(ExtractionStatus) == {"pending", "succeeded", "failed", "needs_review"}


def test_extraction_disposition_values() -> None:
    assert values(ExtractionDisposition) == {"extract", "context", "abstain"}


def test_memory_type_values() -> None:
    assert values(MemoryType) == {
        "semantic_fact",
        "episodic_event",
        "preference",
        "intention",
        "task",
        "commitment",
        "goal",
        "project",
        "decision",
        "idea",
        "open_loop",
        "plan",
        "note",
        "reflection",
        "resource",
        "financial_note",
    }


def test_memory_status_and_state_are_separate_vocabularies() -> None:
    assert values(MemoryStatus) == {"proposed", "active", "superseded", "retracted"}
    assert values(MemoryState) == {"not_applicable", "open", "planned", "done"}
    assert not values(MemoryStatus) & values(MemoryState)


def test_entity_type_values() -> None:
    assert values(EntityType) == {
        "person",
        "organization",
        "project",
        "concept",
        "place",
        "event",
        "technology",
        "topic",
    }


def test_remaining_vocabularies() -> None:
    assert values(Sensitivity) == {"normal", "sensitive"}
    assert values(SourceRole) == {"supporting", "contradicting", "contextual"}
    assert values(MemoryEntityRelation) == {"mentions"}
    assert values(ReplayAction) == {"created", "requeued", "unchanged"}
    assert values(RelationType) == {
        "depends_on",
        "contradicts",
        "supersedes",
        "supports",
        "elaborates",
        "related_to",
    }
    assert values(MemoryOrigin) == {"pipeline", "user", "assistant", "app"}
    assert values(ImportStatus) == {"previewed", "queued"}
    assert values(CloseReason) == {"done", "dropped"}
    assert values(InsightKind) == {
        "money",
        "people.top",
        "people.quiet",
        "follow_through",
        "goal.quiet",
        "theme",
    }
    assert values(InsightTarget) == {"person", "memory", "todo", "memories"}
    assert values(LifeBucket) == {"overdue", "today", "upcoming", "later", "someday"}
    assert values(SuggestionKind) == {"duplicate", "conflict"}


def test_memory_event_values() -> None:
    assert values(MemoryEventAction) == {
        "created",
        "accepted",
        "retracted",
        "restored",
        "edited",
        "corrected",
        "superseded",
        "merged",
        "replaced",
        "suggestion_dismissed",
        "completed",
        "dropped",
        "reopened",
        "scheduled",
        "reminded",
    }


def test_enums_compare_as_strings() -> None:
    assert ProcessingStatus.QUEUED == "queued"
    assert EntityType.PERSON == "person"


def test_check_constraints_are_built_from_the_enums() -> None:
    assert enum_check("status", MemoryStatus) == (
        "status IN ('proposed','active','superseded','retracted')"
    )
    assert nullable_enum_check("stage", PipelineStage) == (
        "stage IS NULL OR stage IN ('normalize','extract','resolve','construct','persist')"
    )
