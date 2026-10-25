"""Migrations: reversible, and safe to apply on top of existing data."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from tests.integration.conftest import run_alembic

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        return {row.tablename for row in rows}


async def _constraint_names(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = to_regclass(:table) AND contype = 'c'"
            ),
            {"table": table},
        )
        return {row.conname for row in rows}


async def _migrate(engine: AsyncEngine, *arguments: str) -> None:
    await asyncio.to_thread(run_alembic, *arguments)
    # Pooled connections cache statements for tables that were just rebuilt.
    await engine.dispose()


async def test_schema_downgrades_to_empty_and_upgrades_again(engine: AsyncEngine) -> None:
    try:
        await _migrate(engine, "downgrade", "base")
        assert await _table_names(engine) == {"alembic_version"}
    finally:
        await _migrate(engine, "upgrade", "head")

    assert await _table_names(engine) == set(Base.metadata.tables) | {"alembic_version"}


async def test_downgrade_restores_the_first_revision_exactly(engine: AsyncEngine) -> None:
    try:
        await _migrate(engine, "downgrade", "001")
        assert "processing_run_messages" not in await _table_names(engine)
        # Revision 001 really created its checks under these doubled names.
        assert await _constraint_names(engine, "entities") == {
            "ck_entities_ck_entities_no_self_merge",
            "ck_entities_ck_entities_valid_entity_status",
            "ck_entities_ck_entities_valid_entity_type",
        }
    finally:
        await _migrate(engine, "upgrade", "head")

    assert "ck_entities_no_self_merge" in await _constraint_names(engine, "entities")


async def test_upgrade_keeps_and_backfills_rows_written_under_the_first_revision(
    engine: AsyncEngine,
) -> None:
    message_id, run_id, result_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first_mention, second_mention = uuid.uuid4(), uuid.uuid4()
    memory_id, source_id = uuid.uuid4(), uuid.uuid4()
    content = "call Asha and Bina"
    try:
        await _migrate(engine, "downgrade", "001")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO raw_messages (id, source, content, content_sha256, ingested_at, "
                    "created_at) VALUES (:id, 'api_input', :content, :sha, :at, :at)"
                ),
                {
                    "id": message_id,
                    "content": content,
                    "sha": hashlib.sha256(content.encode()).hexdigest(),
                    "at": T0,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO processing_runs (id, raw_message_id, pipeline_version, status, "
                    "idempotency_key, created_at) "
                    "VALUES (:id, :message, '0.9', 'succeeded', 'legacy-key', :at)"
                ),
                {"id": run_id, "message": message_id, "at": T0},
            )
            await connection.execute(
                text(
                    "INSERT INTO extraction_results (id, processing_run_id, schema_version, "
                    "extractor_version, status, created_at) "
                    "VALUES (:id, :run, '1.0', 'legacy', 'succeeded', :at)"
                ),
                {"id": result_id, "run": run_id, "at": T0},
            )
            for mention_id, name, offset, created in (
                (second_mention, "Bina", 14, T0 + timedelta(seconds=2)),
                (first_mention, "Asha", 5, T0 + timedelta(seconds=1)),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO entity_mentions (id, raw_message_id, extraction_result_id, "
                        "entity_type, mention_text, normalized_mention, start_offset, end_offset, "
                        "created_at) VALUES (:id, :message, :result, 'person', :name, "
                        ":normalized, :start, :end, :at)"
                    ),
                    {
                        "id": mention_id,
                        "message": message_id,
                        "result": result_id,
                        "name": name,
                        "normalized": name.casefold(),
                        "start": offset,
                        "end": offset + len(name),
                        "at": created,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO memories (id, memory_type, content, created_at, updated_at) "
                    "VALUES (:id, 'task', 'Call Asha and Bina', :at, :at)"
                ),
                {"id": memory_id, "at": T0},
            )
            await connection.execute(
                text(
                    "INSERT INTO memory_sources (id, memory_id, raw_message_id, "
                    "extraction_result_id, source_role, created_at) "
                    "VALUES (:id, :memory, :message, :result, 'supporting', :at)"
                ),
                {
                    "id": source_id,
                    "memory": memory_id,
                    "message": message_id,
                    "result": result_id,
                    "at": T0,
                },
            )
    finally:
        await _migrate(engine, "upgrade", "head")

    async with engine.connect() as connection:
        unit = (
            await connection.execute(
                text(
                    "SELECT raw_message_id, position FROM processing_run_messages "
                    "WHERE processing_run_id = :run"
                ),
                {"run": run_id},
            )
        ).all()
        ordinals = dict(
            (
                await connection.execute(
                    text(
                        "SELECT id, ordinal FROM entity_mentions "
                        "WHERE extraction_result_id = :result"
                    ),
                    {"result": result_id},
                )
            ).all()
        )
        run = (
            await connection.execute(
                text("SELECT available_at, status FROM processing_runs WHERE id = :run"),
                {"run": run_id},
            )
        ).one()
        memory = (
            await connection.execute(
                text(
                    "SELECT content, origin_extraction_result_id, origin_ordinal "
                    "FROM memories WHERE id = :id"
                ),
                {"id": memory_id},
            )
        ).one()
        sources = (
            await connection.execute(text("SELECT count(*) FROM memory_sources"))
        ).scalar_one()

    # The old run processed exactly its anchor message.
    assert [tuple(row) for row in unit] == [(message_id, 0)]
    # Mentions are numbered in the order they were created.
    assert ordinals == {first_mention: 0, second_mention: 1}
    assert run.status == "succeeded"
    assert run.available_at is not None
    # Rows that did not come from the pipeline keep an empty origin.
    assert tuple(memory) == ("Call Asha and Bina", None, None)
    assert sources == 1
