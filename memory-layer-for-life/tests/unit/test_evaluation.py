"""The evaluation harness: scoring, judge plumbing, runner, and report.

The model is replaced by scripted doubles, so the harness itself is tested exactly.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import ExtractionDisposition, MemoryState, MemoryType
from app.domain.errors import (
    ExtractionBillingError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    PermanentExtractionError,
    TransientExtractionError,
)
from app.integrations.extraction.base import ExtractionUsage
from app.schemas.extraction import ExtractionOutput
from evaluation import runner as runner_module
from evaluation.golden import GoldenCase, GoldenExpectedMemory
from evaluation.judge import (
    JUDGE_SYSTEM_PROMPT,
    AnthropicJudge,
    JudgeError,
    JudgeResponse,
    JudgeVerdict,
    RuleVerdict,
    UnsupportedClaim,
    render_judge_request,
)
from evaluation.report import (
    build_report,
    estimate_cost,
    render_markdown,
    total_usage,
    write_report,
)
from evaluation.runner import evaluate_case, run_evaluation
from evaluation.scoring import CheckName, check_structured_fields, score_case
from tests.support.extraction import (
    ScriptedExtractor,
    abstention,
    evidence,
    extraction,
    financial,
    memory,
    temporal,
)

NARROW_NO_BREAK_SPACE = chr(0x202F)


def make_case(
    *,
    case_id: str = "case_1",
    outcome: str = "extract",
    memory_type: str = "expense_note",
    status: str = "candidate",
    attributes: dict[str, Any] | None = None,
    must_not: tuple[str, ...] = ("Assume a currency",),
    texts: tuple[str, ...] = ("500 petrol",),
) -> GoldenCase:
    memories = (
        []
        if outcome == "abstain"
        else [{"type": memory_type, "summary": "Petrol expense note", "status": status}]
    )
    if memories and attributes:
        memories[0].update(attributes)
    return GoldenCase.model_validate(
        {
            "case_id": case_id,
            "source_event_ids": [f"evt-{index}" for index in range(len(texts))],
            "input": {
                "messages": [
                    {
                        "event_id": f"evt-{index}",
                        "source_line": index + 1,
                        "timestamp_local": f"14/03/26 12:53{NARROW_NO_BREAK_SPACE}pm",
                        "text": text,
                    }
                    for index, text in enumerate(texts)
                ]
            },
            "expected": {"outcome": outcome, "memories": memories, "rationale": "Because."},
            "must_not": list(must_not),
            "tags": ["test"],
            "review_status": "draft_needs_human_review",
        }
    )


_FIRST_COVERING = object()


def verdict(
    *,
    covering: tuple[int, ...] = (0,),
    primary: Any = _FIRST_COVERING,
    coverage: str = "covered",
    violated: tuple[int, ...] = (),
    rules: int = 1,
    unsupported: tuple[str, ...] = (),
) -> JudgeVerdict:
    if primary is _FIRST_COVERING:
        primary = covering[0] if covering else None
    return JudgeVerdict(
        covering_memory_indexes=list(covering),
        primary_memory_index=primary,
        coverage=coverage,  # type: ignore[arg-type]
        coverage_explanation=f"The reference is {coverage}.",
        rule_verdicts=[
            RuleVerdict(rule_index=index, violated=index in violated, explanation="Checked.")
            for index in range(rules)
        ],
        unsupported_claims=[UnsupportedClaim(memory_index=0, claim=claim) for claim in unsupported],
    )


def expense(amount: float | None = 500, **kwargs: Any) -> ExtractionOutput:
    return extraction(
        memory(
            "Petrol expense of 500",
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            evidence_refs=[evidence(0, "500 petrol")],
            financial=financial(amount, **kwargs),
        )
    )


def failed(score: Any) -> set[CheckName]:
    return {check.name for check in score.failed_checks}


# --- Scoring --------------------------------------------------------------------------


def test_a_faithful_extraction_passes_every_check() -> None:
    case = make_case(attributes={"amount": 500, "currency": None})

    score = score_case(case, expense(), [verdict()])

    assert score.passed
    assert [check.name for check in score.checks] == list(CheckName)
    assert score.disposition_agrees is True
    assert score.state_agrees is True


def test_failed_extraction_fails_the_case() -> None:
    score = score_case(make_case(), None, error="EXTRACTION_REFUSED: declined")

    assert not score.passed
    assert failed(score) == {CheckName.VALID_OUTPUT}
    assert score.failed_checks[0].detail == "EXTRACTION_REFUSED: declined"


def test_correct_abstention_passes_without_a_judge() -> None:
    score = score_case(make_case(outcome="abstain", texts=("14 15",)), abstention())

    assert score.passed
    assert [check.name for check in score.checks] == [CheckName.VALID_OUTPUT, CheckName.ABSTENTION]
    assert score.disposition_agrees is True


def test_a_memory_where_abstention_was_expected_fails() -> None:
    score = score_case(make_case(outcome="abstain", texts=("14 15",)), expense(), [verdict()])

    assert failed(score) == {CheckName.ABSTENTION}
    assert "abstention was expected" in score.failed_checks[0].detail
    assert score.disposition_agrees is False


def test_abstaining_where_a_memory_was_expected_fails() -> None:
    score = score_case(make_case(), abstention())

    assert failed(score) == {CheckName.ABSTENTION}
    assert "abstained although a memory was expected" in score.failed_checks[0].detail


def test_a_missing_judge_verdict_fails_coverage() -> None:
    score = score_case(make_case(), expense(), None, error="Judge call failed")

    assert failed(score) == {CheckName.COVERAGE}
    assert score.failed_checks[0].detail == "Judge call failed"


@pytest.mark.parametrize("coverage", ["partial", "missing"])
def test_incomplete_coverage_fails(coverage: str) -> None:
    score = score_case(make_case(), expense(), [verdict(coverage=coverage)])

    assert CheckName.COVERAGE in failed(score)


def test_coverage_needs_a_named_existing_memory() -> None:
    nothing_named = score_case(make_case(), expense(), [verdict(covering=())])
    out_of_range = score_case(make_case(), expense(), [verdict(covering=(4,))])

    assert CheckName.COVERAGE in failed(nothing_named)
    assert CheckName.COVERAGE in failed(out_of_range)
    assert "do not exist" in out_of_range.checks[2].detail


def test_wrong_memory_type_fails() -> None:
    output = extraction(memory("Buy petrol for 500", memory_type=MemoryType.TASK))

    score = score_case(make_case(), output, [verdict()])

    assert failed(score) == {CheckName.MEMORY_TYPE}
    assert "task" in score.failed_checks[0].detail


def test_only_the_primary_memory_is_type_checked() -> None:
    """A note recorded as several memories may have parts of other types."""
    output = extraction(
        memory("Which role could I move to?", memory_type=MemoryType.OPEN_LOOP),
        memory("Works with Python", memory_type=MemoryType.SEMANTIC_FACT),
    )
    case = make_case(memory_type="career_question", status="open", must_not=("Invent a job",))

    both_convey_it = score_case(case, output, [verdict(covering=(0, 1), primary=0)])
    wrong_primary = score_case(case, output, [verdict(covering=(0, 1), primary=1)])

    assert both_convey_it.passed
    assert failed(wrong_primary) == {CheckName.MEMORY_TYPE}


def test_a_missing_or_impossible_primary_memory_fails_the_type_check() -> None:
    none_named = score_case(make_case(), expense(), [verdict(primary=None)])
    out_of_range = score_case(make_case(), expense(), [verdict(primary=9)])

    assert CheckName.MEMORY_TYPE in failed(none_named)
    assert CheckName.MEMORY_TYPE in failed(out_of_range)


def test_memories_that_do_not_convey_the_reference_are_ignored() -> None:
    """An extra memory of another type is fine if it is not what conveys the reference."""
    output = extraction(
        memory("Reminder to fill the tank", memory_type=MemoryType.TASK),
        memory(
            "Petrol expense of 500",
            memory_type=MemoryType.FINANCIAL_NOTE,
            state=MemoryState.NOT_APPLICABLE,
            financial=financial(500),
        ),
    )

    score = score_case(make_case(attributes={"amount": 500}), output, [verdict(covering=(1,))])

    assert score.passed


def test_an_invented_completion_fails() -> None:
    case = make_case(memory_type="task", status="open", must_not=("Mark completed",))
    output = extraction(memory("Bought almonds", state=MemoryState.DONE))

    score = score_case(case, output, [verdict()])

    assert failed(score) == {CheckName.NO_INVENTED_COMPLETION}
    assert score.state_agrees is False


def test_done_is_allowed_for_something_observed() -> None:
    case = make_case(memory_type="technical_note", status="observed")
    output = extraction(
        memory("Added the prompt to messages", memory_type=MemoryType.NOTE, state=MemoryState.DONE)
    )

    assert score_case(case, output, [verdict()]).passed


def test_a_broken_rule_fails() -> None:
    case = make_case(must_not=("Assume a currency", "Invent a date"))

    score = score_case(case, expense(), [verdict(rules=2, violated=(1,))])

    assert failed(score) == {CheckName.MUST_NOT}
    assert "Invent a date" in score.failed_checks[0].detail


def test_every_rule_must_be_judged() -> None:
    case = make_case(must_not=("Assume a currency", "Invent a date"))

    score = score_case(case, expense(), [verdict(rules=1)])

    assert failed(score) == {CheckName.MUST_NOT}
    assert "rule 1 was not judged" in score.failed_checks[0].detail


def test_an_unsupported_claim_fails() -> None:
    score = score_case(make_case(), expense(), [verdict(unsupported=("paid in cash",))])

    assert failed(score) == {CheckName.GROUNDED}
    assert "paid in cash" in score.failed_checks[0].detail


def test_disposition_mismatch_is_reported_but_does_not_fail() -> None:
    case = make_case(outcome="context")

    score = score_case(case, expense(), [verdict()])

    assert score.passed
    assert score.disposition_agrees is False


# --- Structured fields ----------------------------------------------------------------


def label(**attributes: Any) -> GoldenExpectedMemory:
    return GoldenExpectedMemory.model_validate(
        {"type": "expense_note", "summary": "s", "status": "candidate", **attributes}
    )


def test_label_attributes_are_separated_from_the_core_fields() -> None:
    expected = label(amount=500, currency=None)

    assert expected.attributes == {"amount": 500, "currency": None}
    assert expected.has("currency") is True
    assert expected.has("category") is False


def test_matching_amount_and_absent_currency_pass() -> None:
    result = check_structured_fields(label(amount=336, currency=None), expense(336).memories)

    assert result.passed
    assert result.detail == "checked currency, amount"


def test_an_invented_currency_fails() -> None:
    result = check_structured_fields(label(currency=None), expense(currency="INR").memories)

    assert not result.passed
    assert "INR" in result.detail


def test_an_expected_currency_must_be_stated() -> None:
    assert check_structured_fields(label(currency="INR"), expense(currency="INR").memories).passed
    assert not check_structured_fields(label(currency="INR"), expense().memories).passed


def test_a_wrong_or_missing_amount_fails() -> None:
    assert not check_structured_fields(label(amount=336), expense(232).memories).passed
    assert not check_structured_fields(label(amount=336), expense(None).memories).passed
    assert not check_structured_fields(label(amount=336), extraction().memories).passed


def test_a_computed_total_is_compared_with_the_amount() -> None:
    memories = expense(711, component_amounts=[245, 131, 200, 135]).memories

    assert check_structured_fields(label(computed_total=711), memories).passed
    assert not check_structured_fields(label(computed_total=700), memories).passed


def test_listed_amounts_must_all_be_recorded() -> None:
    memories = expense(None, component_amounts=[3275, 2375, 170]).memories

    assert check_structured_fields(label(amounts=[3275, 2375]), memories).passed
    failing = check_structured_fields(label(amounts=[3275, 999]), memories)
    assert not failing.passed
    assert "999" in failing.detail


def test_an_unknown_year_forbids_a_resolved_date() -> None:
    resolved = extraction(
        memory("Gym expires", temporal=temporal("Jan 14", datetime(2027, 1, 14).date()))
    ).memories
    unresolved = extraction(memory("Gym expires", temporal=temporal("Jan 14"))).memories

    assert not check_structured_fields(label(year=None), resolved).passed
    assert check_structured_fields(label(year=None), unresolved).passed


def test_a_label_without_checked_fields_passes() -> None:
    result = check_structured_fields(label(category="food"), extraction().memories)

    assert result.passed
    assert result.detail == "the label states no checked field"


# --- Judge ----------------------------------------------------------------------------


def test_judge_request_holds_everything_needed() -> None:
    case = make_case(attributes={"amount": 500}, texts=("500 petrol", "for the bike"))
    (expected,) = case.expected.memories

    rendered = render_judge_request(case, expected, expense())

    _, _, document = rendered.partition("\n\n")
    data = json.loads(document)
    assert [item["text"] for item in data["source_messages"]] == ["500 petrol", "for the bike"]
    assert data["source_messages"][0]["weekday"] == "Saturday"
    assert data["produced_memories"][0]["financial"]["amount"] == 500
    assert data["reference_memory"]["summary"] == "Petrol expense note"
    assert data["reference_memory"]["attributes"] == {"amount": 500}
    assert data["rules_the_system_must_not_break"] == [{"index": 0, "rule": "Assume a currency"}]


def judge_with(response: Any) -> tuple[AnthropicJudge, AsyncMock]:
    create = (
        AsyncMock(side_effect=response)
        if isinstance(response, Exception)
        else AsyncMock(return_value=response)
    )
    client = MagicMock()
    client.messages.create = create
    return AnthropicJudge(client, model="claude-haiku-5-5"), create


def judge_api_response(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-haiku-5-5",
        _request_id="req_judge_1",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(
            input_tokens=900,
            output_tokens=200,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=700,
        ),
    )


async def test_judge_returns_a_validated_verdict() -> None:
    case = make_case()
    judge, create = judge_with(judge_api_response(verdict().model_dump_json()))

    response = await judge.judge(case, case.expected.memories[0], expense())

    assert response.verdict == verdict()
    assert response.usage == ExtractionUsage(900, 200, 0, 700)
    kwargs = create.await_args.kwargs
    assert kwargs["system"][0]["text"] == JUDGE_SYSTEM_PROMPT
    assert kwargs["output_config"]["effort"] == "high"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert judge.model == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("response", "retryable"),
    [
        pytest.param(judge_api_response("not json"), True, id="invalid verdict"),
        pytest.param(judge_api_response("{}", stop_reason="refusal"), False, id="refusal"),
        pytest.param(judge_api_response("{", stop_reason="max_tokens"), False, id="truncated"),
    ],
)
async def test_judge_reports_unusable_answers(response: Any, retryable: bool) -> None:
    case = make_case()
    judge, _ = judge_with(response)

    with pytest.raises(JudgeError) as raised:
        await judge.judge(case, case.expected.memories[0], expense())

    assert raised.value.retryable is retryable


# --- Runner ---------------------------------------------------------------------------


class ScriptedJudge:
    def __init__(self, *script: JudgeVerdict | Exception) -> None:
        self._script = list(script)
        self.calls = 0

    @property
    def model(self) -> str:
        return "scripted-judge"

    async def judge(
        self, case: GoldenCase, expected: GoldenExpectedMemory, output: ExtractionOutput
    ) -> JudgeResponse:
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return JudgeResponse(verdict=item, usage=ExtractionUsage(900, 200))


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, "_RETRY_DELAYS_SECONDS", (0.0, 0.0))


async def test_a_passing_case_is_extracted_then_judged() -> None:
    case = make_case(attributes={"amount": 500, "currency": None})
    extractor, judge = ScriptedExtractor(expense()), ScriptedJudge(verdict())

    result = await evaluate_case(case, extractor, judge)

    assert result.score.passed
    assert result.output == expense()
    assert result.verdicts == (verdict(),)
    assert (extractor.call_count, judge.calls) == (1, 1)
    # The extractor saw the case's message with its local timestamp.
    (request,) = extractor.requests
    assert request.messages[0].text == "500 petrol"
    assert request.messages[0].sent_at_local == datetime(2026, 3, 14, 12, 53)


async def test_abstention_cases_are_not_sent_to_the_judge() -> None:
    case = make_case(outcome="abstain", texts=("14 15",))
    judge = ScriptedJudge(verdict())

    correct = await evaluate_case(case, ScriptedExtractor(abstention()), judge)
    wrong = await evaluate_case(case, ScriptedExtractor(expense()), judge)

    assert correct.score.passed
    assert not wrong.score.passed
    assert judge.calls == 0


async def test_transient_failures_are_retried() -> None:
    extractor = ScriptedExtractor(TransientExtractionError("busy"), expense())
    judge = ScriptedJudge(JudgeError("busy", retryable=True), verdict())

    result = await evaluate_case(make_case(), extractor, judge)

    assert result.score.passed
    assert (extractor.call_count, judge.calls) == (2, 2)


async def test_a_provider_failure_leaves_the_case_unevaluated() -> None:
    extractor = ScriptedExtractor(PermanentExtractionError("rejected"))

    result = await evaluate_case(make_case(), extractor, ScriptedJudge(verdict()))

    # The provider said nothing about quality, so the case neither passes nor fails.
    assert result.evaluated is False
    assert result.score.checks == ()
    assert not result.score.passed
    assert result.output is None
    assert result.error == "EXTRACTION_PERMANENT_FAILURE: rejected"
    assert extractor.call_count == 1


async def test_output_pointing_outside_the_case_fails_as_invalid() -> None:
    output = extraction(memory(evidence_refs=[evidence(5, "nowhere")]))

    result = await evaluate_case(make_case(), ScriptedExtractor(output), ScriptedJudge(verdict()))

    assert failed(result.score) == {CheckName.VALID_OUTPUT}
    assert "EXTRACTION_OUTPUT_INVALID" in (result.error or "")


async def test_a_judge_that_keeps_failing_leaves_the_case_unevaluated() -> None:
    judge = ScriptedJudge(JudgeError("down", retryable=True))

    result = await evaluate_case(make_case(), ScriptedExtractor(expense()), judge)

    assert result.evaluated is False
    assert result.error == "down"
    # The extraction is kept, so the report can still show it.
    assert result.output == expense()
    assert judge.calls == 3


async def test_a_provider_that_stays_unreachable_leaves_the_case_unevaluated() -> None:
    extractor = ScriptedExtractor(TransientExtractionError("busy"))

    result = await evaluate_case(make_case(), extractor, ScriptedJudge(verdict()))

    assert result.evaluated is False
    assert extractor.call_count == 3


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ExtractionRefusedError("declined"), id="refusal"),
        pytest.param(ExtractionTruncatedError("cut off"), id="truncated"),
    ],
)
async def test_an_unusable_model_answer_fails_the_case(error: Exception) -> None:
    result = await evaluate_case(make_case(), ScriptedExtractor(error), ScriptedJudge(verdict()))

    # The model answered and the answer could not be used: that is a quality result.
    assert result.evaluated is True
    assert failed(result.score) == {CheckName.VALID_OUTPUT}


async def test_run_keeps_dataset_order_and_counts_results() -> None:
    cases = [
        make_case(case_id="pass_1"),
        make_case(case_id="abstain_1", outcome="abstain", texts=("14 15",)),
        make_case(case_id="fail_1", memory_type="task", status="open"),
    ]
    extractor = ScriptedExtractor(expense())

    run = await run_evaluation(cases, extractor, ScriptedJudge(verdict()), concurrency=1)

    assert [result.case.case_id for result in run.results] == ["pass_1", "abstain_1", "fail_1"]
    assert [result.case.case_id for result in run.passed] == ["pass_1"]
    assert [result.case.case_id for result in run.failed] == ["abstain_1", "fail_1"]
    assert run.all_passed is False
    assert run.judge_model == "scripted-judge"
    assert run.extractor_version == "scripted:1"


# --- Report ---------------------------------------------------------------------------


def test_usage_is_summed_and_priced() -> None:
    usage = total_usage(
        [ExtractionUsage(1_000_000, 200_000, 500_000, 100_000), None, ExtractionUsage(0, 800_000)]
    )

    assert usage == ExtractionUsage(1_000_000, 1_000_000, 500_000, 100_000)
    # input 1M + cache write 0.1M * 1.25 + cache read 0.5M * 0.1 = 1.175M at $0.10,
    # output 1M at $0.50.
    assert estimate_cost(usage, "claude-haiku-5-5") == pytest.approx(0.6175)
    assert estimate_cost(usage, "unknown-model") is None
    assert estimate_cost(usage, None) is None


async def test_report_summarizes_checks_failures_and_disagreements(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cases = [
        make_case(case_id="pass_1", attributes={"currency": None}),
        make_case(case_id="context_1", outcome="context"),
        make_case(case_id="fail_1", memory_type="task", status="open"),
    ]
    run = await run_evaluation(
        cases, ScriptedExtractor(expense()), ScriptedJudge(verdict()), concurrency=2
    )
    generated_at = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

    report = build_report(run, generated_at=generated_at)

    assert report["summary"] == {
        "cases": 3,
        "evaluated": 3,
        "passed": 2,
        "failed": 1,
        "not_evaluated": 0,
        "complete": True,
        "all_passed": False,
        "failed_case_ids": ["fail_1"],
        "not_evaluated_case_ids": [],
        "not_evaluated_reasons": {},
    }
    assert report["checks"]["memory_type"] == {"evaluated": 3, "passed": 2}
    assert report["checks"]["valid_output"] == {"evaluated": 3, "passed": 3}
    assert report["dataset"]["review_status"] == {"draft_needs_human_review": 3}
    disposition = report["reported_not_gating"]["disposition"]
    assert (disposition["compared"], disposition["agree"]) == (3, 2)
    assert disposition["disagreements"] == [
        {"case_id": "context_1", "expected": "context", "produced": "extract"}
    ]
    assert report["usage"]["judge"]["input_tokens"] == 2700
    assert report["usage"]["extraction"]["estimated_cost_usd"] is None  # unpriced test model

    markdown = render_markdown(report)
    assert "**2 of 3 cases pass.**" in markdown
    assert "### fail_1" in markdown
    assert "FAILED memory_type" in markdown
    assert "| context_1 | context | extract |" in markdown
    assert "not verified ground truth" in markdown

    directory = write_report(run, tmp_path / "run", generated_at=generated_at)
    assert (
        json.loads((directory / "report.json").read_text(encoding="utf-8"))["summary"]
        == (report["summary"])
    )
    assert (directory / "report.md").read_text(encoding="utf-8") == markdown


async def test_report_of_a_clean_run_lists_no_failures() -> None:
    run = await run_evaluation(
        [make_case()], ScriptedExtractor(expense()), ScriptedJudge(verdict()), concurrency=1
    )

    report = build_report(run, generated_at=datetime(2026, 10, 12, tzinfo=UTC))

    assert report["summary"]["all_passed"] is True
    assert "## Failing cases (0)\n\nNone." in render_markdown(report)
    assert run.all_passed is True


async def test_an_incomplete_run_is_never_a_pass_and_says_so() -> None:
    cases = [make_case(case_id="pass_1"), make_case(case_id="unreached_1")]
    extractor = ScriptedExtractor(expense(), ExtractionBillingError("no credit"))

    run = await run_evaluation(cases, extractor, ScriptedJudge(verdict()), concurrency=1)

    assert (run.complete, run.all_passed) == (False, False)
    assert [result.case.case_id for result in run.passed] == ["pass_1"]
    assert run.failed == ()
    assert [result.case.case_id for result in run.not_evaluated] == ["unreached_1"]

    report = build_report(run, generated_at=datetime(2026, 10, 12, tzinfo=UTC))

    reason = "EXTRACTION_PROVIDER_BILLING: no credit"
    assert report["summary"] == {
        "cases": 2,
        "evaluated": 1,
        "passed": 1,
        "failed": 0,
        "not_evaluated": 1,
        "complete": False,
        "all_passed": False,
        "failed_case_ids": [],
        "not_evaluated_case_ids": ["unreached_1"],
        "not_evaluated_reasons": {reason: 1},
    }
    # Checks are counted over evaluated cases only.
    assert report["checks"]["valid_output"] == {"evaluated": 1, "passed": 1}
    assert [case["evaluated"] for case in report["cases"]] == [True, False]

    markdown = render_markdown(report)
    assert "**Incomplete run: 1 of 2 cases could not be evaluated.**" in markdown
    assert f"| {reason} | 1 |" in markdown
    assert "Not evaluated: unreached_1" in markdown
    assert "**1 of 1 evaluated cases pass.**" in markdown
    assert "## Failing cases (0)\n\nNone." in markdown


def test_extraction_disposition_enum_is_used_for_outcomes() -> None:
    assert make_case(outcome="context").expected.outcome is ExtractionDisposition.CONTEXT
