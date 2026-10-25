"""The migrated schema and the SQLAlchemy models must describe the same database.

Alembic's autogenerate does not compare CHECK constraints, and a mismatch there is exactly
what went unnoticed in the first revision. This test builds the models into a scratch
schema with ``create_all`` and compares the PostgreSQL catalogs of both schemas: columns,
defaults, constraints, and indexes.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.base import Base

MIGRATED_SCHEMA = "public"
MODEL_SCHEMA = "model_snapshot"

# Objects that exist only in the migrated schema by design.
MIGRATION_ONLY_TABLES = {"alembic_version"}


def _strip_schema(definition: str) -> str:
    return definition.replace(f"{MODEL_SCHEMA}.", "").replace(f"{MIGRATED_SCHEMA}.", "")


async def _columns(connection: AsyncConnection, schema: str) -> set[tuple[object, ...]]:
    rows = await connection.execute(
        text(
            """
            SELECT table_name, column_name, data_type, character_maximum_length,
                   numeric_precision, numeric_scale, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = :schema
            """
        ),
        {"schema": schema},
    )
    return {tuple(row) for row in rows if row.table_name not in MIGRATION_ONLY_TABLES}


async def _constraints(connection: AsyncConnection, schema: str) -> set[tuple[str, str, str, str]]:
    rows = await connection.execute(
        text(
            """
            SELECT rel.relname AS table_name, con.conname, con.contype::text AS kind,
                   pg_get_constraintdef(con.oid) AS definition
            FROM pg_constraint AS con
            JOIN pg_class AS rel ON rel.oid = con.conrelid
            JOIN pg_namespace AS ns ON ns.oid = rel.relnamespace
            WHERE ns.nspname = :schema
            """
        ),
        {"schema": schema},
    )
    return {
        (row.table_name, row.conname, row.kind, _strip_schema(row.definition))
        for row in rows
        if row.table_name not in MIGRATION_ONLY_TABLES
    }


async def _indexes(connection: AsyncConnection, schema: str) -> set[tuple[str, str, str]]:
    rows = await connection.execute(
        text("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = :schema"),
        {"schema": schema},
    )
    return {
        (row.tablename, row.indexname, _strip_schema(row.indexdef))
        for row in rows
        if row.tablename not in MIGRATION_ONLY_TABLES
    }


def _describe_difference(kind: str, migrated: set[tuple], models: set[tuple]) -> str:  # type: ignore[type-arg]
    only_migrated = sorted(str(item) for item in migrated - models)
    only_models = sorted(str(item) for item in models - migrated)
    return (
        f"{kind} differ between migrations and models.\n"
        f"Only in migrations ({len(only_migrated)}):\n  " + "\n  ".join(only_migrated) + "\n"
        f"Only in models ({len(only_models)}):\n  " + "\n  ".join(only_models)
    )


async def test_models_match_migrated_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP SCHEMA IF EXISTS {MODEL_SCHEMA} CASCADE"))
        await connection.execute(text(f"CREATE SCHEMA {MODEL_SCHEMA}"))
        # SET LOCAL lasts only for this transaction, so pooled connections stay clean.
        # Tables go to the first schema; extensions (pgvector's type, pg_trgm's operator
        # class) live in public and must stay resolvable.
        await connection.execute(
            text(f"SET LOCAL search_path TO {MODEL_SCHEMA}, {MIGRATED_SCHEMA}")
        )
        # checkfirst=False: with public on the path, the migrated tables there would look
        # like existing ones and be skipped.
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))

    try:
        async with engine.connect() as connection:
            migrated_columns = await _columns(connection, MIGRATED_SCHEMA)
            model_columns = await _columns(connection, MODEL_SCHEMA)
            migrated_constraints = await _constraints(connection, MIGRATED_SCHEMA)
            model_constraints = await _constraints(connection, MODEL_SCHEMA)
            migrated_indexes = await _indexes(connection, MIGRATED_SCHEMA)
            model_indexes = await _indexes(connection, MODEL_SCHEMA)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA IF EXISTS {MODEL_SCHEMA} CASCADE"))

    # Guard against a vacuous pass: both catalogs must actually have been read.
    assert migrated_columns and migrated_constraints and migrated_indexes

    assert migrated_columns == model_columns, _describe_difference(
        "Columns", migrated_columns, model_columns
    )
    assert migrated_constraints == model_constraints, _describe_difference(
        "Constraints", migrated_constraints, model_constraints
    )
    assert migrated_indexes == model_indexes, _describe_difference(
        "Indexes", migrated_indexes, model_indexes
    )


async def test_every_model_table_exists_after_migration(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
            {"schema": MIGRATED_SCHEMA},
        )
        migrated_tables = {row.tablename for row in rows} - MIGRATION_ONLY_TABLES

    assert migrated_tables == set(Base.metadata.tables)
