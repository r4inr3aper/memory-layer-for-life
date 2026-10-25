#!/usr/bin/env python3
"""Measure memory retrieval on the golden dataset.

Run explicitly: python -m scripts.run_retrieval_eval [--embedder none|voyage] [--rerank]

It builds the golden memory store in the *test* database (its name must end with
``_test``; the database is emptied first, so never run it while the tests run), then asks
every question of ``retrieval_queries.jsonl`` and writes a report to ``eval_reports/``.

* ``--embedder none`` (default) measures words and names only. No provider is called.
* ``--embedder voyage`` also embeds the store and the questions with the configured
  EMBEDDING_MODEL. This calls Voyage AI and costs money (about a cent for the dataset).
* ``--rerank`` also reranks with RETRIEVAL_RERANK_MODEL (Voyage AI, also paid).
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import make_url, text

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.base import Base
from evaluation.fixture_extractor import GoldenFixtureExtractor
from evaluation.golden import load_golden_cases
from evaluation.retrieval.dataset import check_against_golden, load_retrieval_cases
from evaluation.retrieval.harness import (
    build_golden_store,
    evaluate,
    memories_by_content,
    render_markdown,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://brain:brain_dev_password@localhost:5432/second_brain_test"
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure memory retrieval on the golden dataset.")
    parser.add_argument("--embedder", choices=["none", "voyage"], default="none")
    parser.add_argument("--rerank", action="store_true", help="Rerank with RETRIEVAL_RERANK_MODEL.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "eval_reports")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> int:
    database_url = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    if not (make_url(database_url).database or "").endswith("_test"):
        print("ERROR: the evaluation only runs on a database whose name ends with _test.")
        return 2
    configured = get_settings()
    if arguments.embedder == "voyage" and configured.VOYAGE_API_KEY is None:
        print("ERROR: --embedder voyage needs VOYAGE_API_KEY.")
        return 2
    if arguments.rerank and configured.RETRIEVAL_RERANK_MODEL is None:
        print("ERROR: --rerank needs RETRIEVAL_RERANK_MODEL.")
        return 2
    voyage_key = configured.VOYAGE_API_KEY if arguments.embedder == "voyage" else None
    rerank_model = configured.RETRIEVAL_RERANK_MODEL if arguments.rerank else None
    # Never the configured database, and providers only when asked for.
    settings = configured.model_copy(
        update={
            "DATABASE_URL": database_url,
            "SCHEDULER_ENABLED": False,
            "RETRIEVAL_INDEXER_ENABLED": False,
            "MEMORY_CAPTURE_ENABLED": False,
            "VOYAGE_API_KEY": voyage_key,
            "RETRIEVAL_RERANK_MODEL": rerank_model,
        }
    )
    setup_logging()

    golden = load_golden_cases()
    cases = load_retrieval_cases()
    check_against_golden(cases, golden)

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )
    container = build_container(settings, extractor=GoldenFixtureExtractor(golden))
    try:
        tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
        async with container.engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

        await build_golden_store(container.ingestion_service, container.pipeline_runner, golden)
        if container.memory_indexer is not None:
            report = await container.memory_indexer.run()
            print(f"Embedded {report.embedded} memories ({report.tokens} tokens).")
            if report.stopped_by is not None:
                print(f"ERROR: embedding stopped: {report.stopped_by}")
                return 1

        index = await memories_by_content(container.session_factory)
        evaluation = await evaluate(container.retrieval_engine, cases, golden, index)
    finally:
        await container.aclose()

    contents = {memory_id: content for content, ids in index.items() for memory_id in ids}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = arguments.output_dir / f"retrieval_{stamp}.md"
    json_path = arguments.output_dir / f"retrieval_{stamp}.json"
    markdown_path.write_text(render_markdown(evaluation, contents), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "embedding_space": evaluation.embedding_space,
                "reranked": evaluation.reranked,
                "summary": evaluation.summary(),
                "queries": [
                    {
                        "query_id": result.case.query_id,
                        "category": result.case.category.value,
                        "metrics": dict(result.metrics),
                        "duration_ms": result.duration_ms,
                        "degraded": result.degraded,
                        "candidates": dict(result.candidates),
                    }
                    for result in evaluation.results
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    overall = evaluation.summary().get("all", {})
    print(
        f"Recall@5 {overall.get('recall@5')}, MRR {overall.get('mrr')} over "
        f"{int(overall.get('queries') or 0)} questions. Report: {markdown_path}"
    )
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(_run(_parse_arguments())))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
