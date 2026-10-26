from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import v1_router
from app.bootstrap import AppContainer, build_container
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.request_limits import BodySizeLimitMiddleware
from app.core.request_logging import RequestLoggingMiddleware
from app.services.proactive import ProactiveLoop
from app.services.processing.runner import PipelineLoop
from app.services.retrieval.indexer import IndexLoop
from app.services.schedule_runs import ScheduleLoop
from app.services.source_sync import SourceSyncLoop

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    setup_logging()
    logger.info(
        "application_starting", app_name=settings.APP_NAME, environment=settings.ENVIRONMENT
    )

    # Builds the engine, the provider client, and the pipeline. Nothing here opens a
    # connection or calls a provider.
    container: AppContainer = build_container(settings)
    app.state.container = container
    # Due schedules are dispatched from inside the API process. Several processes may
    # do so at once: each slot is claimed in the database.
    schedule_loop = (
        ScheduleLoop(
            container.schedule_dispatcher,
            interval_seconds=settings.SCHEDULER_POLL_SECONDS,
            pacer=container.pacer,
        )
        if settings.SCHEDULER_ENABLED
        else None
    )
    if schedule_loop is not None:
        schedule_loop.start()
    # New and changed memories are embedded in the background, whatever created them.
    index_loop = (
        IndexLoop(
            container.memory_indexer,
            interval_seconds=settings.RETRIEVAL_INDEXER_INTERVAL_SECONDS,
            pacer=container.pacer,
        )
        if settings.RETRIEVAL_INDEXER_ENABLED and container.memory_indexer is not None
        else None
    )
    if index_loop is not None:
        index_loop.start()
    # Quiet chats are captured as memories, and failed and interrupted memory saves are
    # retried, in the background (ADR-044, ADR-048).
    pipeline_loop = (
        PipelineLoop(
            container.pipeline_runner,
            interval_seconds=settings.PIPELINE_WORKER_INTERVAL_SECONDS,
            batch_size=settings.PIPELINE_WORKER_BATCH_SIZE,
            # Chats are read for memories once they go quiet (ADR-048).
            capture=container.memory_capture,
            pacer=container.pacer,
        )
        if settings.PIPELINE_WORKER_ENABLED and container.pipeline_runner.can_process
        else None
    )
    if pipeline_loop is not None:
        pipeline_loop.start()
    # Reminders and daily briefs (ADR-045).
    proactive_loop = (
        ProactiveLoop(
            container.proactive_dispatcher,
            interval_seconds=settings.PROACTIVE_POLL_SECONDS,
            pacer=container.pacer,
        )
        if settings.PROACTIVE_ENABLED
        else None
    )
    if proactive_loop is not None:
        proactive_loop.start()
    # Connected apps as memory sources (ADR-047).
    source_loop = (
        SourceSyncLoop(
            container.source_sync_service,
            interval_seconds=settings.SOURCE_SYNC_INTERVAL_SECONDS,
        )
        if settings.SOURCE_SYNC_ENABLED and container.tool_connection_service.available
        else None
    )
    if source_loop is not None:
        source_loop.start()
    logger.info(
        "application_ready",
        pipeline_version=container.fingerprint.pipeline_version,
        extractor_configured=container.pipeline_runner.can_process,
        console_ui=settings.console_ui_dir.is_dir(),
        sign_in_configured=container.token_verifier is not None,
        assistant_configured=container.chat_turn_service.available,
        apps_configured=container.tool_connection_service.available,
        scheduler=schedule_loop is not None,
        semantic_retrieval=container.retrieval_engine.semantic_available,
        memory_indexer=index_loop is not None,
        pipeline_worker=pipeline_loop is not None,
        proactive=proactive_loop is not None,
        source_sync=source_loop is not None,
        database_sleeps_between_ticks=container.pacer.saves_database,
    )

    yield

    if source_loop is not None:
        await source_loop.stop()
    if proactive_loop is not None:
        await proactive_loop.stop()
    if pipeline_loop is not None:
        await pipeline_loop.stop()
    if index_loop is not None:
        await index_loop.stop()
    if schedule_loop is not None:
        await schedule_loop.stop()
    await container.aclose()
    logger.info("application_shutdown_complete")


def mount_console_ui(app: FastAPI, directory: Path) -> None:
    """Serve the built web console at the root, when it has been built.

    The API routes are registered first, so they take precedence. The console uses hash
    routing, so every page of it is reached through its index file.
    """
    if directory.is_dir():
        app.mount("/", StaticFiles(directory=directory, html=True), name="console-ui")


def create_app() -> FastAPI:
    settings = get_settings()

    docs = settings.api_docs_enabled
    app = FastAPI(
        title="Second Brain API",
        description="Personal Second Brain - Memory Layer for Life",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Middleware. The last one added is the outermost, so CORS answers preflight requests
    # before anything is logged, and an oversized body is refused inside the logging.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BYTES)
    app.add_middleware(RequestLoggingMiddleware, api_prefix=settings.API_V1_PREFIX)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    register_exception_handlers(app)

    # Routers
    app.include_router(v1_router, prefix=settings.API_V1_PREFIX)

    mount_console_ui(app, settings.console_ui_dir)
    return app


app = create_app()
