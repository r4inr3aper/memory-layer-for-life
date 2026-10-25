#!/usr/bin/env python3
"""Process queued runs.

Run explicitly: python -m scripts.process_pending [--limit N] [--watch SECONDS]

The API processes a unit right after capturing it. This worker is the recovery path:
it picks up runs that are still queued, such as retries whose backoff has elapsed, runs
captured while no API key was configured, and runs whose worker disappeared.

Without --watch it drains what is due and exits. With --watch it keeps polling.
"""

import argparse
import asyncio
import sys
from collections import Counter

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued pipeline runs.")
    parser.add_argument("--limit", type=int, default=100, help="Most runs to execute per pass.")
    parser.add_argument(
        "--watch",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Keep running and poll for due runs at this interval.",
    )
    return parser.parse_args()


async def _run(limit: int, watch: float | None) -> int:
    settings = get_settings()
    setup_logging()
    container = build_container(settings)
    try:
        if not container.pipeline_runner.can_process:
            print("ERROR: ANTHROPIC_API_KEY is not configured, so nothing can be processed.")
            return 1

        while True:
            outcomes = await container.pipeline_runner.process_available(limit=limit)
            counts = Counter(
                outcome.status.value if outcome.status is not None else "skipped"
                for outcome in outcomes
            )
            summary = ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))
            print(f"Executed {len(outcomes)} run(s). {summary or 'Nothing was due.'}")
            if watch is None:
                return 0
            await asyncio.sleep(watch)
    finally:
        await container.aclose()


def main() -> None:
    arguments = _parse_arguments()
    if arguments.limit < 1:
        print("ERROR: --limit must be at least 1.")
        sys.exit(2)
    try:
        sys.exit(asyncio.run(_run(arguments.limit, arguments.watch)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
