"""Scoring of one golden case.

A case passes when every gating check passes. The checks, and why each exists:

``valid_output``
    The extractor returned output that satisfies the contract and points only at
    messages that exist.
``abstention``
    The system abstained exactly when the case expects it. Producing a memory from an
    unintelligible fragment is the failure the project fears most, so this is checked
    first and decides alone for abstention cases.
``coverage``
    The produced memories convey the expected memory. Decided by the judge. Exact wording
    is not required, and neither is an exact number of memories: one input can
    legitimately be recorded as several memories, and one dataset input is shared by two
    cases that each expect a different part of it.
``memory_type``
    The produced memory that corresponds to the expected one has a type that
    ``evaluation.label_mapping`` accepts for the annotator's label. Only that primary
    memory is type-checked: when a note is recorded as several memories, its parts
    legitimately have different types.
``no_invented_completion``
    No conveying memory is marked ``done`` unless the annotator's status says the thing
    already happened.
``structured_fields``
    Amounts, currency, and dates agree with the label wherever the label states them. A
    label that says ``currency: null`` forbids any currency.
``must_not``
    No ``must_not`` rule of the case is broken. Decided by the judge.
``grounded``
    No memory states a fact the source does not support. Decided by the judge.

Two more comparisons are reported but do not gate, because the dataset's own labels are
not consistent enough to treat them as right or wrong. Both are listed in the report so
the labels can be reviewed:

``disposition_agrees``
    Whether ``extract`` versus ``context`` matches. Inputs of the same shape carry
    different labels in the dataset, for example a bare amount followed by an item name.
``state_agrees``
    Whether the pending-or-done state is one the annotator's status allows.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.enums import ExtractionDisposition, MemoryState
from app.schemas.extraction import ExtractedMemory, ExtractionOutput
from evaluation.golden import GoldenCase, GoldenExpectedMemory
from evaluation.judge import JudgeVerdict
from evaluation.label_mapping import accepted_memory_types, accepted_states, allows_done

_AMOUNT_TOLERANCE = 1e-6


class CheckName(StrEnum):
    VALID_OUTPUT = "valid_output"
    ABSTENTION = "abstention"
    COVERAGE = "coverage"
    MEMORY_TYPE = "memory_type"
    NO_INVENTED_COMPLETION = "no_invented_completion"
    STRUCTURED_FIELDS = "structured_fields"
    MUST_NOT = "must_not"
    GROUNDED = "grounded"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: CheckName
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    checks: tuple[CheckResult, ...]
    disposition_agrees: bool | None = None
    state_agrees: bool | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)


def _same_amount(actual: float | None, expected: float) -> bool:
    return actual is not None and math.isclose(actual, expected, abs_tol=_AMOUNT_TOLERANCE)


def check_structured_fields(
    expected: GoldenExpectedMemory, covering: Sequence[ExtractedMemory]
) -> CheckResult:
    """Compare money and date fields the label states with what was extracted."""
    attributes = expected.attributes
    financials = [memory.financial for memory in covering if memory.financial is not None]
    problems: list[str] = []
    checked: list[str] = []

    if expected.has("currency"):
        checked.append("currency")
        wanted = attributes["currency"]
        stated = sorted({item.currency for item in financials if item.currency is not None})
        if wanted is None and stated:
            problems.append(f"currency {stated} was stated but the source gives none")
        if wanted is not None and wanted not in stated:
            problems.append(f"currency {wanted} expected, found {stated or 'none'}")

    for attribute in ("amount", "computed_total"):
        if expected.has(attribute):
            checked.append(attribute)
            wanted_amount = float(attributes[attribute])
            if not any(_same_amount(item.amount, wanted_amount) for item in financials):
                found = [item.amount for item in financials]
                problems.append(f"{attribute} {wanted_amount:g} expected, found {found}")

    if expected.has("amounts"):
        checked.append("amounts")
        stated_amounts = [amount for item in financials for amount in item.component_amounts]
        missing = [
            float(amount)
            for amount in attributes["amounts"]
            if not any(_same_amount(stated, float(amount)) for stated in stated_amounts)
        ]
        if missing:
            problems.append(f"amounts {missing} are missing from {stated_amounts}")

    for attribute in ("year", "due_at"):
        if expected.has(attribute) and attributes[attribute] is None:
            checked.append(attribute)
            resolved = [
                memory.temporal.resolved_date.isoformat()
                for memory in covering
                if memory.temporal is not None and memory.temporal.resolved_date is not None
            ]
            if resolved:
                problems.append(
                    f"a date was resolved ({resolved}) although the label leaves {attribute} open"
                )

    if problems:
        return CheckResult(CheckName.STRUCTURED_FIELDS, False, "; ".join(problems))
    detail = f"checked {', '.join(checked)}" if checked else "the label states no checked field"
    return CheckResult(CheckName.STRUCTURED_FIELDS, True, detail)


def _covering_memories(
    output: ExtractionOutput, verdict: JudgeVerdict
) -> tuple[list[ExtractedMemory], list[int]]:
    """Memories the judge named as conveying the expected one, and any bad indexes."""
    valid = [
        index for index in verdict.covering_memory_indexes if 0 <= index < len(output.memories)
    ]
    invalid = [index for index in verdict.covering_memory_indexes if index not in valid]
    return [output.memories[index] for index in dict.fromkeys(valid)], invalid


def _score_expected_memory(
    case: GoldenCase,
    expected: GoldenExpectedMemory,
    output: ExtractionOutput,
    verdict: JudgeVerdict,
) -> tuple[list[CheckResult], bool]:
    """Gating checks for one expected memory, and whether the state agrees."""
    covering, invalid_indexes = _covering_memories(output, verdict)
    checks: list[CheckResult] = []

    covered = verdict.coverage == "covered" and bool(covering) and not invalid_indexes
    coverage_detail = verdict.coverage_explanation
    if invalid_indexes:
        coverage_detail = f"judge named memories that do not exist: {invalid_indexes}"
    elif verdict.coverage == "covered" and not covering:
        coverage_detail = "judge reported coverage without naming a memory"
    checks.append(CheckResult(CheckName.COVERAGE, covered, coverage_detail))

    accepted = accepted_memory_types(expected.type)
    primary_index = verdict.primary_memory_index
    if primary_index is None or not 0 <= primary_index < len(output.memories):
        type_ok = False
        type_detail = "no produced memory corresponds to the expected one"
    else:
        primary_type = output.memories[primary_index].memory_type
        type_ok = primary_type in accepted
        type_detail = f"'{primary_type.value}' for label '{expected.type}'"
        if not type_ok:
            type_detail += f" (accepted: {[item.value for item in accepted]})"
    checks.append(CheckResult(CheckName.MEMORY_TYPE, type_ok, type_detail))

    invented_completion = any(
        memory.state is MemoryState.DONE for memory in covering
    ) and not allows_done(expected.status)
    checks.append(
        CheckResult(
            CheckName.NO_INVENTED_COMPLETION,
            not invented_completion,
            f"marked done although the label status is '{expected.status}'"
            if invented_completion
            else "",
        )
    )

    checks.append(check_structured_fields(expected, covering))

    verdict_by_rule = {item.rule_index: item for item in verdict.rule_verdicts}
    rule_problems: list[str] = []
    for index, rule in enumerate(case.must_not):
        rule_verdict = verdict_by_rule.get(index)
        if rule_verdict is None:
            rule_problems.append(f"rule {index} was not judged: {rule}")
        elif rule_verdict.violated:
            rule_problems.append(f"rule {index} broken ({rule}): {rule_verdict.explanation}")
    checks.append(CheckResult(CheckName.MUST_NOT, not rule_problems, " | ".join(rule_problems)))

    checks.append(
        CheckResult(
            CheckName.GROUNDED,
            not verdict.unsupported_claims,
            " | ".join(
                f"memory {claim.memory_index}: {claim.claim}"
                for claim in verdict.unsupported_claims
            ),
        )
    )

    state_agrees = bool(covering) and all(
        memory.state in accepted_states(expected.status) for memory in covering
    )
    return checks, state_agrees


def _merge(results: Sequence[CheckResult]) -> CheckResult:
    """Combine the results of one check across several expected memories."""
    details = [result.detail for result in results if result.detail]
    return CheckResult(
        results[0].name, all(result.passed for result in results), " || ".join(details)
    )


def score_case(
    case: GoldenCase,
    output: ExtractionOutput | None,
    verdicts: Sequence[JudgeVerdict] | None = None,
    *,
    error: str | None = None,
) -> CaseScore:
    """Score one case.

    ``output`` is ``None`` when extraction failed, with the reason in ``error``.
    ``verdicts`` holds one judge verdict per expected memory, in order. It is not needed
    when the abstention check already decides the case.
    """
    if output is None:
        return CaseScore(
            case.case_id,
            (CheckResult(CheckName.VALID_OUTPUT, False, error or "extraction failed"),),
        )

    checks: list[CheckResult] = [CheckResult(CheckName.VALID_OUTPUT, True)]
    abstained = output.disposition is ExtractionDisposition.ABSTAIN
    disposition_agrees = output.disposition is case.expected.outcome

    if case.expects_abstention or abstained:
        correct = case.expects_abstention and abstained
        if correct:
            detail = ""
        elif abstained:
            detail = "abstained although a memory was expected"
        else:
            detail = f"produced {len(output.memories)} memory(ies) where abstention was expected"
        checks.append(CheckResult(CheckName.ABSTENTION, correct, detail))
        return CaseScore(case.case_id, tuple(checks), disposition_agrees=disposition_agrees)

    checks.append(CheckResult(CheckName.ABSTENTION, True))
    expected_memories = case.expected.memories
    if verdicts is None or len(verdicts) != len(expected_memories):
        checks.append(
            CheckResult(CheckName.COVERAGE, False, error or "no judge verdict is available")
        )
        return CaseScore(case.case_id, tuple(checks), disposition_agrees=disposition_agrees)

    per_memory = [
        _score_expected_memory(case, expected, output, verdict)
        for expected, verdict in zip(expected_memories, verdicts, strict=True)
    ]
    for position in range(len(per_memory[0][0])):
        checks.append(_merge([memory_checks[position] for memory_checks, _ in per_memory]))

    return CaseScore(
        case.case_id,
        tuple(checks),
        disposition_agrees=disposition_agrees,
        state_agrees=all(agrees for _, agrees in per_memory),
    )
