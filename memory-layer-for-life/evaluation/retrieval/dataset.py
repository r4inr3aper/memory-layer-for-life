"""The retrieval question set: questions about the golden dataset, with the golden
memories that answer them.

A relevant memory is named by its golden case and its position in that case's expected
memories. Like the golden labels, these are drafts until a person reviews them.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.golden import GoldenCase

DEFAULT_QUERIES_PATH: Final = Path(__file__).resolve().parents[2] / "retrieval_queries.jsonl"


class QueryCategory(StrEnum):
    # The question shares distinctive words with its memories.
    KEYWORD = "keyword"
    # The question is a person's or place's name.
    ENTITY = "entity"
    # The question means the same in other words; only meaning can find it.
    PARAPHRASE = "paraphrase"
    # Some answers share words, some only meaning.
    MIXED = "mixed"
    # Nothing answers it; any result is a false positive.
    NEGATIVE = "negative"


class RelevantMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9_]+$")
    memory_index: int = Field(default=0, ge=0)


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str = Field(pattern=r"^rq_[0-9]{3}$")
    query: str = Field(min_length=1, max_length=500)
    category: QueryCategory
    relevant: tuple[RelevantMemory, ...]
    notes: str = ""
    review_status: str
    annotation_version: str

    @model_validator(mode="after")
    def negatives_have_no_answer(self) -> "RetrievalCase":
        if (self.category is QueryCategory.NEGATIVE) != (not self.relevant):
            raise ValueError("negative questions, and only they, have no relevant memory")
        if len(set(self.relevant)) != len(self.relevant):
            raise ValueError("a relevant memory is listed twice")
        return self


class RetrievalDatasetError(ValueError):
    """The question set is malformed or names memories the golden dataset lacks."""


def load_retrieval_cases(path: Path = DEFAULT_QUERIES_PATH) -> list[RetrievalCase]:
    cases: list[RetrievalCase] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(RetrievalCase.model_validate(json.loads(line)))
        except ValueError as error:
            raise RetrievalDatasetError(f"{path.name}, line {number}: {error}") from error
    ids = [case.query_id for case in cases]
    if len(set(ids)) != len(ids):
        raise RetrievalDatasetError(f"{path.name}: a query_id is used twice")
    return cases


def check_against_golden(cases: Iterable[RetrievalCase], golden: Iterable[GoldenCase]) -> None:
    """Every relevant memory must exist in the golden dataset."""
    expected = {case.case_id: len(case.expected.memories) for case in golden}
    for case in cases:
        for relevant in case.relevant:
            count = expected.get(relevant.case_id)
            if count is None:
                raise RetrievalDatasetError(
                    f"{case.query_id}: golden case {relevant.case_id} does not exist"
                )
            if relevant.memory_index >= count:
                raise RetrievalDatasetError(
                    f"{case.query_id}: {relevant.case_id} has no memory {relevant.memory_index}"
                )


def relevant_summaries(
    case: RetrievalCase, golden_by_id: Mapping[str, GoldenCase]
) -> Sequence[str]:
    """The expected summaries of the case's relevant memories: the stored memories' text,
    since the fixture extractor stores each expected summary as a memory's content."""
    return [
        golden_by_id[relevant.case_id].expected.memories[relevant.memory_index].summary
        for relevant in case.relevant
    ]
