"""Small synthetic golden datasets for tests of the evaluation services.

The real dataset holds personal messages and is not part of every checkout. These cases
are invented, and a scripted expense extraction passes the first, fails the second, and
never reaches the third when the extractor's script ends in a provider failure.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from evaluation.golden import GoldenCase
from tests.unit.test_evaluation import make_case


def write_dataset(path: Path, cases: Sequence[GoldenCase]) -> Path:
    path.write_text(
        "".join(json.dumps(case.model_dump(mode="json")) + "\n" for case in cases),
        encoding="utf-8",
    )
    return path


def three_cases() -> list[GoldenCase]:
    return [
        make_case(case_id="pass_1", attributes={"amount": 500, "currency": None}),
        make_case(case_id="abstain_1", outcome="abstain", texts=("14 15",)),
        make_case(case_id="unreached_1", attributes={"amount": 500, "currency": None}),
    ]
