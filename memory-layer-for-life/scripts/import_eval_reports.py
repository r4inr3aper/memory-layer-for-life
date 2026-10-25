#!/usr/bin/env python3
"""Store evaluation reports that were written before results were kept in the database.

Run explicitly: python -m scripts.import_eval_reports [--reports DIR]

Reads every <DIR>/<name>/report.json and stores it as a completed evaluation run named
after its folder, so the console can show it. A report that is already stored is
skipped, so the command can be run again safely. No model is called.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging

DEFAULT_REPORT_ROOT = Path("eval_reports")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store evaluation report files.")
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORT_ROOT)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> int:
    root: Path = arguments.reports
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory.")
        return 2

    settings = get_settings()
    setup_logging()
    container = build_container(settings)
    created = skipped = unreadable = 0
    try:
        for folder in sorted(path for path in root.iterdir() if path.is_dir()):
            file = folder / "report.json"
            if not file.is_file():
                continue
            try:
                document = json.loads(file.read_text(encoding="utf-8"))
                run_id, was_created = await container.evaluation_service.import_report(
                    document, source_report=folder.name
                )
            except ValueError as error:
                # Malformed JSON and a malformed report both say what is wrong without
                # quoting the file.
                unreadable += 1
                print(f"{folder.name}: cannot be read ({type(error).__name__}: {error})")
                continue
            if was_created:
                created += 1
                print(f"{folder.name}: stored as evaluation run {run_id}")
            else:
                skipped += 1
                print(f"{folder.name}: already stored")
    finally:
        await container.aclose()

    print(f"Imported {created}, already stored {skipped}, unreadable {unreadable}.")
    return 1 if unreadable else 0


def main() -> None:
    sys.exit(asyncio.run(_run(_parse_arguments())))


if __name__ == "__main__":
    main()
