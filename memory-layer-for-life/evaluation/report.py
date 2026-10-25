"""Turns an evaluation run into a JSON document and a readable Markdown report.

Reports contain the source messages and what was extracted from them, so they hold
personal data. They are written to a local, git-ignored directory.
"""

import json
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from app.domain.model_catalog import estimate_cost_usd
from app.integrations.extraction.base import ExtractionUsage
from evaluation.runner import CaseResult, EvaluationRun
from evaluation.scoring import CheckName

REPORT_VERSION: Final = "1"


def total_usage(usages: Iterable[ExtractionUsage | None]) -> ExtractionUsage:
    present = [usage for usage in usages if usage is not None]
    return ExtractionUsage(
        input_tokens=sum(usage.input_tokens for usage in present),
        output_tokens=sum(usage.output_tokens for usage in present),
        cache_read_input_tokens=sum(usage.cache_read_input_tokens for usage in present),
        cache_creation_input_tokens=sum(usage.cache_creation_input_tokens for usage in present),
    )


def estimate_cost(usage: ExtractionUsage, model: str | None) -> float | None:
    """Estimated cost of summed usage in US dollars, or ``None`` for an unpriced model.

    Prices come from ``app.domain.model_catalog``. The per-call costs in the call log are
    the more exact figure. This one is for the totals of a run.
    """
    cost = estimate_cost_usd(model, usage, aggregate=True)
    return float(cost) if cost is not None else None


def _usage_document(usage: ExtractionUsage, model: str | None) -> dict[str, Any]:
    cost = estimate_cost(usage, model)
    return {
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "estimated_cost_usd": round(cost, 4) if cost is not None else None,
    }


def case_document(result: CaseResult) -> dict[str, Any]:
    """Everything about one case, as it is written to a report and stored."""
    case = result.case
    output = result.output
    return {
        "case_id": case.case_id,
        "evaluated": result.evaluated,
        "passed": result.score.passed,
        "tags": list(case.tags),
        "review_status": case.review_status,
        "messages": [message.content for message in case.input.messages],
        "expected": {
            "outcome": case.expected.outcome.value,
            "memories": [
                {
                    "type": memory.type,
                    "status": memory.status,
                    "summary": memory.summary,
                    "attributes": memory.attributes,
                }
                for memory in case.expected.memories
            ],
            "must_not": list(case.must_not),
        },
        "produced": (
            {
                "disposition": output.disposition.value,
                "disposition_reason": output.disposition_reason,
                "memories": [memory.model_dump(mode="json") for memory in output.memories],
                "entity_mentions": [
                    mention.model_dump(mode="json") for mention in output.entity_mentions
                ],
            }
            if output is not None
            else None
        ),
        "checks": [
            {"name": check.name.value, "passed": check.passed, "detail": check.detail}
            for check in result.score.checks
        ],
        "disposition_agrees": result.score.disposition_agrees,
        "state_agrees": result.score.state_agrees,
        "judge": [verdict.model_dump(mode="json") for verdict in result.verdicts],
        "error": result.error,
    }


def build_report(run: EvaluationRun, *, generated_at: datetime) -> dict[str, Any]:
    results = run.results
    check_totals: dict[str, dict[str, int]] = {
        name.value: {"evaluated": 0, "passed": 0} for name in CheckName
    }
    for result in results:
        for check in result.score.checks:
            check_totals[check.name.value]["evaluated"] += 1
            check_totals[check.name.value]["passed"] += int(check.passed)

    with_disposition = [r for r in results if r.score.disposition_agrees is not None]
    with_state = [r for r in results if r.score.state_agrees is not None]
    extraction_usage = total_usage(result.extraction_usage for result in results)
    judge_usage = total_usage(usage for result in results for usage in result.judge_usage)

    return {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at.isoformat(),
        "extractor": {"model": run.extractor_model, "version": run.extractor_version},
        "judge": {"model": run.judge_model},
        "dataset": {
            "cases": len(results),
            "review_status": dict(Counter(result.case.review_status for result in results)),
        },
        "summary": {
            "cases": len(results),
            "evaluated": len(run.evaluated),
            "passed": len(run.passed),
            "failed": len(run.failed),
            "not_evaluated": len(run.not_evaluated),
            "complete": run.complete,
            "all_passed": run.all_passed,
            "failed_case_ids": [result.case.case_id for result in run.failed],
            "not_evaluated_case_ids": [result.case.case_id for result in run.not_evaluated],
            "not_evaluated_reasons": dict(
                Counter(result.error or "unknown" for result in run.not_evaluated)
            ),
        },
        "checks": check_totals,
        "reported_not_gating": {
            "disposition": {
                "compared": len(with_disposition),
                "agree": sum(bool(r.score.disposition_agrees) for r in with_disposition),
                "disagreements": [
                    {
                        "case_id": r.case.case_id,
                        "expected": r.case.expected.outcome.value,
                        "produced": r.output.disposition.value if r.output else None,
                    }
                    for r in with_disposition
                    if not r.score.disposition_agrees
                ],
            },
            "state": {
                "compared": len(with_state),
                "agree": sum(bool(r.score.state_agrees) for r in with_state),
                "disagreements": [r.case.case_id for r in with_state if not r.score.state_agrees],
            },
        },
        "usage": {
            "extraction": _usage_document(extraction_usage, run.extractor_model),
            "judge": _usage_document(judge_usage, run.judge_model),
        },
        "cases": [case_document(result) for result in results],
    }


def _result_lines(summary: dict[str, Any]) -> list[str]:
    """The headline. An incomplete run says so before it gives any number."""
    if summary["complete"]:
        return [f"**{summary['passed']} of {summary['cases']} cases pass.**"]
    lines = [
        f"**Incomplete run: {summary['not_evaluated']} of {summary['cases']} cases could "
        "not be evaluated.** They count as neither passed nor failed.",
        "",
        "| Reason | Cases |",
        "|---|---|",
    ]
    lines += [
        f"| {reason} | {count} |" for reason, count in summary["not_evaluated_reasons"].items()
    ]
    lines += [
        "",
        "Not evaluated: " + ", ".join(summary["not_evaluated_case_ids"]),
        "",
        f"**{summary['passed']} of {summary['evaluated']} evaluated cases pass.**",
    ]
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Golden evaluation report",
        "",
        f"Generated: {report['generated_at']}",
        f"Extractor: {report['extractor']['model']} ({report['extractor']['version']})",
        f"Judge: {report['judge']['model']}",
        "",
        "Every case in the dataset is marked "
        f"`{', '.join(report['dataset']['review_status'])}`. The labels are a regression "
        "baseline, not verified ground truth.",
        "",
        "## Result",
        "",
        *_result_lines(summary),
        "",
        "| Check | Passed | Evaluated |",
        "|---|---|---|",
    ]
    lines += [
        f"| {name} | {totals['passed']} | {totals['evaluated']} |"
        for name, totals in report["checks"].items()
    ]

    disposition = report["reported_not_gating"]["disposition"]
    state = report["reported_not_gating"]["state"]
    lines += [
        "",
        "## Reported, not gating",
        "",
        f"- Disposition matches the label in {disposition['agree']} of "
        f"{disposition['compared']} cases.",
        f"- State is one the label's status allows in {state['agree']} of "
        f"{state['compared']} cases.",
    ]
    if disposition["disagreements"]:
        lines += ["", "| Case | Label | Produced |", "|---|---|---|"]
        lines += [
            f"| {item['case_id']} | {item['expected']} | {item['produced']} |"
            for item in disposition["disagreements"]
        ]

    lines += ["", "## Cost", "", "| Role | Model | Input | Output | Cache read | Estimated USD |"]
    lines.append("|---|---|---|---|---|---|")
    for role in ("extraction", "judge"):
        usage = report["usage"][role]
        cost = usage["estimated_cost_usd"]
        lines.append(
            f"| {role} | {usage['model']} | {usage['input_tokens']} | {usage['output_tokens']} | "
            f"{usage['cache_read_input_tokens']} | {cost if cost is not None else 'unknown'} |"
        )

    failed = [case for case in report["cases"] if case["evaluated"] and not case["passed"]]
    lines += ["", f"## Failing cases ({len(failed)})", ""]
    if not failed:
        lines.append("None.")
    for case in failed:
        lines += [f"### {case['case_id']}", ""]
        lines += [f"- Message: `{message}`" for message in case["messages"]]
        for expected in case["expected"]["memories"]:
            lines.append(
                f"- Expected ({case['expected']['outcome']}, {expected['type']}): "
                f"{expected['summary']}"
            )
        if not case["expected"]["memories"]:
            lines.append(f"- Expected: {case['expected']['outcome']}")
        produced = case["produced"]
        if produced is None:
            lines.append(f"- Produced: nothing ({case['error']})")
        else:
            lines.append(f"- Produced disposition: {produced['disposition']}")
            lines += [
                f"- Produced [{index}] ({memory['memory_type']}, {memory['state']}): "
                f"{memory['content']}"
                for index, memory in enumerate(produced["memories"])
            ]
        lines += [
            f"- FAILED {check['name']}: {check['detail']}"
            for check in case["checks"]
            if not check["passed"]
        ]
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(run: EvaluationRun, directory: Path, *, generated_at: datetime) -> Path:
    """Write ``report.json`` and ``report.md`` into ``directory`` and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    report = build_report(run, generated_at=generated_at)
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return directory
