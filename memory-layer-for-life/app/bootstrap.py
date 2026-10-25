"""Composition root: the process-wide components, built once at startup.

This is the only module that knows which concrete classes implement the application.
Everything else receives what it needs. It sits at the top of the package so that no
lower layer has to import it.
"""

from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.core.config import PROJECT_ROOT, Settings
from app.db.session import create_engine, create_session_factory
from app.domain.run_state import RetryPolicy
from app.domain.versions import PipelineFingerprint
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.anthropic_ping import AnthropicConnectionCheck
from app.integrations.assistant.anthropic_model import AnthropicAssistantModel
from app.integrations.assistant.base import AssistantModel
from app.integrations.browserbase import BrowserbaseClient
from app.integrations.composio import ComposioClient
from app.integrations.document_reader import AnthropicDocumentReader, DocumentReader
from app.integrations.embeddings.base import Embedder, Reranker
from app.integrations.embeddings.voyage import VoyageClient
from app.integrations.expo_push import ExpoPushClient
from app.integrations.extraction.base import Extractor
from app.integrations.extraction.factory import (
    AnthropicExtractorFactory,
    ExtractorFactory,
    FixedExtractorFactory,
    configured_extractor_descriptor,
)
from app.integrations.supabase_admin import SupabaseAdminClient
from app.integrations.supabase_auth import (
    SupabaseTokenVerifier,
    TokenVerifier,
    http_jwks_fetcher,
)
from app.services.account import AccountService
from app.services.assistant.tools import AssistantToolbox
from app.services.background import BackgroundWork
from app.services.chat import ChatService
from app.services.chat_turns import ChatTurnService, TurnLimits
from app.services.diagnostics import DiagnosticsService, ProviderCheck
from app.services.evaluations import EvaluationService
from app.services.export import ExportService
from app.services.file_capture import FileCapture
from app.services.imports import ImportService
from app.services.ingestion import IngestionLimits, IngestionService
from app.services.insights import InsightService
from app.services.life_state import LifeStateService
from app.services.llm_call_log import LlmCallLog
from app.services.memories import MemoryService
from app.services.memory_capture import MemoryCapture
from app.services.memory_review import MemoryReviewService
from app.services.notifications import PushService
from app.services.pacing import BackgroundPacer
from app.services.people import PeopleService
from app.services.playground import PlaygroundLimits, PlaygroundService
from app.services.proactive import ProactiveDispatcher
from app.services.processing.replay import ReplayService
from app.services.processing.runner import PipelineRunner, RunnerConfig
from app.services.reports import ReportService
from app.services.retrieval.engine import RetrievalConfig, RetrievalEngine
from app.services.retrieval.indexer import MemoryIndexer
from app.services.schedule_runs import ScheduleDispatcher, ScheduleRunner
from app.services.schedules import ScheduleService
from app.services.source_sync import SourceSyncService
from app.services.tool_connections import ToolConnectionService
from app.services.usage import UsageService
from app.services.users import UserService
from evaluation.judge import AnthropicJudgeFactory, FixedJudgeFactory, Judge, JudgeFactory


@dataclass(frozen=True, slots=True)
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    anthropic_manager: AnthropicClientManager
    fingerprint: PipelineFingerprint
    pipeline_runner: PipelineRunner
    ingestion_service: IngestionService
    replay_service: ReplayService
    playground_service: PlaygroundService
    evaluation_service: EvaluationService
    diagnostics_service: DiagnosticsService
    report_service: ReportService
    # The assistant app.
    http: httpx.AsyncClient
    background: BackgroundWork
    token_verifier: TokenVerifier | None
    user_service: UserService
    chat_service: ChatService
    chat_turn_service: ChatTurnService
    schedule_service: ScheduleService
    schedule_dispatcher: ScheduleDispatcher
    tool_connection_service: ToolConnectionService
    usage_service: UsageService
    account_service: AccountService
    push_service: PushService
    retrieval_engine: RetrievalEngine
    # None without an embedding provider: there is nothing to index then.
    memory_indexer: MemoryIndexer | None
    # Memories as their owner manages them.
    memory_service: MemoryService
    memory_review_service: MemoryReviewService
    people_service: PeopleService
    export_service: ExportService
    # Life state, reminders, and the daily brief.
    life_state_service: LifeStateService
    proactive_dispatcher: ProactiveDispatcher
    insight_service: InsightService
    # New memory sources.
    import_service: ImportService
    file_capture: FileCapture
    source_sync_service: SourceSyncService
    # How the background loops pace themselves; signed-in requests mark activity.
    pacer: BackgroundPacer

    async def aclose(self) -> None:
        """Stop background work, then release the provider clients and the connections."""
        await self.background.shutdown()
        await self.evaluation_service.shutdown()
        await self.anthropic_manager.close()
        await self.http.aclose()
        await self.engine.dispose()


def runner_config(settings: Settings) -> RunnerConfig:
    return RunnerConfig(
        retry_policy=RetryPolicy(
            max_attempts=settings.PIPELINE_MAX_ATTEMPTS,
            base_delay_seconds=settings.PIPELINE_RETRY_BASE_SECONDS,
            max_delay_seconds=settings.PIPELINE_RETRY_MAX_SECONDS,
        ),
        lease=timedelta(seconds=settings.PIPELINE_RUN_LEASE_SECONDS),
        timezone_name=settings.DEFAULT_TIMEZONE,
    )


def build_container(
    settings: Settings,
    *,
    extractor: Extractor | None = None,
    judge: Judge | None = None,
    provider_check: ProviderCheck | None = None,
    assistant_model: AssistantModel | None = None,
    token_verifier: TokenVerifier | None = None,
    composio: ComposioClient | None = None,
    browser: BrowserbaseClient | None = None,
    push_client: ExpoPushClient | None = None,
    identity_admin: SupabaseAdminClient | None = None,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    document_reader: DocumentReader | None = None,
    clock: Clock = utc_now,
) -> AppContainer:
    """Build every shared component. No network call is made here.

    ``extractor`` replaces the configured provider for every use, including test calls
    and evaluations, and ``judge`` replaces the evaluation judge. Tests use them to run
    the real services with deterministic doubles. ``provider_check`` replaces the
    connection check in the same way. ``assistant_model``, ``token_verifier``,
    ``composio``, and ``browser`` replace the assistant app's model, sign-in check, and
    integrations; ``embedder`` and ``reranker`` replace retrieval's providers. Each is
    otherwise built from the settings when they configure it.
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    # Every model call is reported here and written to the call log.
    observer = AnthropicCallObserver(LlmCallLog(session_factory), clock=clock)

    anthropic_manager = AnthropicClientManager()
    extractors: ExtractorFactory
    judges: JudgeFactory
    active_extractor: Extractor | None
    if extractor is None:
        anthropic_manager.initialize(settings)
        extractors = AnthropicExtractorFactory(settings, anthropic_manager, observer)
        judges = AnthropicJudgeFactory(anthropic_manager, observer)
        active_extractor = extractors.build()
        descriptor = configured_extractor_descriptor(settings)
    else:
        extractors = FixedExtractorFactory(extractor)
        judges = FixedJudgeFactory(judge)
        active_extractor = extractor
        descriptor = extractor.descriptor

    fingerprint = PipelineFingerprint.for_extractor(descriptor)

    # --- The assistant app ------------------------------------------------------------
    # One HTTP client per process for Supabase, Composio, and Browserbase.
    http = httpx.AsyncClient(timeout=settings.INTEGRATION_TIMEOUT_SECONDS)
    background = BackgroundWork()
    if token_verifier is None:
        token_verifier = _supabase_verifier(settings, http)
    if composio is None and settings.COMPOSIO_API_KEY is not None:
        composio = ComposioClient(
            http, api_key=settings.COMPOSIO_API_KEY, base_url=settings.COMPOSIO_BASE_URL
        )
    if browser is None and settings.BROWSERBASE_API_KEY is not None:
        browser = BrowserbaseClient(
            http, api_key=settings.BROWSERBASE_API_KEY, base_url=settings.BROWSERBASE_BASE_URL
        )
    if assistant_model is None and anthropic_manager.client is not None:
        assistant_model = AnthropicAssistantModel(
            anthropic_manager.client,
            model=settings.assistant_model,
            effort=settings.ASSISTANT_EFFORT,
            max_tokens=settings.ASSISTANT_MAX_TOKENS,
            observer=observer,
        )
    tool_connection_service = ToolConnectionService(
        session_factory,
        composio,
        auth_config_overrides=settings.COMPOSIO_AUTH_CONFIGS,
        clock=clock,
    )
    # --- Memory retrieval ---------------------------------------------------------------
    if embedder is None and settings.VOYAGE_API_KEY is not None:
        voyage = VoyageClient(
            http,
            api_key=settings.VOYAGE_API_KEY,
            embedding_model=settings.EMBEDDING_MODEL,
            dimensions=settings.EMBEDDING_DIMENSIONS,
            recorder=LlmCallLog(session_factory),
            rerank_model=settings.RETRIEVAL_RERANK_MODEL,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            base_url=settings.VOYAGE_BASE_URL,
            clock=clock,
        )
        embedder = voyage
        if reranker is None and voyage.can_rerank:
            reranker = voyage
    retrieval_engine = RetrievalEngine(
        session_factory,
        embedder=embedder,
        reranker=reranker,
        config=RetrievalConfig(min_semantic_similarity=settings.RETRIEVAL_MIN_SEMANTIC_SIMILARITY),
        clock=clock,
    )
    memory_indexer = (
        MemoryIndexer(
            session_factory, embedder, batch_size=settings.EMBEDDING_BATCH_SIZE, clock=clock
        )
        if embedder is not None
        else None
    )

    life_state_service = LifeStateService(
        session_factory, default_timezone=settings.DEFAULT_TIMEZONE, clock=clock
    )
    toolbox = AssistantToolbox(
        connections=tool_connection_service,
        composio=composio,
        browser=browser,
        browser_timeout_seconds=settings.BROWSERBASE_RUN_TIMEOUT_SECONDS,
        memories=retrieval_engine,
        life=life_state_service,
        clock=clock,
    )
    usage_service = UsageService(
        session_factory,
        daily_prompt_limit=settings.ASSISTANT_DAILY_PROMPT_LIMIT,
        currency=settings.USAGE_CURRENCY,
        currency_per_usd=settings.USAGE_CURRENCY_PER_USD,
        clock=clock,
    )
    if push_client is None and settings.PUSH_NOTIFICATIONS_ENABLED:
        push_client = ExpoPushClient(http, access_token=settings.EXPO_PUSH_ACCESS_TOKEN)
    push_service = PushService(session_factory, push_client, clock=clock)
    if (
        identity_admin is None
        and settings.SUPABASE_URL is not None
        and settings.SUPABASE_SECRET_KEY is not None
    ):
        identity_admin = SupabaseAdminClient(
            http, supabase_url=settings.SUPABASE_URL, secret_key=settings.SUPABASE_SECRET_KEY
        )
    user_service = UserService(session_factory, clock=clock)
    schedule_runner = ScheduleRunner(
        session_factory,
        model=assistant_model,
        toolbox=toolbox,
        connections=tool_connection_service,
        usage=usage_service,
        push=push_service,
        max_steps=settings.ASSISTANT_MAX_STEPS,
        clock=clock,
    )

    pipeline_runner = PipelineRunner(
        session_factory, active_extractor, config=runner_config(settings), clock=clock
    )
    ingestion_service = IngestionService(
        session_factory,
        fingerprint=fingerprint,
        limits=IngestionLimits(
            max_unit_messages=settings.INGESTION_MAX_UNIT_MESSAGES,
            max_batch_units=settings.INGESTION_MAX_BATCH_UNITS,
            max_content_chars=settings.INGESTION_MAX_CONTENT_CHARS,
        ),
        clock=clock,
    )
    if document_reader is None and anthropic_manager.client is not None:
        document_reader = AnthropicDocumentReader(
            anthropic_manager.client, model=settings.assistant_model, observer=observer
        )
    memory_capture = MemoryCapture(
        session_factory,
        ingestion=ingestion_service,
        runner=pipeline_runner,
        background=background,
        enabled=settings.MEMORY_CAPTURE_ENABLED,
    )

    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        anthropic_manager=anthropic_manager,
        fingerprint=fingerprint,
        pipeline_runner=pipeline_runner,
        ingestion_service=ingestion_service,
        replay_service=ReplayService(session_factory, fingerprint=fingerprint, clock=clock),
        playground_service=PlaygroundService(
            session_factory,
            extractors,
            default_model=settings.ANTHROPIC_MODEL,
            default_effort=settings.EXTRACTION_EFFORT,
            default_timezone=settings.DEFAULT_TIMEZONE,
            limits=PlaygroundLimits(
                max_messages=settings.INGESTION_MAX_UNIT_MESSAGES,
                max_content_chars=settings.INGESTION_MAX_CONTENT_CHARS,
            ),
            clock=clock,
        ),
        evaluation_service=EvaluationService(
            session_factory,
            extractors,
            judges,
            dataset_path=settings.evaluation_dataset_path,
            default_model=settings.ANTHROPIC_MODEL,
            default_effort=settings.EXTRACTION_EFFORT,
            stale_after=timedelta(seconds=settings.EVALUATION_STALE_AFTER_SECONDS),
            clock=clock,
        ),
        diagnostics_service=DiagnosticsService(
            session_factory,
            provider_check or AnthropicConnectionCheck(anthropic_manager, observer),
            default_model=settings.ANTHROPIC_MODEL,
        ),
        report_service=ReportService(PROJECT_ROOT),
        http=http,
        background=background,
        token_verifier=token_verifier,
        user_service=user_service,
        chat_service=ChatService(
            session_factory,
            composio=composio,
            connections=tool_connection_service,
            clock=clock,
        ),
        chat_turn_service=ChatTurnService(
            session_factory,
            model=assistant_model,
            toolbox=toolbox,
            background=background,
            usage=usage_service,
            capture=memory_capture,
            max_steps=settings.ASSISTANT_MAX_STEPS,
            limits=TurnLimits(
                max_message_chars=settings.CHAT_MAX_MESSAGE_CHARS,
                history_messages=settings.ASSISTANT_HISTORY_MESSAGES,
                max_attachments=settings.CHAT_MAX_ATTACHMENTS,
                max_attachment_bytes=settings.CHAT_MAX_ATTACHMENT_BYTES,
                lease=timedelta(seconds=settings.CHAT_TURN_LEASE_SECONDS),
            ),
            clock=clock,
        ),
        schedule_service=ScheduleService(
            session_factory,
            schedule_runner,
            background,
            connections=tool_connection_service,
            clock=clock,
        ),
        schedule_dispatcher=ScheduleDispatcher(
            session_factory,
            schedule_runner,
            batch_size=settings.SCHEDULER_BATCH_SIZE,
            concurrency=settings.SCHEDULER_CONCURRENCY,
            stale_after=timedelta(seconds=settings.SCHEDULE_RUN_STALE_SECONDS),
            missed_grace=timedelta(seconds=settings.SCHEDULE_MISSED_GRACE_SECONDS),
            clock=clock,
        ),
        tool_connection_service=tool_connection_service,
        usage_service=usage_service,
        account_service=AccountService(
            session_factory,
            users=user_service,
            connections=tool_connection_service,
            identity=identity_admin,
        ),
        push_service=push_service,
        retrieval_engine=retrieval_engine,
        memory_indexer=memory_indexer,
        memory_service=MemoryService(session_factory, clock=clock),
        memory_review_service=MemoryReviewService(
            session_factory,
            space=embedder.space if embedder is not None else None,
            clock=clock,
        ),
        people_service=PeopleService(session_factory, clock=clock),
        export_service=ExportService(session_factory, clock=clock),
        life_state_service=life_state_service,
        insight_service=InsightService(
            session_factory, default_timezone=settings.DEFAULT_TIMEZONE, clock=clock
        ),
        import_service=ImportService(
            session_factory,
            ingestion_service,
            default_timezone=settings.DEFAULT_TIMEZONE,
            extraction_model=settings.ANTHROPIC_MODEL,
            currency=settings.USAGE_CURRENCY,
            currency_per_usd=settings.USAGE_CURRENCY_PER_USD,
            clock=clock,
        ),
        file_capture=FileCapture(
            session_factory,
            document_reader,
            ingestion=ingestion_service,
            runner=pipeline_runner,
            background=background,
            usage=usage_service,
            max_bytes=settings.CHAT_MAX_ATTACHMENT_BYTES,
            default_timezone=settings.DEFAULT_TIMEZONE,
            clock=clock,
        ),
        source_sync_service=SourceSyncService(
            session_factory, composio, default_timezone=settings.DEFAULT_TIMEZONE, clock=clock
        ),
        proactive_dispatcher=ProactiveDispatcher(
            session_factory,
            push_service,
            default_timezone=settings.DEFAULT_TIMEZONE,
            clock=clock,
        ),
        pacer=BackgroundPacer(
            idle_interval=settings.BACKGROUND_IDLE_INTERVAL_SECONDS,
            active_window=settings.BACKGROUND_ACTIVE_WINDOW_SECONDS,
            clock=clock,
        ),
    )


def _supabase_verifier(settings: Settings, http: httpx.AsyncClient) -> TokenVerifier | None:
    """The verifier for the configured Supabase project, or None without one."""
    issuer = settings.supabase_issuer
    jwks_url = settings.supabase_jwks_url
    if issuer is None or jwks_url is None:
        return None
    return SupabaseTokenVerifier(
        http_jwks_fetcher(http, jwks_url),
        issuer=issuer,
        audience=settings.SUPABASE_JWT_AUDIENCE,
        cache_seconds=settings.SUPABASE_JWKS_CACHE_SECONDS,
    )
