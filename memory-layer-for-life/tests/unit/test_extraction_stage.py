"""Extraction contract, grounding checks, request building, and memory construction."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    EntityType,
    ExtractionDisposition,
    MemoryState,
    MemoryStatus,
    MemoryType,
    Sensitivity,
    SourceRole,
)
from app.domain.errors import InvalidExtractionOutputError
from app.models.raw_message import RawMessage
from app.schemas.extraction import (
    ExtractedEntityMention,
    ExtractionOutput,
    ExtractionPayload,
    FinancialInfo,
)
from app.schemas.memory_metadata import MemoryMetadata
from app.services.processing.extraction import build_extraction_request, validate_grounding
from app.services.processing.memory_builder import MemoryBuilder
from app.services.processing.resolution import is_usable_name
from tests.support.extraction import (
    abstention,
    evidence,
    extraction,
    financial,
    memory,
    mention,
    temporal,
)


def stored_message(content: str, sent_at: datetime | None = None) -> RawMessage:
    return RawMessage(
        id=uuid.uuid4(),
        source="api_input",
        content=content,
        content_sha256="0" * 64,
        source_created_at=sent_at,
    )


# --- Contract -------------------------------------------------------------------------


def test_output_round_trips_through_json() -> None:
    output = extraction(
        memory(
            "Petrol split with Harsh",
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            mention_indexes=[0],
            financial=financial(200, component_amounts=[400], calculation="400 / 2"),
            temporal=temporal("tomorrow"),
            ambiguity="Whose share is unclear.",
        ),
        mentions=[mention("Harsh")],
    )

    assert ExtractionOutput.model_validate_json(output.model_dump_json()) == output


def test_abstention_cannot_carry_memories() -> None:
    with pytest.raises(ValidationError, match="cannot contain memories"):
        ExtractionOutput(
            disposition=ExtractionDisposition.ABSTAIN,
            disposition_reason="Too little to go on.",
            memories=[memory()],
            entity_mentions=[],
        )


@pytest.mark.parametrize(
    "disposition", [ExtractionDisposition.EXTRACT, ExtractionDisposition.CONTEXT]
)
def test_a_non_abstaining_output_needs_a_memory(disposition: ExtractionDisposition) -> None:
    with pytest.raises(ValidationError, match="at least one memory"):
        ExtractionOutput(
            disposition=disposition,
            disposition_reason="Something is here.",
            memories=[],
            entity_mentions=[],
        )


def test_entity_links_must_point_at_listed_mentions() -> None:
    with pytest.raises(ValidationError, match="out of range"):
        extraction(memory(mention_indexes=[1]), mentions=[mention("Asha")])
    with pytest.raises(ValidationError, match="more than once"):
        extraction(memory(mention_indexes=[0, 0]), mentions=[mention("Asha")])


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"confidence": 1.01}, id="confidence above one"),
        pytest.param({"confidence": -0.01}, id="confidence below zero"),
        pytest.param({"content": ""}, id="empty content"),
        pytest.param({"evidence": []}, id="no evidence"),
        pytest.param({"memory_type": "rumour"}, id="unknown type"),
        pytest.param({"state": "finished"}, id="unknown state"),
        pytest.param({"sensitivity": "top_secret"}, id="unknown sensitivity"),
        pytest.param({"surprise": True}, id="unknown field"),
    ],
)
def test_invalid_memories_are_rejected(broken: dict[str, object]) -> None:
    valid = memory().model_dump(mode="json")

    with pytest.raises(ValidationError):
        type(memory()).model_validate({**valid, **broken})


def test_every_contract_field_is_required() -> None:
    """The model must state each field explicitly, including nulls."""
    valid = memory().model_dump(mode="json")
    for field_name in valid:
        incomplete = {key: value for key, value in valid.items() if key != field_name}
        with pytest.raises(ValidationError):
            type(memory()).model_validate(incomplete)

    with pytest.raises(ValidationError):
        FinancialInfo.model_validate({"amount": 5})


def test_evidence_and_mentions_reject_bad_references() -> None:
    with pytest.raises(ValidationError):
        evidence(-1, "quote")
    with pytest.raises(ValidationError):
        evidence(0, "")
    with pytest.raises(ValidationError):
        ExtractedEntityMention(
            entity_type=EntityType.PERSON, mention_text="", message_index=0, confidence=0.5
        )


def test_payload_envelope_names_its_schema_version() -> None:
    message_id = uuid.uuid4()
    payload = ExtractionPayload(
        normalizer_version="1", message_ids=[message_id], output=extraction()
    )

    stored = payload.model_dump(mode="json")

    assert stored["schema_version"] == "1.0"
    assert stored["message_ids"] == [str(message_id)]
    assert ExtractionPayload.model_validate(stored) == payload
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate({**stored, "schema_version": "2.0"})
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate({**stored, "message_ids": []})


# --- Grounding ------------------------------------------------------------------------


def test_references_inside_the_unit_are_accepted() -> None:
    output = extraction(
        memory(evidence_refs=[evidence(0, "a"), evidence(1, "b")], mention_indexes=[0]),
        mentions=[mention("Asha", message_index=1)],
    )

    validate_grounding(output, message_count=2)
    validate_grounding(abstention(), message_count=1)


def test_evidence_outside_the_unit_is_rejected() -> None:
    output = extraction(memory(evidence_refs=[evidence(2, "quote")]))

    with pytest.raises(InvalidExtractionOutputError, match="Memory 0 cites message 2"):
        validate_grounding(output, message_count=2)


def test_a_mention_outside_the_unit_is_rejected() -> None:
    output = extraction(memory(), mentions=[mention("Asha", message_index=1)])

    with pytest.raises(InvalidExtractionOutputError, match="Entity mention 0 cites message 1"):
        validate_grounding(output, message_count=1)


# --- Request building -----------------------------------------------------------------


def test_request_carries_normalized_text_and_local_time() -> None:
    messages = [
        stored_message("  buy gifts  ", datetime(2026, 4, 18, 21, 57, tzinfo=UTC)),
        stored_message("for parents"),
    ]

    request = build_extraction_request(messages, timezone_name="Asia/Kolkata")

    first, second = request.messages
    assert (first.index, first.text) == (0, "buy gifts")
    assert first.sent_at_local == datetime(2026, 4, 19, 3, 27)
    assert first.sent_at_local.tzinfo is None
    assert (second.index, second.text, second.sent_at_local) == (1, "for parents", None)
    assert request.timezone_name == "Asia/Kolkata"


# --- Entity names ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "usable"),
    [("asha", True), ("c++", True), ("x", True), ("", False), ("...", False), ("a" * 501, False)],
)
def test_usable_entity_names(name: str, usable: bool) -> None:
    assert is_usable_name(name) is usable


# --- Memory construction --------------------------------------------------------------


def test_builder_creates_a_proposed_draft_with_validated_metadata() -> None:
    sent_at = datetime(2026, 6, 27, 11, 28, tzinfo=UTC)
    messages = [stored_message("400/2 - petrol harsh", sent_at)]
    entity_id = uuid.uuid4()
    output = extraction(
        memory(
            "Petrol split with Harsh: 200",
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            confidence=0.876,
            sensitivity=Sensitivity.SENSITIVE,
            evidence_refs=[evidence(0, "400/2 - petrol HARSH")],
            mention_indexes=[0],
            financial=financial(200, component_amounts=[400], calculation="400 / 2"),
            ambiguity="Whose share is unclear.",
        ),
        mentions=[mention("harsh")],
        disposition=ExtractionDisposition.EXTRACT,
    )

    (draft,) = MemoryBuilder().build(output, messages, {0: entity_id})

    assert draft.ordinal == 0
    assert draft.memory_type == "financial_note"
    assert draft.status is MemoryStatus.PROPOSED
    assert draft.confidence == 0.88
    assert draft.normalized_content == "petrol split with harsh: 200"
    assert draft.observed_at == sent_at
    assert draft.entity_ids == (entity_id,)
    metadata = MemoryMetadata.model_validate(draft.metadata)
    assert metadata.disposition is ExtractionDisposition.EXTRACT
    assert metadata.state is MemoryState.NOT_APPLICABLE
    assert metadata.sensitivity is Sensitivity.SENSITIVE
    assert metadata.financial is not None
    assert metadata.financial.amount == 200
    assert metadata.financial.currency is None
    (source,) = draft.sources
    assert source.source_role is SourceRole.SUPPORTING
    # The quote is kept as the extractor gave it once it is verified.
    assert source.evidence_text == "400/2 - petrol HARSH"


def test_builder_links_cited_messages_as_supporting_and_the_rest_as_context() -> None:
    early = datetime(2026, 3, 21, 16, 1, tzinfo=UTC)
    late = datetime(2026, 3, 21, 16, 41, tzinfo=UTC)
    messages = [
        stored_message("232+104 groceries", early),
        stored_message("chilli, turmeric", late),
        stored_message("To marinate", late),
    ]
    output = extraction(
        memory(
            "Groceries for chicken",
            evidence_refs=[
                evidence(0, "232+104"),
                evidence(1, "chilli"),
                evidence(1, "turmeric"),
                evidence(1, "chilli"),
                evidence(0, "this is not in the message"),
            ],
        )
    )

    (draft,) = MemoryBuilder().build(output, messages, {})

    first, second, third = draft.sources
    assert [source.raw_message_id for source in draft.sources] == [item.id for item in messages]
    assert (first.source_role, first.evidence_text) == (SourceRole.SUPPORTING, "232+104")
    # Several quotes from one message are kept together, without repeats.
    assert (second.source_role, second.evidence_text) == (SourceRole.SUPPORTING, "chilli\nturmeric")
    assert (third.source_role, third.evidence_text) == (SourceRole.CONTEXTUAL, None)
    # Observed when the latest supporting message was written.
    assert draft.observed_at == late


def test_builder_keeps_the_link_when_no_quote_can_be_verified() -> None:
    messages = [stored_message("buy milk")]
    output = extraction(memory(evidence_refs=[evidence(0, "purchase dairy")]))

    (draft,) = MemoryBuilder().build(output, messages, {})

    (source,) = draft.sources
    assert (source.source_role, source.evidence_text) == (SourceRole.SUPPORTING, None)
    assert draft.observed_at is None


def test_builder_links_only_resolved_entities_once() -> None:
    messages = [stored_message("Sam, harsh, nishant")]
    resolved = uuid.uuid4()
    output = extraction(
        memory("Group outing", mention_indexes=[0, 1, 2]),
        memory("Second memory"),
        mentions=[mention("Sam"), mention("harsh"), mention("nishant")],
    )

    first, second = MemoryBuilder().build(output, messages, {0: resolved, 2: resolved})

    # Mention 1 is unresolved or ambiguous, so it produces no link.
    assert first.entity_ids == (resolved,)
    assert second.entity_ids == ()
    assert (first.ordinal, second.ordinal) == (0, 1)


def test_builder_never_derives_a_validity_period() -> None:
    """Resolved dates stay in metadata; the draft has no validity fields to fill."""
    messages = [stored_message("849 pant tomorrow", datetime(2026, 9, 7, 16, 36, tzinfo=UTC))]
    output = extraction(
        memory(
            "Pants for 849",
            temporal=temporal("tomorrow", resolved_date=datetime(2026, 9, 8).date()),
        )
    )

    (draft,) = MemoryBuilder().build(output, messages, {})

    assert draft.metadata["temporal"] == {"expression": "tomorrow", "resolved_date": "2026-09-08"}
    assert not hasattr(draft, "valid_from")
