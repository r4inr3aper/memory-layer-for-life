"""Access to the golden dataset for tests, and an ideal judge verdict."""

from functools import cache

import pytest

from app.schemas.extraction import ExtractionOutput
from evaluation.fixture_extractor import GoldenFixtureExtractor
from evaluation.golden import DEFAULT_DATASET_PATH, GoldenCase, load_golden_cases
from evaluation.judge import JudgeVerdict, RuleVerdict


@cache
def golden_cases() -> tuple[GoldenCase, ...]:
    """The dataset, or an empty tuple when the file is not present.

    The dataset holds personal messages and is not part of every checkout. Tests that
    need it are skipped with a clear reason instead of failing.
    """
    if not DEFAULT_DATASET_PATH.exists():
        return ()
    return tuple(load_golden_cases(DEFAULT_DATASET_PATH))


def require_golden_cases() -> tuple[GoldenCase, ...]:
    cases = golden_cases()
    if not cases:
        pytest.skip(f"golden dataset not found at {DEFAULT_DATASET_PATH}")
    return cases


def golden_case_params() -> list[object]:
    """Parameters for ``pytest.mark.parametrize``, one per case, named by case id."""
    cases = golden_cases()
    if not cases:
        return [pytest.param(None, id="dataset-missing", marks=pytest.mark.skip("no dataset"))]
    return [pytest.param(case, id=case.case_id) for case in cases]


def ideal_verdicts(
    case: GoldenCase, output: ExtractionOutput, extractor: GoldenFixtureExtractor
) -> list[JudgeVerdict]:
    """What a perfect judge says about the fixture extractor's output for a case.

    The fixture output lists the expected memories of all cases that share the input, in
    dataset order, so the memories of this case start after those of the earlier ones.
    """
    offset = 0
    for other in extractor.cases_for(case):
        if other.case_id == case.case_id:
            break
        offset += len(other.expected.memories)
    assert offset + len(case.expected.memories) <= len(output.memories)

    return [
        JudgeVerdict(
            covering_memory_indexes=[offset + position],
            primary_memory_index=offset + position,
            coverage="covered",
            coverage_explanation="The produced memory is the reference summary.",
            rule_verdicts=[
                RuleVerdict(rule_index=index, violated=False, explanation="Not broken.")
                for index in range(len(case.must_not))
            ],
            unsupported_claims=[],
        )
        for position in range(len(case.expected.memories))
    ]
