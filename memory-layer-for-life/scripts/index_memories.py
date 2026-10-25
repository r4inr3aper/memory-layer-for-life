#!/usr/bin/env python3
"""Embed memories for semantic retrieval.

Run explicitly: python -m scripts.index_memories [--mode changed|verify|rebuild]
                [--limit N] [--prune-other-spaces] [--status]

The API embeds new and changed memories by itself while it runs (RETRIEVAL_INDEXER_
ENABLED). This command is for everything else:

* ``changed`` (default): embed memories with no embedding, or changed since.
* ``verify``: rebuild every memory's document and re-embed those that no longer match,
  for example after an entity was renamed.
* ``rebuild``: re-embed every memory, for example after changing EMBEDDING_MODEL or
  EMBEDDING_DIMENSIONS (a new space starts empty).
* ``--prune-other-spaces``: delete embeddings of every space but the configured one,
  once the new space is complete.
* ``--status``: print how much of the store is embedded, and call nothing.

This calls Voyage AI and costs money (little: a few hundred memories are a few cents).
"""

import argparse
import asyncio
import sys

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.retrieval.indexer import IndexMode


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed memories for semantic retrieval.")
    parser.add_argument(
        "--mode", choices=[mode.value for mode in IndexMode], default=IndexMode.CHANGED.value
    )
    parser.add_argument("--limit", type=int, default=None, help="Most memories to examine.")
    parser.add_argument(
        "--prune-other-spaces",
        action="store_true",
        help="Delete embeddings of every space but the configured one.",
    )
    parser.add_argument(
        "--status", action="store_true", help="Only report coverage; call no provider."
    )
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging()
    container = build_container(settings)
    try:
        indexer = container.memory_indexer
        if indexer is None:
            print("ERROR: VOYAGE_API_KEY is not configured, so nothing can be embedded.")
            return 1
        embedded, total = await indexer.coverage()
        print(f"Space {indexer.space_key}: {embedded} of {total} memories embedded and current.")
        if arguments.status:
            return 0

        report = await indexer.run(IndexMode(arguments.mode), limit=arguments.limit)
        print(
            f"Examined {report.examined}: embedded {report.embedded}, already current "
            f"{report.unchanged}, failed {report.failed}; {report.tokens} tokens."
        )
        if report.stopped_by is not None:
            print(f"Stopped early: {report.stopped_by}")
            return 1
        if arguments.prune_other_spaces:
            removed = await indexer.prune_other_spaces()
            print(f"Removed {removed} embeddings of other spaces.")
        return 0
    finally:
        await container.aclose()


def main() -> None:
    arguments = _parse_arguments()
    if arguments.limit is not None and arguments.limit < 1:
        print("ERROR: --limit must be at least 1.")
        sys.exit(2)
    try:
        sys.exit(asyncio.run(_run(arguments)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
