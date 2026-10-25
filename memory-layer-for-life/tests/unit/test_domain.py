"""Pure domain rules: identities, normalization, the run state machine, versions."""

import hashlib
import uuid
from datetime import timedelta

import pytest

from app.domain.enums import ProcessingStatus
from app.domain.errors import IllegalRunTransitionError, InvalidProcessingUnitError
from app.domain.identity import (
    IDEMPOTENCY_KEY_SCHEME,
    content_sha256,
    processing_idempotency_key,
)
from app.domain.normalization import (
    contains_quote,
    locate_span,
    normalize_entity_name,
    normalize_for_matching,
    normalize_message_text,
)
from app.domain.run_state import (
    SETTLED_STATUSES,
    RetryPolicy,
    can_transition,
    ensure_transition,
)
from app.domain.versions import (
    EXTRACTION_SCHEMA_VERSION,
    PIPELINE_VERSION,
    ExtractorDescriptor,
    PipelineFingerprint,
)

DESCRIPTOR = ExtractorDescriptor(provider="anthropic", model="claude-haiku-5-5", prompt_version="1")
FINGERPRINT = PipelineFingerprint.for_extractor(DESCRIPTOR)

# --- Identity -------------------------------------------------------------------------


def test_content_hash_is_sha256_of_the_exact_utf8_bytes() -> None:
    text = "500 petrol " + chr(0x20B9)

    assert content_sha256(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert content_sha256("a") != content_sha256("a ")


def test_idempotency_key_is_stable_and_compact() -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]

    key = processing_idempotency_key(ids, FINGERPRINT)

    assert key == processing_idempotency_key(list(ids), FINGERPRINT)
    assert key.startswith(f"{IDEMPOTENCY_KEY_SCHEME}:")
    assert len(key) == len(IDEMPOTENCY_KEY_SCHEME) + 1 + 64
    assert len(key) <= 255


def test_idempotency_key_depends_on_messages_order_and_configuration() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    base = processing_idempotency_key([first, second], FINGERPRINT)
    other_prompt = PipelineFingerprint.for_extractor(
        ExtractorDescriptor(provider="anthropic", model="claude-haiku-5-5", prompt_version="2")
    )
    other_model = PipelineFingerprint.for_extractor(
        ExtractorDescriptor(provider="anthropic", model="another-model", prompt_version="1")
    )

    assert processing_idempotency_key([second, first], FINGERPRINT) != base
    assert processing_idempotency_key([first], FINGERPRINT) != base
    assert processing_idempotency_key([first, uuid.uuid4()], FINGERPRINT) != base
    assert processing_idempotency_key([first, second], other_prompt) != base
    assert processing_idempotency_key([first, second], other_model) != base


def test_idempotency_key_rejects_an_invalid_unit() -> None:
    message_id = uuid.uuid4()

    with pytest.raises(InvalidProcessingUnitError):
        processing_idempotency_key([], FINGERPRINT)
    with pytest.raises(InvalidProcessingUnitError):
        processing_idempotency_key([message_id, message_id], FINGERPRINT)


# --- Versions -------------------------------------------------------------------------


def test_fingerprint_covers_every_component() -> None:
    assert FINGERPRINT.as_dict() == {
        "pipeline_version": PIPELINE_VERSION,
        "normalizer_version": "1",
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "extractor_provider": "anthropic",
        "extractor_model": "claude-haiku-5-5",
        "extractor_prompt_version": "1",
        "resolver_version": "1",
        "memory_builder_version": "1",
    }
    assert len(FINGERPRINT.digest()) == 64


def test_fingerprint_digest_changes_with_any_component() -> None:
    digests = {FINGERPRINT.digest()}
    for field_name in FINGERPRINT.as_dict():
        changed = PipelineFingerprint(**{**FINGERPRINT.as_dict(), field_name: "changed"})
        digests.add(changed.digest())

    assert len(digests) == len(FINGERPRINT.as_dict()) + 1


def test_extractor_version_fits_its_column() -> None:
    assert DESCRIPTOR.version == "anthropic:1"
    assert len(DESCRIPTOR.version) <= 50


# --- Normalization --------------------------------------------------------------------


def test_message_normalization_is_conservative() -> None:
    narrow_no_break_space, zero_width_space, left_to_right_mark = (
        chr(0x202F),
        chr(0x200B),
        chr(0x200E),
    )
    first_line = f"{left_to_right_mark}7:40{narrow_no_break_space}pm:  himym{zero_width_space}  "
    raw = first_line + chr(13) + chr(10) + "blog   " + chr(13)

    assert normalize_message_text(raw) == "7:40 pm:  himym" + chr(10) + "blog"


def test_message_normalization_keeps_meaningful_characters() -> None:
    zero_width_joiner = chr(0x200D)
    family = chr(0x1F468) + zero_width_joiner + chr(0x1F469)
    rupee = chr(0x20B9)
    text = f"Raju owes {rupee}2980?? *buy* gifts {family} 232+104"

    assert normalize_message_text(text) == text


def test_message_normalization_is_idempotent_and_composes_unicode() -> None:
    decomposed = "cafe" + chr(0x0301)

    once = normalize_message_text(decomposed)

    assert once == "caf" + chr(0x00E9)
    assert normalize_message_text(once) == once


def test_matching_key_ignores_case_and_spacing() -> None:
    assert normalize_for_matching("  Buy   MILK\n now ") == "buy milk now"
    assert normalize_for_matching("Stra" + chr(0x00DF) + "e") == "strasse"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Harsh", "harsh"),
        ("  harsh. ", "harsh"),
        ('"Netra",', "netra"),
        ("(ZS)", "zs"),
        ("C++", "c++"),
        ("C#", "c#"),
        ("Node.js", "node.js"),
        ("Varun   Mayya", "varun mayya"),
        ("...", ""),
    ],
)
def test_entity_name_normalization(name: str, expected: str) -> None:
    assert normalize_entity_name(name) == expected


def test_quote_containment_tolerates_case_and_spacing_only() -> None:
    text = "232+104 groceries\nfor chicken"

    assert contains_quote(text, "Groceries for   CHICKEN")
    assert not contains_quote(text, "groceries for dinner")
    assert not contains_quote(text, "   ")


def test_span_location_reports_only_verified_offsets() -> None:
    assert locate_span("call Asha tomorrow", "Asha") == (5, 9)
    assert locate_span("call asha tomorrow", "Asha") == (5, 9)
    assert locate_span("110 tom, 20 tom", "tom") == (4, 7)
    assert locate_span("hackathons in blr", "Bengaluru") is None
    assert locate_span("anything", "") is None
    assert locate_span("price is 5.0", "5x0") is None


# --- Run state machine ----------------------------------------------------------------

LEGAL = {
    (ProcessingStatus.QUEUED, ProcessingStatus.RUNNING),
    (ProcessingStatus.RUNNING, ProcessingStatus.SUCCEEDED),
    (ProcessingStatus.RUNNING, ProcessingStatus.NEEDS_REVIEW),
    (ProcessingStatus.RUNNING, ProcessingStatus.FAILED),
    (ProcessingStatus.RUNNING, ProcessingStatus.QUEUED),
    (ProcessingStatus.FAILED, ProcessingStatus.QUEUED),
    (ProcessingStatus.NEEDS_REVIEW, ProcessingStatus.QUEUED),
}


@pytest.mark.parametrize("current", list(ProcessingStatus))
@pytest.mark.parametrize("target", list(ProcessingStatus))
def test_only_the_documented_transitions_are_legal(
    current: ProcessingStatus, target: ProcessingStatus
) -> None:
    expected = (current, target) in LEGAL

    assert can_transition(current, target) is expected
    if expected:
        ensure_transition(current, target)
    else:
        with pytest.raises(IllegalRunTransitionError):
            ensure_transition(current, target)


def test_a_succeeded_run_can_go_nowhere() -> None:
    assert not any(
        can_transition(ProcessingStatus.SUCCEEDED, target) for target in ProcessingStatus
    )
    assert {
        ProcessingStatus.SUCCEEDED,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEEDS_REVIEW,
    } == SETTLED_STATUSES


def test_retry_policy_backs_off_exponentially_up_to_a_cap() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay_seconds=30, max_delay_seconds=100)

    assert [policy.delay_after(attempt) for attempt in (1, 2, 3, 4)] == [
        timedelta(seconds=30),
        timedelta(seconds=60),
        timedelta(seconds=100),
        timedelta(seconds=100),
    ]
    assert [policy.allows_retry_after(attempt) for attempt in (1, 4, 5, 6)] == [
        True,
        True,
        False,
        False,
    ]


def test_retry_policy_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="negative"):
        RetryPolicy(base_delay_seconds=-1)
    with pytest.raises(ValueError, match="attempt_number"):
        RetryPolicy().delay_after(0)
