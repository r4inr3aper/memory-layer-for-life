#!/usr/bin/env python3
"""Live model-quality evaluation against the golden dataset.

Run explicitly:

    python -m scripts.run_golden_eval [--cases ID ...] [--model MODEL] [--effort LEVEL]
                                      [--judge-model MODEL] [--judge-effort LEVEL]
                                      [--concurrency N] [--output DIR]

This calls a model once per case to extract, and once more per non-abstaining case to
judge, so it costs money and sends the dataset's messages to the provider. It never runs
in tests or on startup.

The run and every case are stored in the database, where the console shows them next to
earlier runs, and every model call goes into the call log. A copy of the result is also
written to <output>/<timestamp>/ as report.json and report.md. The dataset is the file
named by EVALUATION_DATASET_PATH.

The exit code is 0 when every case passes, 1 when a case fails, and 2 when the run could
not start or could not evaluate every case, for example because the provider rejected
the calls.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.bootstrap import build_container
from app.core.config import EffortLevel, get_settings
from app.core.logging import setup_logging
from app.domain.enums import EvaluationTrigger
from app.domain.errors import DomainError
from app.services.evaluations import EvaluationOptions
from evaluation.report import build_report, write_report

DEFAULT_REPORT_ROOT = Path("eval_reports")
EFFORT_LEVELS: tuple[EffortLevel, ...] = ("low", "medium", "high", "xhigh", "max")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate extraction on the golden dataset.")
    parser.add_argument("--cases", nargs="+", metavar="ID", help="Only run these case ids.")
    parser.add_argument("--model", help="Extraction model. Defaults to ANTHROPIC_MODEL.")
    parser.add_argument(
        "--effort", choices=EFFORT_LEVELS, help="Extraction effort. Defaults to EXTRACTION_EFFORT."
    )
    parser.add_argument("--judge-model", help="Defaults to the extraction model.")
    parser.add_argument("--judge-effort", choices=EFFORT_LEVELS, default="high")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_ROOT)
    return parser.parse_args()


def _print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    if summary["complete"]:
        print(f"\n{summary['passed']} of {summary['cases']} cases pass.")
    else:
        print(
            f"\nINCOMPLETE RUN: {summary['not_evaluated']} of {summary['cases']} case(s) "
            "could not be evaluated."
        )
        for reason, count in summary["not_evaluated_reasons"].items():
            print(f"  {count} x {reason}")
        print(f"{summary['passed']} of {summary['evaluated']} evaluated cases pass.")
    for name, totals in report["checks"].items():
        print(f"  {name:<24} {totals['passed']:>3} / {totals['evaluated']}")
    disposition = report["reported_not_gating"]["disposition"]
    print(
        f"  disposition agreement (not gating): {disposition['agree']} / {disposition['compared']}"
    )
    for role in ("extraction", "judge"):
        usage = report["usage"][role]
        print(
            f"  {role} tokens: {usage['input_tokens']} in, {usage['output_tokens']} out, "
            f"{usage['cache_read_input_tokens']} cached, about ${usage['estimated_cost_usd']}"
        )
    if summary["failed_case_ids"]:
        print("Failing cases: " + ", ".join(summary["failed_case_ids"]))


async def _run(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging()
    options = EvaluationOptions(
        extractor_model=arguments.model,
        extraction_effort=arguments.effort,
        judge_model=arguments.judge_model,
        judge_effort=arguments.judge_effort,
        case_ids=tuple(arguments.cases) if arguments.cases else None,
        concurrency=arguments.concurrency,
    )
    extractor_model = options.extractor_model or settings.ANTHROPIC_MODEL
    scope = f"{len(options.case_ids)} case(s)" if options.case_ids else "the whole dataset"
    print(
        f"Evaluating {scope} with {extractor_model} "
        f"(effort {options.extraction_effort or settings.EXTRACTION_EFFORT}), "
        f"judged by {options.judge_model or extractor_model}..."
    )

    container = build_container(settings)
    try:
        try:
            completed = await container.evaluation_service.run(
                options, trigger=EvaluationTrigger.CLI
            )
        except DomainError as error:
            print(f"ERROR: {error.message}")
            return 2
        generated_at = datetime.now(UTC)
        directory = write_report(
            completed.outcome,
            arguments.output / generated_at.strftime("%Y%m%dT%H%M%SZ"),
            generated_at=generated_at,
        )
        await container.evaluation_service.attach_report_file(completed.run_id, directory.name)
    finally:
        await container.aclose()

    outcome = completed.outcome
    _print_summary(build_report(outcome, generated_at=generated_at))
    print(f"Stored as evaluation run {completed.run_id}.")
    print(f"Report: {directory / 'report.md'}")
    if not outcome.complete:
        return 2
    return 0 if outcome.all_passed else 1


def main() -> None:
    arguments = _parse_arguments()
    if arguments.concurrency < 1:
        print("ERROR: --concurrency must be at least 1.")
        sys.exit(2)
    sys.exit(asyncio.run(_run(arguments)))


if __name__ == "__main__":
    main()
