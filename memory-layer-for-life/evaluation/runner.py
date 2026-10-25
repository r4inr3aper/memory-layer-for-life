"""Live evaluation: run every golden case through an extractor and score the result."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace

from app.domain.enums import ExtractionDisposition
from app.domain.errors import (
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    InvalidExtractionOutputError,
)
from app.integrations.extraction.base import ExtractionUsage, Extractor
from app.integrations.llm_calls import LlmCallContext
from app.schemas.extraction import ExtractionOutput
from app.services.processing.extraction import finalize_extraction
from evaluation.golden import GoldenCase, to_extraction_request
from evaluation.judge import Judge, JudgeError, JudgeVerdict
from evaluation.scoring import CaseScore, score_case

_RETRY_DELAYS_SECONDS = (2.0, 8.0)

# Extraction failures that say something about the model: it answered, and the answer
# could not be used. Any other extraction failure comes from the provider or the network
# and says nothing about quality.
_MODEL_FAULTS = (InvalidExtractionOutputError, ExtractionRefusedError, ExtractionTruncatedError)


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Outcome of one case.

    ``evaluated`` is false when the case could not be scored at all, because the provider
    could not be reached or the judge gave no usable verdict. Such a case neither passes
    nor fails, and ``error`` says why.
    """

    case: GoldenCase
    score: CaseScore
    output: ExtractionOutput | None = None
    verdicts: tuple[JudgeVerdict, ...] = ()
    extraction_usage: ExtractionUsage | None = None
    judge_usage: tuple[ExtractionUsage, ...] = ()
    error: str | None = None
    evaluated: bool = True


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    results: tuple[CaseResult, ...]
    extractor_model: str | None
    extractor_version: str
    judge_model: str | None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def evaluated(self) -> tuple[CaseResult, ...]:
        return tuple(result for result in self.results if result.evaluated)

    @property
    def not_evaluated(self) -> tuple[CaseResult, ...]:
        return tuple(result for result in self.results if not result.evaluated)

    @property
    def passed(self) -> tuple[CaseResult, ...]:
        return tuple(result for result in self.evaluated if result.score.passed)

    @property
    def failed(self) -> tuple[CaseResult, ...]:
        return tuple(result for result in self.evaluated if not result.score.passed)

    @property
    def complete(self) -> bool:
        """Whether every case was scored."""
        return not self.not_evaluated

    @property
    def all_passed(self) -> bool:
        """Every case was scored and passed. An incomplete run is never a pass."""
        return bool(self.results) and self.complete and not self.failed


@dataclass(frozen=True, slots=True)
class _Extraction:
    output: ExtractionOutput | None = None
    usage: ExtractionUsage | None = None
    error: str | None = None
    model_fault: bool = False


# Called with a case's position in the run and its result, as soon as it is known.
OnResult = Callable[[int, CaseResult], Awaitable[None]]


def _unscored(case: GoldenCase) -> CaseScore:
    """The score of a case that could not be evaluated: it carries no checks."""
    return CaseScore(case.case_id, ())


async def _extract(
    case: GoldenCase, extractor: Extractor, call_context: LlmCallContext | None
) -> _Extraction:
    """Call the extractor, retrying only failures that a retry can fix."""
    request = to_extraction_request(
        case,
        call_context=(
            replace(call_context, evaluation_case_id=case.case_id)
            if call_context is not None
            else None
        ),
    )
    for delay in (*_RETRY_DELAYS_SECONDS, None):
        try:
            response = await extractor.extract(request)
            # The same finalization the pipeline applies before it stores an extraction.
            finalized = finalize_extraction(response.output, message_count=len(request.messages))
            return _Extraction(output=finalized.output, usage=response.usage)
        except ExtractionError as error:
            if not error.retryable or delay is None:
                return _Extraction(
                    error=f"{error.code}: {error.message}",
                    model_fault=isinstance(error, _MODEL_FAULTS),
                )
            await asyncio.sleep(delay)
    return _Extraction(error="extraction failed")  # pragma: no cover - the loop always returns


async def _judge(
    case: GoldenCase, output: ExtractionOutput, judge: Judge
) -> tuple[tuple[JudgeVerdict, ...], tuple[ExtractionUsage, ...], str | None]:
    verdicts: list[JudgeVerdict] = []
    usages: list[ExtractionUsage] = []
    for expected in case.expected.memories:
        for delay in (*_RETRY_DELAYS_SECONDS, None):
            try:
                response = await judge.judge(case, expected, output)
            except JudgeError as error:
                if not error.retryable or delay is None:
                    return tuple(verdicts), tuple(usages), str(error)
                await asyncio.sleep(delay)
                continue
            verdicts.append(response.verdict)
            if response.usage is not None:
                usages.append(response.usage)
            break
    return tuple(verdicts), tuple(usages), None


async def evaluate_case(
    case: GoldenCase,
    extractor: Extractor,
    judge: Judge,
    *,
    call_context: LlmCallContext | None = None,
) -> CaseResult:
    """Extract, judge, and score one case.

    ``call_context`` names the evaluation run, so the extraction call is logged against
    it. The judge carries its own context.
    """
    extraction = await _extract(case, extractor, call_context)
    output = extraction.output
    if output is None:
        if extraction.model_fault:
            return CaseResult(
                case, score_case(case, None, error=extraction.error), error=extraction.error
            )
        return CaseResult(case, _unscored(case), error=extraction.error, evaluated=False)

    # The abstention check decides alone when either side abstains: no judge is needed.
    needs_judge = (
        not case.expects_abstention and output.disposition is not ExtractionDisposition.ABSTAIN
    )
    if not needs_judge:
        return CaseResult(
            case, score_case(case, output), output=output, extraction_usage=extraction.usage
        )

    verdicts, judge_usage, judge_error = await _judge(case, output, judge)
    if judge_error is not None:
        # The extraction exists, but nothing could assess it. That is not a quality result.
        return CaseResult(
            case,
            _unscored(case),
            output=output,
            verdicts=verdicts,
            extraction_usage=extraction.usage,
            judge_usage=judge_usage,
            error=judge_error,
            evaluated=False,
        )
    return CaseResult(
        case,
        score_case(case, output, verdicts),
        output=output,
        verdicts=verdicts,
        extraction_usage=extraction.usage,
        judge_usage=judge_usage,
    )


async def run_evaluation(
    cases: Sequence[GoldenCase],
    extractor: Extractor,
    judge: Judge,
    *,
    concurrency: int = 6,
    call_context: LlmCallContext | None = None,
    on_result: OnResult | None = None,
) -> EvaluationRun:
    """Evaluate the cases with bounded concurrency. Results keep the dataset order.

    ``on_result`` is awaited for each case as soon as it is scored, so a caller can store
    results while the run is still going.
    """
    limiter = asyncio.Semaphore(concurrency)

    async def bounded(position: int, case: GoldenCase) -> CaseResult:
        async with limiter:
            result = await evaluate_case(case, extractor, judge, call_context=call_context)
            if on_result is not None:
                await on_result(position, result)
            return result

    results = await asyncio.gather(
        *(bounded(position, case) for position, case in enumerate(cases))
    )
    return EvaluationRun(
        results=tuple(results),
        extractor_model=extractor.descriptor.model,
        extractor_version=extractor.descriptor.version,
        judge_model=judge.model,
    )
