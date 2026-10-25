"""Every table denies everyone but its owner.

In Supabase, the public schema is reachable through the Data API with the publishable
key that ships in the mobile app. Row level security without policies closes that path
while the API, which connects as the owner, keeps full access.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base


async def test_every_table_has_row_level_security(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        )
        security = {row.relname: row.relrowsecurity for row in rows}

    assert set(Base.metadata.tables) | {"alembic_version"} == set(security)
    assert [name for name, enabled in security.items() if not enabled] == []


async def test_a_role_that_does_not_own_the_tables_sees_no_rows(engine: AsyncEngine) -> None:
    """What the Data API's roles experience, simulated with a throwaway role."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "INSERT INTO app_users (id, email, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), 'ada@example.com', now(), now())"
                )
            )
            # The grants Supabase gives its Data API roles.
            await connection.execute(text("CREATE ROLE data_api_probe NOLOGIN"))
            await connection.execute(text("GRANT USAGE ON SCHEMA public TO data_api_probe"))
            await connection.execute(text("GRANT SELECT, INSERT ON app_users TO data_api_probe"))
            await connection.execute(text("SET LOCAL ROLE data_api_probe"))

            visible = await connection.scalar(text("SELECT count(*) FROM app_users"))
            owner_view_blocked = visible == 0

            await connection.execute(text("SAVEPOINT before_insert"))
            try:
                await connection.execute(
                    text(
                        "INSERT INTO app_users (id, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), now(), now())"
                    )
                )
                insert_refused = False
            except Exception:
                insert_refused = True
                await connection.execute(text("ROLLBACK TO SAVEPOINT before_insert"))
        finally:
            # Everything above, the role included, is undone.
            await transaction.rollback()

    assert owner_view_blocked
    assert insert_refused
