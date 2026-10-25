"""The stored form of evaluation results.

A case scored by a live run and a case read from a ``report.json`` file end up in the
same shape here, so the database holds one kind of record whatever produced it.

Report files written before a run could be incomplete counted every case as passed or
failed. Reading such a file applies today's rule instead: a case the provider or the
judge never answered was not evaluated, and it is left out of every total.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from app.domain.enums import EvaluationCaseOutcome, ExtractionDisposition
from app.domain.model_catalog import estimate_cost_usd
from app.integrations.extraction.base import ExtractionUsage
from evaluation.scoring import CheckName

# Extraction failures that mean the provider never gave an answer to score.
_PROVIDER_FAILURE_CODES: Final = (
    "EXTRACTION_PERMANENT_FAILURE",
    "EXTRACTION_TRANSIENT_FAILURE",
    "EXTRACTION_PROVIDER_BILLING",
    "EXTRACTION_FAILED",
)
_USAGE_ROLES: Final = ("extraction", "judge")


class ReportFormatError(ValueError):
    """A report file does not have the structure this code can read."""


@dataclass(frozen=True, slots=True)
class StoredCase:
    case_id: str
    outcome: EvaluationCaseOutcome
    expected_outcome: ExtractionDisposition
    produced_disposition: ExtractionDisposition | None
    failed_checks: tuple[str, ...]
    error: str | None
    document: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CaseTotals:
    """Counts over a set of stored cases. Checks are counted over evaluated cases only."""

    total: int
    passed: int
    failed: int
    not_evaluated: int
    check_totals: dict[str, dict[str, int]]


@dataclass(frozen=True, slots=True)
class StoredReport:
    """A report file, read into the stored form."""

    generated_at: datetime
    extractor_model: str | None
    extractor_version: str
    judge_model: str | None
    cases: tuple[StoredCase, ...]
    totals: CaseTotals
    not_gating: dict[str, Any]
    usage: dict[str, Any]
    estimated_cost_usd: Decimal | None


# --- Documents of a report file -------------------------------------------------------


class _Document(BaseModel):
    model_config = ConfigDict(extra="allow")


class _ExpectedDocument(_Document):
    outcome: ExtractionDisposition


class _ProducedDocument(_Document):
    disposition: ExtractionDisposition


class _CheckDocument(_Document):
    name: str
    passed: bool


class _CaseDocument(_Document):
    case_id: str
    passed: bool
    evaluated: bool | None = None
    expected: _ExpectedDocument
    produced: _ProducedDocument | None = None
    checks: list[_CheckDocument]
    error: str | None = None


class _ExtractorDocument(_Document):
    model: str | None = None
    version: str


class _JudgeDocument(_Document):
    model: str | None = None


class _ReportDocument(_Document):
    generated_at: AwareDatetime
    extractor: _ExtractorDocument
    judge: _JudgeDocument
    cases: list[dict[str, Any]]
    reported_not_gating: dict[str, Any] = {}
    usage: dict[str, dict[str, Any]] = {}


# --- Cases ----------------------------------------------------------------------------


def _was_evaluated(case: _CaseDocument) -> bool:
    """Whether a case was scored. Old report files do not say, so it is worked out."""
    if case.evaluated is not None:
        return case.evaluated
    if case.error is None:
        return True
    if case.produced is not None:
        # An error next to an extraction is a judge that never gave a verdict.
        return False
    return not case.error.startswith(_PROVIDER_FAILURE_CODES)


def stored_case(document: Mapping[str, Any]) -> StoredCase:
    """Read one case document, as produced by ``evaluation.report.case_document``.

    Raises ``ReportFormatError`` when the document cannot be read.
    """
    try:
        case = _CaseDocument.model_validate(document)
    except ValidationError as error:
        raise ReportFormatError(
            f"A case document is malformed ({error.error_count()} error(s))."
        ) from error

    if not _was_evaluated(case):
        outcome = EvaluationCaseOutcome.NOT_EVALUATED
        failed_checks: tuple[str, ...] = ()
    else:
        outcome = EvaluationCaseOutcome.PASSED if case.passed else EvaluationCaseOutcome.FAILED
        failed_checks = tuple(check.name for check in case.checks if not check.passed)

    stored_document = dict(document)
    stored_document["evaluated"] = outcome is not EvaluationCaseOutcome.NOT_EVALUATED
    stored_document["passed"] = outcome is EvaluationCaseOutcome.PASSED
    return StoredCase(
        case_id=case.case_id,
        outcome=outcome,
        expected_outcome=case.expected.outcome,
        produced_disposition=case.produced.disposition if case.produced is not None else None,
        failed_checks=failed_checks,
        error=case.error,
        document=stored_document,
    )


def summarize_cases(cases: Sequence[StoredCase]) -> CaseTotals:
    check_totals: dict[str, dict[str, int]] = {
        name.value: {"evaluated": 0, "passed": 0} for name in CheckName
    }
    for case in cases:
        if case.outcome is EvaluationCaseOutcome.NOT_EVALUATED:
            continue
        for check in case.document.get("checks", []):
            totals = check_totals.setdefault(check["name"], {"evaluated": 0, "passed": 0})
            totals["evaluated"] += 1
            totals["passed"] += int(bool(check["passed"]))
    counts = {outcome: 0 for outcome in EvaluationCaseOutcome}
    for case in cases:
        counts[case.outcome] += 1
    return CaseTotals(
        total=len(cases),
        passed=counts[EvaluationCaseOutcome.PASSED],
        failed=counts[EvaluationCaseOutcome.FAILED],
        not_evaluated=counts[EvaluationCaseOutcome.NOT_EVALUATED],
        check_totals=check_totals,
    )


# --- Usage ----------------------------------------------------------------------------


def priced_usage(usage: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], Decimal | None]:
    """Usage per role with its cost estimated from current list prices.

    Costs written into older report files are ignored: they are recomputed from the token
    counts, so every stored run is priced by the same table. The total is ``None`` when a
    role that made calls has no known price.
    """
    priced: dict[str, Any] = {}
    total: Decimal | None = Decimal(0)
    for role in _USAGE_ROLES:
        role_usage = usage.get(role)
        if role_usage is None:
            continue
        counts = ExtractionUsage(
            input_tokens=int(role_usage.get("input_tokens") or 0),
            output_tokens=int(role_usage.get("output_tokens") or 0),
            cache_read_input_tokens=int(role_usage.get("cache_read_input_tokens") or 0),
            cache_creation_input_tokens=int(role_usage.get("cache_creation_input_tokens") or 0),
        )
        model = role_usage.get("model")
        cost = estimate_cost_usd(model, counts, aggregate=True)
        priced[role] = {
            "model": model,
            "input_tokens": counts.input_tokens,
            "output_tokens": counts.output_tokens,
            "cache_read_input_tokens": counts.cache_read_input_tokens,
            "cache_creation_input_tokens": counts.cache_creation_input_tokens,
            "estimated_cost_usd": float(cost) if cost is not None else None,
        }
        made_calls = counts != ExtractionUsage()
        if cost is None and made_calls:
            total = None
        elif cost is not None and total is not None:
            total += cost
    return priced, total


# --- Whole reports --------------------------------------------------------------------


def read_report(report: Mapping[str, Any]) -> StoredReport:
    """Read a ``report.json`` document into the stored form.

    Raises ``ReportFormatError`` when the document cannot be read.
    """
    try:
        document = _ReportDocument.model_validate(report)
    except ValidationError as error:
        raise ReportFormatError(
            f"The report is malformed ({error.error_count()} error(s))."
        ) from error

    cases = tuple(stored_case(case) for case in document.cases)
    usage, cost = priced_usage(document.usage)
    return StoredReport(
        generated_at=document.generated_at,
        extractor_model=document.extractor.model,
        extractor_version=document.extractor.version,
        judge_model=document.judge.model,
        cases=cases,
        totals=summarize_cases(cases),
        not_gating=dict(document.reported_not_gating),
        usage=usage,
        estimated_cost_usd=cost,
    )
