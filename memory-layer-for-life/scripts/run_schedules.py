#!/usr/bin/env python3
"""Run scheduled tasks that are due.

Run explicitly: python -m scripts.run_schedules [--watch SECONDS]

The API dispatches due schedules itself while SCHEDULER_ENABLED is true. This script is
for running the dispatcher on its own, for example in a separate process with the API's
loop turned off, or once by hand. Several dispatchers can run at the same time: each
slot is claimed in the database, so it runs once.

Without --watch it runs what is due and exits. With --watch it keeps polling.
"""

import argparse
import asyncio
import sys

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled tasks that are due.")
    parser.add_argument(
        "--watch",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Keep running and poll for due schedules at this interval.",
    )
    return parser.parse_args()


async def _run(watch: float | None) -> int:
    settings = get_settings()
    setup_logging()
    container = build_container(settings)
    try:
        if not container.chat_turn_service.available:
            print("ERROR: ANTHROPIC_API_KEY is not configured, so schedules cannot run.")
            return 1

        while True:
            executed = await container.schedule_dispatcher.run_due()
            print(f"Ran {len(executed)} scheduled task(s).")
            if watch is None:
                return 0
            await asyncio.sleep(watch)
    finally:
        await container.aclose()


def main() -> None:
    arguments = _parse_arguments()
    if arguments.watch is not None and arguments.watch <= 0:
        print("ERROR: --watch must be a positive number of seconds.")
        sys.exit(2)
    try:
        sys.exit(asyncio.run(_run(arguments.watch)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
