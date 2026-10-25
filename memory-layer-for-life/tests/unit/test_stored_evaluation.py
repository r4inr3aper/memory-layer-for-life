"""Reading evaluation results into their stored form, from live runs and from report files."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.domain.enums import EvaluationCaseOutcome, ExtractionDisposition
from evaluation.report import build_report, case_document
from evaluation.runner import CaseResult, EvaluationRun
from evaluation.scoring import score_case
from evaluation.stored import (
    ReportFormatError,
    priced_usage,
    read_report,
    stored_case,
    summarize_cases,
)
from tests.support.extraction import abstention
from tests.unit.test_evaluation import expense, make_case, verdict


def passed_document() -> dict[str, Any]:
    case = make_case(case_id="pass_1", attributes={"amount": 500, "currency": None})
    output = expense()
    result = CaseResult(
        case, score_case(case, output, [verdict()]), output=output, verdicts=(verdict(),)
    )
    return case_document(result)


def failed_document() -> dict[str, Any]:
    case = make_case(case_id="fail_1", outcome="abstain", texts=("14 15",))
    output = expense()
    return case_document(CaseResult(case, score_case(case, output), output=output))


def unevaluated_document() -> dict[str, Any]:
    case = make_case(case_id="unreached_1")
    error = "EXTRACTION_PROVIDER_BILLING: no credit"
    return case_document(
        CaseResult(case, score_case(case, None, error=error), error=error, evaluated=False)
    )


# --- One case ---------------------------------------------------------------------------


def test_a_passed_case_keeps_its_document_and_states_its_outcome() -> None:
    document = passed_document()

    stored = stored_case(document)

    assert stored.case_id == "pass_1"
    assert stored.outcome is EvaluationCaseOutcome.PASSED
    assert stored.expected_outcome is ExtractionDisposition.EXTRACT
    assert stored.produced_disposition is ExtractionDisposition.EXTRACT
    assert stored.failed_checks == ()
    assert stored.error is None
    assert stored.document["messages"] == document["messages"]
    assert stored.document["checks"] == document["checks"]
    assert stored.document["evaluated"] is True
    assert stored.document["passed"] is True


def test_a_failed_case_lists_the_checks_it_failed() -> None:
    stored = stored_case(failed_document())

    assert stored.outcome is EvaluationCaseOutcome.FAILED
    assert stored.failed_checks == ("abstention",)
    assert stored.expected_outcome is ExtractionDisposition.ABSTAIN


def test_an_unevaluated_case_is_neither_passed_nor_failed() -> None:
    stored = stored_case(unevaluated_document())

    assert stored.outcome is EvaluationCaseOutcome.NOT_EVALUATED
    assert stored.failed_checks == ()
    assert stored.produced_disposition is None
    assert stored.error == "EXTRACTION_PROVIDER_BILLING: no credit"
    assert stored.document["passed"] is False


@pytest.mark.parametrize(
    ("error", "produced", "expected_outcome"),
    [
        pytest.param(
            "EXTRACTION_PERMANENT_FAILURE: The Anthropic API rejected the request (HTTP 400).",
            False,
            EvaluationCaseOutcome.NOT_EVALUATED,
            id="provider rejected the call",
        ),
        pytest.param(
            "EXTRACTION_TRANSIENT_FAILURE: timed out",
            False,
            EvaluationCaseOutcome.NOT_EVALUATED,
            id="provider unreachable",
        ),
        pytest.param(
            "EXTRACTION_REFUSED: declined",
            False,
            EvaluationCaseOutcome.FAILED,
            id="model declined",
        ),
        pytest.param(
            "EXTRACTION_OUTPUT_INVALID: 1 validation error(s)",
            False,
            EvaluationCaseOutcome.FAILED,
            id="model answered badly",
        ),
        pytest.param(
            "Judge call failed with HTTP 400",
            True,
            EvaluationCaseOutcome.NOT_EVALUATED,
            id="judge never answered",
        ),
    ],
)
def test_old_report_files_without_an_evaluated_flag_are_read_by_their_error(
    error: str, produced: bool, expected_outcome: EvaluationCaseOutcome
) -> None:
    """Reports written before the flag existed counted every such case as failed."""
    document = passed_document() if produced else failed_document()
    document.pop("evaluated")
    document["passed"] = False
    document["error"] = error
    if not produced:
        document["produced"] = None
        document["checks"] = [{"name": "valid_output", "passed": False, "detail": error}]

    stored = stored_case(document)

    assert stored.outcome is expected_outcome
    assert stored.error == error


def test_a_malformed_case_document_is_refused() -> None:
    with pytest.raises(ReportFormatError):
        stored_case({"case_id": "x"})


# --- Totals ---------------------------------------------------------------------------


def test_totals_count_outcomes_and_only_evaluated_checks() -> None:
    cases = [
        stored_case(passed_document()),
        stored_case(failed_document()),
        stored_case(unevaluated_document()),
    ]

    totals = summarize_cases(cases)

    assert (totals.total, totals.passed, totals.failed, totals.not_evaluated) == (3, 1, 1, 1)
    # The unevaluated case contributes to no check.
    assert totals.check_totals["valid_output"] == {"evaluated": 2, "passed": 2}
    assert totals.check_totals["abstention"] == {"evaluated": 2, "passed": 1}
    assert totals.check_totals["grounded"] == {"evaluated": 1, "passed": 1}


# --- Usage ----------------------------------------------------------------------------


def test_usage_is_repriced_from_its_token_counts() -> None:
    """A cost written into an old report is ignored; today's price table decides."""
    usage = {
        "extraction": {
            "model": "claude-sonnet-5-5",
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_input_tokens": 1_000_000,
            "cache_creation_input_tokens": 0,
            "estimated_cost_usd": 99.0,
        },
        "judge": {
            "model": "claude-sonnet-5-5",
            "input_tokens": 0,
            "output_tokens": 100_000,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "estimated_cost_usd": None,
        },
    }

    priced, total = priced_usage(usage)

    assert priced["extraction"]["estimated_cost_usd"] == pytest.approx(2.1)
    assert priced["judge"]["estimated_cost_usd"] == pytest.approx(1.0)
    assert total == Decimal("3.100000")


def test_a_role_with_an_unpriced_model_leaves_the_total_unknown() -> None:
    usage = {
        "extraction": {"model": "some-other-model", "input_tokens": 10, "output_tokens": 5},
        "judge": {"model": "claude-haiku-5-5", "input_tokens": 10, "output_tokens": 5},
    }

    priced, total = priced_usage(usage)

    assert priced["extraction"]["estimated_cost_usd"] is None
    assert priced["judge"]["estimated_cost_usd"] is not None
    assert total is None


def test_an_unpriced_role_that_made_no_calls_does_not_hide_the_total() -> None:
    usage = {
        "extraction": {"model": "claude-haiku-5-5", "input_tokens": 1_000_000},
        "judge": {"model": None, "input_tokens": 0, "output_tokens": 0},
    }

    _, total = priced_usage(usage)

    assert total == Decimal("0.100000")


# --- Whole reports --------------------------------------------------------------------


def test_a_report_file_is_read_into_the_stored_form() -> None:
    case = make_case(case_id="pass_1", attributes={"amount": 500, "currency": None})
    abstain_case = make_case(case_id="abstain_1", outcome="abstain", texts=("14 15",))
    run = EvaluationRun(
        results=(
            CaseResult(
                case,
                score_case(case, expense(), [verdict()]),
                output=expense(),
                verdicts=(verdict(),),
            ),
            CaseResult(abstain_case, score_case(abstain_case, abstention()), output=abstention()),
        ),
        extractor_model="claude-sonnet-5-5",
        extractor_version="anthropic:1",
        judge_model="claude-sonnet-5-5",
    )
    generated_at = datetime(2026, 10, 11, 19, 29, 20, tzinfo=UTC)

    stored = read_report(build_report(run, generated_at=generated_at))

    assert stored.generated_at == generated_at
    assert (stored.extractor_model, stored.extractor_version) == (
        "claude-sonnet-5-5",
        "anthropic:1",
    )
    assert stored.judge_model == "claude-sonnet-5-5"
    assert [case.case_id for case in stored.cases] == ["pass_1", "abstain_1"]
    assert (stored.totals.total, stored.totals.passed, stored.totals.failed) == (2, 2, 0)
    assert stored.not_gating["disposition"]["compared"] == 2
    assert stored.usage["extraction"]["model"] == "claude-sonnet-5-5"
    assert stored.estimated_cost_usd == Decimal(0)


def test_a_report_without_a_timezone_or_without_cases_is_refused() -> None:
    with pytest.raises(ReportFormatError):
        read_report({"generated_at": "2026-10-11T19:29:20", "extractor": {"version": "v"}})
    with pytest.raises(ReportFormatError):
        read_report({"summary": {}})
