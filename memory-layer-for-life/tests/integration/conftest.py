"""Fixtures for tests that need PostgreSQL.

The schema is built by running the real Alembic migrations, never ``create_all``, so
constraints, triggers, and indexes are exactly what production gets. Every test starts
from empty tables.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.bootstrap import AppContainer, build_container
from app.core.config import Settings
from app.db.base import Base
from app.domain.principal import Principal
from app.integrations.document_reader import DocumentReader
from app.integrations.embeddings.base import Embedder, Reranker
from app.integrations.extraction.base import Extractor
from app.main import create_app
from tests.support.assistant import (
    FakeComposio,
    FakeIdentityAdmin,
    FakePushClient,
    ScriptedAssistantModel,
    StaticTokenVerifier,
)
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock, PipelineHarness, build_harness

PROJECT_ROOT = Path(__file__).resolve().parents[2]

HarnessFactory = Callable[..., PipelineHarness]
AssistantHarnessFactory = Callable[..., AbstractAsyncContextManager["AssistantHarness"]]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.integration)


def assert_is_test_database(database_url: str) -> None:
    """Refuse to run destructive fixtures against anything but a test database."""
    name = make_url(database_url).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to reset database '{name}': integration tests only run against a "
            "database whose name ends with '_test'."
        )


def run_alembic(*arguments: str) -> None:
    """Run the Alembic CLI in a subprocess, as an operator would."""
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(arguments)} failed:\n{completed.stdout}\n{completed.stderr}"
        )


async def reset_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    assert_is_test_database(settings.DATABASE_URL)
    engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True)
    await reset_schema(engine)
    await asyncio.to_thread(run_alembic, "upgrade", "head")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine: AsyncEngine) -> None:
    """Empty every application table before each test."""
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_harness(
    session_factory: async_sessionmaker[AsyncSession], clock: FakeClock
) -> HarnessFactory:
    """Build a real pipeline around a scripted extractor, sharing the test's clock."""

    def factory(extractor: Extractor | None, **options: object) -> PipelineHarness:
        options.setdefault("clock", clock)
        return build_harness(session_factory, extractor, **options)  # type: ignore[arg-type]

    return factory


@dataclass
class ApiHarness:
    """The real application served in-process, with a scripted extractor."""

    client: AsyncClient
    extractor: ScriptedExtractor
    container: AppContainer


@asynccontextmanager
async def _serve(container: AppContainer) -> AsyncIterator[AsyncClient]:
    """Serve the application in-process around an already built container."""
    application = create_app()
    application.state.container = container
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client
    finally:
        await container.aclose()


@pytest_asyncio.fixture
async def api(
    settings: Settings, engine: AsyncEngine, clock: FakeClock
) -> AsyncIterator[ApiHarness]:
    """API with a working pipeline. ``engine`` is requested so the schema is migrated."""
    extractor = ScriptedExtractor()
    container = build_container(settings, extractor=extractor, clock=clock)
    async with _serve(container) as client:
        yield ApiHarness(client=client, extractor=extractor, container=container)


@pytest_asyncio.fixture
async def api_without_extractor(
    settings: Settings, engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    """API as it runs when no provider key is configured."""
    async with _serve(build_container(settings)) as client:
        yield client


@dataclass
class AssistantHarness:
    """The real application with a scripted assistant model, a token verifier that
    knows its own tokens, and an in-memory Composio."""

    client: AsyncClient
    container: AppContainer
    model: ScriptedAssistantModel
    verifier: StaticTokenVerifier
    composio: FakeComposio
    clock: FakeClock
    push: FakePushClient
    identity: FakeIdentityAdmin
    extractor: ScriptedExtractor

    def sign_in(self, principal: Principal) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.verifier.issue(principal)}"}


@pytest_asyncio.fixture
async def assistant_api(
    settings: Settings, engine: AsyncEngine, clock: FakeClock
) -> AsyncIterator[AssistantHarness]:
    async with _assistant_harness(settings, clock, with_model=True) as harness:
        yield harness


@pytest_asyncio.fixture
async def sign_in_only_api(
    settings: Settings, engine: AsyncEngine, clock: FakeClock
) -> AsyncIterator[AssistantHarness]:
    """Sign-in works, but neither a model provider nor Composio is configured."""
    async with _assistant_harness(settings, clock, with_model=False) as harness:
        yield harness


@pytest.fixture
def assistant_api_with(
    settings: Settings, engine: AsyncEngine, clock: FakeClock
) -> AssistantHarnessFactory:
    """Build the assistant app with changed settings, as ``async with factory(...)``.

    ``with_identity=False`` serves it as when the Supabase secret key is not configured;
    ``embedder`` and ``reranker`` stand in for the retrieval providers.
    """

    def factory(
        *,
        with_identity: bool = True,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        document_reader: DocumentReader | None = None,
        **overrides: object,
    ) -> AbstractAsyncContextManager[AssistantHarness]:
        return _assistant_harness(
            settings.model_copy(update=overrides),
            clock,
            with_model=True,
            with_identity=with_identity,
            embedder=embedder,
            reranker=reranker,
            document_reader=document_reader,
        )

    return factory


@asynccontextmanager
async def _assistant_harness(
    settings: Settings,
    clock: FakeClock,
    *,
    with_model: bool,
    with_identity: bool = True,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    document_reader: DocumentReader | None = None,
) -> AsyncIterator[AssistantHarness]:
    model = ScriptedAssistantModel()
    verifier = StaticTokenVerifier()
    composio = FakeComposio()
    push = FakePushClient()
    identity = FakeIdentityAdmin()
    extractor = ScriptedExtractor()
    container = build_container(
        settings,
        extractor=extractor,
        assistant_model=model if with_model else None,
        token_verifier=verifier,
        composio=composio if with_model else None,  # type: ignore[arg-type]
        push_client=push,  # type: ignore[arg-type]
        identity_admin=identity if with_identity else None,  # type: ignore[arg-type]
        embedder=embedder,
        reranker=reranker,
        document_reader=document_reader,
        clock=clock,
    )
    async with _serve(container) as client:
        yield AssistantHarness(
            client=client,
            container=container,
            model=model,
            verifier=verifier,
            composio=composio,
            clock=clock,
            push=push,
            identity=identity,
            extractor=extractor,
        )
