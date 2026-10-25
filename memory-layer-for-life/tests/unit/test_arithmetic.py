"""Arithmetic is computed by the system and never taken from a model."""

import uuid

import pytest

from app.domain.arithmetic import evaluate_arithmetic
from app.domain.enums import MemoryType
from app.domain.errors import InvalidExtractionOutputError
from app.models.raw_message import RawMessage
from app.schemas.extraction import ExtractionOutput
from app.services.processing.extraction import (
    ExtractionStage,
    finalize_extraction,
    reconcile_arithmetic,
)
from evaluation.runner import evaluate_case
from tests.support.extraction import ScriptedExtractor, evidence, extraction, financial, memory
from tests.unit.test_evaluation import ScriptedJudge, expense, make_case, verdict

CORRECTION = "memory 0: amount recomputed from the written calculation"

# --- The evaluator --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("232+104", 336),
        ("245+131+200+135", 711),
        ("400/2", 200),
        ("400 / 2", 200),
        ("3 * 170 + 2*95", 700),
        ("(100 + 50) * 2", 300),
        ("10 - 2 - 3", 5),
        ("100 / 4 / 5", 5),
        ("2 + 3 * 4", 14),
        ("1.5 + 2.25", 3.75),
        ("-5 + 8", 3),
        ("((7))+1", 8),
    ],
)
def test_written_arithmetic_is_evaluated(expression: str, expected: float) -> None:
    assert evaluate_arithmetic(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("500", id="a lone number"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="blank"),
        pytest.param("4x 170", id="shorthand multiplication"),
        pytest.param("12-15 June", id="a date range"),
        pytest.param("232+104 groceries", id="trailing words"),
        pytest.param("400/", id="missing operand"),
        pytest.param("+", id="operator only"),
        pytest.param("(2+3", id="unclosed parenthesis"),
        pytest.param("2+3)", id="unopened parenthesis"),
        pytest.param("2 ++ 3 +", id="dangling operator"),
        pytest.param("10/0", id="division by zero"),
        pytest.param("10/(5-5)", id="division by a computed zero"),
        pytest.param("2**8", id="unsupported operator"),
        pytest.param("1e3+1", id="scientific notation"),
        pytest.param("1,000+5", id="thousands separator"),
        pytest.param("len([1])+1", id="code"),
        pytest.param("1+" * 150 + "1", id="too long"),
        pytest.param("(" * 30 + "1+1" + ")" * 30, id="nested too deeply"),
    ],
)
def test_anything_else_is_not_arithmetic(text: str) -> None:
    assert evaluate_arithmetic(text) is None


# --- Reconciling extractor output -----------------------------------------------------


def sum_note(amount: float | None, calculation: str | None) -> ExtractionOutput:
    return extraction(
        memory(
            "Written sum",
            memory_type=MemoryType.FINANCIAL_NOTE,
            evidence_refs=[evidence(0, "245+131+200+135")],
            financial=financial(
                amount, component_amounts=[245, 131, 200, 135], calculation=calculation
            ),
        )
    )


def stated_amount(output: ExtractionOutput, position: int = 0) -> float | None:
    details = output.memories[position].financial
    assert details is not None
    return details.amount


def test_a_wrong_result_is_replaced_by_the_computed_one() -> None:
    finalized = reconcile_arithmetic(sum_note(611, "245+131+200+135"))

    assert stated_amount(finalized.output) == 711
    assert finalized.output.memories[0].financial.calculation == "245+131+200+135"  # type: ignore[union-attr]
    assert finalized.corrections == (CORRECTION,)


def test_a_correct_result_is_left_alone() -> None:
    output = sum_note(711, "245 + 131 + 200 + 135")

    finalized = reconcile_arithmetic(output)

    assert finalized.output is output
    assert finalized.corrections == ()


def test_results_are_rounded_like_money() -> None:
    assert stated_amount(reconcile_arithmetic(sum_note(33, "100/3")).output) == 33.33


@pytest.mark.parametrize(
    ("amount", "calculation"),
    [
        pytest.param(None, "245+131+200+135", id="no amount was stated"),
        pytest.param(170, None, id="no calculation"),
        pytest.param(170, "4x 170", id="shorthand that is not arithmetic"),
        pytest.param(10, "10/0", id="division by zero"),
    ],
)
def test_nothing_is_invented_when_there_is_nothing_to_recompute(
    amount: float | None, calculation: str | None
) -> None:
    output = sum_note(amount, calculation)

    finalized = reconcile_arithmetic(output)

    assert finalized.output is output
    assert finalized.corrections == ()


def test_only_the_affected_memory_changes() -> None:
    output = extraction(
        memory("First"),
        memory(
            "Second",
            memory_type=MemoryType.FINANCIAL_NOTE,
            financial=financial(1, calculation="2+2"),
        ),
    )

    finalized = reconcile_arithmetic(output)

    assert finalized.output.memories[0] is output.memories[0]
    assert stated_amount(finalized.output, 1) == 4
    assert finalized.corrections == ("memory 1: amount recomputed from the written calculation",)
    # The extractor's own object is not mutated.
    assert stated_amount(output, 1) == 1


def test_finalization_checks_grounding_first() -> None:
    output = extraction(memory(evidence_refs=[evidence(4, "nowhere")]))

    with pytest.raises(InvalidExtractionOutputError):
        finalize_extraction(output, message_count=1)


async def test_stage_returns_the_corrected_output_and_reports_the_correction() -> None:
    extractor = ScriptedExtractor(sum_note(611, "245+131+200+135"))
    stage = ExtractionStage(extractor, timezone_name="UTC")
    message = RawMessage(
        id=uuid.uuid4(), source="api_input", content="245+131+200+135", content_sha256="0" * 64
    )

    result = await stage.run([message])

    assert stated_amount(result.response.output) == 711
    assert result.corrections == (CORRECTION,)
    assert result.response.request_id == "req_test_1"
    assert result.response.model == "test-model"


# --- The evaluation sees what the pipeline would store --------------------------------


async def test_evaluation_scores_the_finalized_output() -> None:
    case = make_case(
        memory_type="expense_calculation",
        attributes={"computed_total": 711, "currency": None},
        texts=("245+131+200+135",),
    )
    miscalculated = expense(
        611, component_amounts=[245, 131, 200, 135], calculation="245+131+200+135"
    )

    result = await evaluate_case(case, ScriptedExtractor(miscalculated), ScriptedJudge(verdict()))

    assert result.score.passed
    assert result.output is not None
    assert stated_amount(result.output) == 711
