#!/usr/bin/env python3
"""Manual Anthropic connectivity check.

Run explicitly: python -m scripts.check_anthropic_connection [--model MODEL]
Never runs automatically in CI or on server startup.

Makes one tiny call and reports whether the provider answered and the account could pay
for it. The call is logged in the database like every other, so the database must be
reachable.
"""

import argparse
import asyncio
import sys

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.domain.errors import DomainError


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check that the Anthropic API can be called.")
    parser.add_argument("--model", help="Defaults to ANTHROPIC_MODEL.")
    return parser.parse_args()


async def check_connection(model: str | None) -> int:
    settings = get_settings()
    setup_logging()
    container = build_container(settings)
    try:
        try:
            result = await container.diagnostics_service.check_connection(model)
        except DomainError as error:
            print(f"ERROR: {error.message}")
            return 1
    finally:
        await container.aclose()

    if not result.ok:
        print(f"FAILED: {result.error_message} ({result.error_code})")
        return 1
    print(f"SUCCESS: Connected to Anthropic ({result.model})")
    call = result.call
    if call is not None:
        print(
            f"Tokens: {call.input_tokens} in, {call.output_tokens} out. "
            f"Estimated cost: ${call.estimated_cost_usd}. Took {call.duration_ms} ms."
        )
    return 0


def main() -> None:
    sys.exit(asyncio.run(check_connection(_parse_arguments().model)))


if __name__ == "__main__":
    main()
