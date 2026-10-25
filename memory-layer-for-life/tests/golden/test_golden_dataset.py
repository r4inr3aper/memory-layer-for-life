"""The golden dataset itself: well-formed, fully mapped, and consistent with the scorer.

None of these tests calls a model or needs a database.
"""

import json
from collections import Counter
from datetime import datetime

import jsonschema
import pytest

from app.domain.enums import ExtractionDisposition, MemoryState, MemoryType
from evaluation.fixture_extractor import GoldenFixtureExtractor, case_request_key
from evaluation.golden import (
    DEFAULT_DATASET_PATH,
    DEFAULT_SCHEMA_PATH,
    GoldenCase,
    GoldenDatasetError,
    load_golden_cases,
    parse_local_timestamp,
    to_extraction_request,
)
from evaluation.label_mapping import (
    ACCEPTED_MEMORY_TYPES,
    ACCEPTED_STATES,
    UnmappedLabelError,
    accepted_memory_types,
    accepted_states,
    allows_done,
)
from evaluation.scoring import score_case
from tests.support.golden import golden_case_params, ideal_verdicts, require_golden_cases

# --- File format ----------------------------------------------------------------------


def test_every_line_satisfies_the_published_schema() -> None:
    require_golden_cases()
    schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    problems = []
    for number, line in enumerate(
        DEFAULT_DATASET_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.strip():
            problems += [
                f"line {number}: {error.message}"
                for error in validator.iter_errors(json.loads(line))
            ]

    assert problems == []


def test_dataset_shape() -> None:
    cases = require_golden_cases()

    assert len(cases) == 124
    assert len({case.case_id for case in cases}) == len(cases)
    assert Counter(case.expected.outcome for case in cases) == {
        ExtractionDisposition.EXTRACT: 101,
        ExtractionDisposition.CONTEXT: 15,
        ExtractionDisposition.ABSTAIN: 8,
    }
    # No label has been reviewed yet. The suite must not pretend otherwise.
    assert {case.review_status for case in cases} == {"draft_needs_human_review"}


def test_abstention_cases_expect_no_memory_and_other_cases_expect_one() -> None:
    for case in require_golden_cases():
        expected_count = 0 if case.expects_abstention else 1
        assert len(case.expected.memories) == expected_count, case.case_id


def test_message_identity_is_consistent_across_cases() -> None:
    """An event id always names the same message, wherever it is reused."""
    seen: dict[str, tuple[str, str]] = {}
    for case in require_golden_cases():
        assert case.source_event_ids == case.unit_key, case.case_id
        for message in case.input.messages:
            identity = (message.text, message.timestamp_local)
            assert seen.setdefault(message.event_id, identity) == identity, message.event_id


def test_timestamps_parse_as_local_time() -> None:
    narrow_no_break_space = chr(0x202F)

    assert parse_local_timestamp(f"24/02/26 1:59{narrow_no_break_space}am") == datetime(
        2026, 2, 24, 1, 59
    )
    assert parse_local_timestamp(f"15/03/26 7:41{narrow_no_break_space}pm") == datetime(
        2026, 3, 15, 19, 41
    )
    assert parse_local_timestamp(f"25/04/26 12:05{narrow_no_break_space}am") == datetime(
        2026, 4, 25, 0, 5
    )
    for case in require_golden_cases():
        for message in case.input.messages:
            assert message.sent_at_local.tzinfo is None


def test_unreadable_timestamp_is_reported() -> None:
    with pytest.raises(GoldenDatasetError, match="timestamp"):
        parse_local_timestamp("yesterday at noon")


def test_escaped_line_breaks_are_restored() -> None:
    cases = require_golden_cases()
    backslash_n = chr(92) + "n"
    multi_line = [
        message for case in cases for message in case.input.messages if backslash_n in message.text
    ]

    assert multi_line, "the dataset is expected to contain multi-line messages"
    for message in multi_line:
        assert backslash_n not in message.content
        assert message.content.count("\n") == message.text.count(backslash_n)


def test_extraction_request_mirrors_the_case() -> None:
    case = next(case for case in require_golden_cases() if len(case.input.messages) == 3)

    request = to_extraction_request(case)

    assert [message.index for message in request.messages] == [0, 1, 2]
    assert [message.sent_at_local for message in request.messages] == [
        message.sent_at_local for message in case.input.messages
    ]
    assert all(message.text for message in request.messages)


def test_malformed_dataset_names_the_line(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "broken.jsonl"
    path.write_text('{"case_id": "ok"}\n', encoding="utf-8")

    with pytest.raises(GoldenDatasetError, match="line 1"):
        load_golden_cases(path)


def test_empty_dataset_is_an_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(GoldenDatasetError, match="no cases"):
        load_golden_cases(path)


# --- Label mapping --------------------------------------------------------------------


def test_every_label_in_the_dataset_is_mapped() -> None:
    cases = require_golden_cases()
    memories = [memory for case in cases for memory in case.expected.memories]

    assert {memory.type for memory in memories} == set(ACCEPTED_MEMORY_TYPES)
    assert {memory.status for memory in memories} == set(ACCEPTED_STATES)


def test_mapping_values_are_distinct_members_of_the_vocabulary() -> None:
    for label, types in ACCEPTED_MEMORY_TYPES.items():
        assert types, label
        assert len(set(types)) == len(types), label
        assert all(isinstance(item, MemoryType) for item in types), label
    for label, states in ACCEPTED_STATES.items():
        assert states, label
        assert len(set(states)) == len(states), label
        assert all(isinstance(item, MemoryState) for item in states), label


def test_most_cases_are_checked_against_a_single_type() -> None:
    """The mapping must stay a real check, not a way to accept anything."""
    cases = require_golden_cases()
    memories = [memory for case in cases for memory in case.expected.memories]
    strict = [memory for memory in memories if len(accepted_memory_types(memory.type)) == 1]

    assert len(strict) / len(memories) > 0.6
    assert max(len(types) for types in ACCEPTED_MEMORY_TYPES.values()) <= 4


def test_unknown_labels_are_reported() -> None:
    with pytest.raises(UnmappedLabelError):
        accepted_memory_types("horoscope")
    with pytest.raises(UnmappedLabelError):
        accepted_states("vibes")
    with pytest.raises(UnmappedLabelError):
        allows_done("vibes")


def test_only_observed_things_may_be_marked_done() -> None:
    assert allows_done("observed") is True
    for status in set(ACCEPTED_STATES) - {"observed"}:
        assert allows_done(status) is False
        assert MemoryState.DONE not in accepted_states(status)


# --- Fixture extractor and scorer agree with the labels -------------------------------


@pytest.mark.parametrize("case", golden_case_params())
def test_expected_output_of_each_case_passes_every_check(case: GoldenCase) -> None:
    """The labels, the mapping, and the scorer are mutually consistent for every case."""
    extractor = GoldenFixtureExtractor(require_golden_cases())
    output = extractor.expected_output(case)
    verdicts = None if case.expects_abstention else ideal_verdicts(case, output, extractor)

    score = score_case(case, output, verdicts)

    assert score.passed, [(check.name, check.detail) for check in score.failed_checks]
    assert score.disposition_agrees is True
    if not case.expects_abstention:
        assert score.state_agrees is True


def test_cases_sharing_an_input_are_answered_together() -> None:
    cases = require_golden_cases()
    extractor = GoldenFixtureExtractor(cases)
    shared = [case for case in cases if len(extractor.cases_for(case)) > 1]

    assert {case.case_id for case in shared} == {"task_020", "plan_002"}
    output = extractor.expected_output(shared[0])
    assert [memory.content for memory in output.memories] == [
        case.expected.memories[0].summary for case in shared
    ]
    assert len({case_request_key(case) for case in shared}) == 1
