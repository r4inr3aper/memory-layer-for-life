import hmac
import ipaddress
from collections.abc import AsyncGenerator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import AppContainer
from app.domain.errors import (
    AccessNotAllowedError,
    AuthenticationNotConfiguredError,
    AuthenticationRequiredError,
    OperatorAccessDeniedError,
)
from app.domain.principal import Principal
from app.services.account import AccountService
from app.services.chat import ChatService
from app.services.chat_turns import ChatTurnService
from app.services.console_queries import ConsoleQueryService
from app.services.diagnostics import DiagnosticsService
from app.services.evaluations import EvaluationService
from app.services.export import ExportService
from app.services.file_capture import FileCapture
from app.services.imports import ImportService
from app.services.ingestion import IngestionService
from app.services.insights import InsightService
from app.services.life_state import LifeStateService
from app.services.memories import MemoryService
from app.services.memory_review import MemoryReviewService
from app.services.notifications import PushService
from app.services.people import PeopleService
from app.services.playground import PlaygroundService
from app.services.processing.replay import ReplayService
from app.services.processing.runner import PipelineRunner
from app.services.queries import MemoryQueryService, ProcessingQueryService
from app.services.reports import ReportService
from app.services.retrieval.engine import RetrievalEngine
from app.services.schedules import ScheduleService
from app.services.source_sync import SourceSyncService
from app.services.tool_connections import ToolConnectionService
from app.services.usage import UsageService
from app.services.users import UserService


def get_container(request: Request) -> AppContainer:
    return cast("AppContainer", request.app.state.container)


ContainerDep = Annotated[AppContainer, Depends(get_container)]


async def get_db_session(container: ContainerDep) -> AsyncGenerator[AsyncSession, None]:
    """One session per request, for reading.

    Services that write own their transactions and do not use this session, so nothing
    is committed here.
    """
    async with container.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_ingestion_service(container: ContainerDep) -> IngestionService:
    return container.ingestion_service


def get_replay_service(container: ContainerDep) -> ReplayService:
    return container.replay_service


def get_pipeline_runner(container: ContainerDep) -> PipelineRunner:
    return container.pipeline_runner


def get_playground_service(container: ContainerDep) -> PlaygroundService:
    return container.playground_service


def get_evaluation_service(container: ContainerDep) -> EvaluationService:
    return container.evaluation_service


def get_diagnostics_service(container: ContainerDep) -> DiagnosticsService:
    return container.diagnostics_service


def get_report_service(container: ContainerDep) -> ReportService:
    return container.report_service


def get_processing_queries(session: SessionDep) -> ProcessingQueryService:
    return ProcessingQueryService(session)


def get_memory_queries(session: SessionDep) -> MemoryQueryService:
    return MemoryQueryService(session)


def get_console_queries(container: ContainerDep, session: SessionDep) -> ConsoleQueryService:
    return ConsoleQueryService(session, timezone_name=container.settings.DEFAULT_TIMEZONE)


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]
ReplayServiceDep = Annotated[ReplayService, Depends(get_replay_service)]
PipelineRunnerDep = Annotated[PipelineRunner, Depends(get_pipeline_runner)]
PlaygroundServiceDep = Annotated[PlaygroundService, Depends(get_playground_service)]
EvaluationServiceDep = Annotated[EvaluationService, Depends(get_evaluation_service)]
DiagnosticsServiceDep = Annotated[DiagnosticsService, Depends(get_diagnostics_service)]
ReportServiceDep = Annotated[ReportService, Depends(get_report_service)]
ProcessingQueriesDep = Annotated[ProcessingQueryService, Depends(get_processing_queries)]
MemoryQueriesDep = Annotated[MemoryQueryService, Depends(get_memory_queries)]
ConsoleQueriesDep = Annotated[ConsoleQueryService, Depends(get_console_queries)]


# --- Signed-in user ------------------------------------------------------------------

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="SupabaseAccessToken",
    description="The access token of the user's Supabase session.",
)


async def get_principal(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The user the request acts for, from their verified Supabase access token.

    Their row is written on first sight, so everything they create has an owner. With an
    access list, anyone not on it is refused before a row exists for them.
    """
    verifier = container.token_verifier
    if verifier is None:
        raise AuthenticationNotConfiguredError
    if credentials is None:
        raise AuthenticationRequiredError("Sign in to continue.")
    principal = await verifier.verify(credentials.credentials)
    allowed = container.settings.ACCESS_ALLOWED_EMAILS
    if allowed and (principal.email is None or principal.email.lower() not in allowed):
        raise AccessNotAllowedError
    # Someone is using the app: background loops may poll at their normal pace while the
    # database is awake for them anyway (app.services.pacing).
    container.pacer.touch()
    await container.user_service.ensure(principal)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


# --- Operator ------------------------------------------------------------------------

_operator_key = APIKeyHeader(
    name="X-Operator-Key",
    auto_error=False,
    scheme_name="OperatorKey",
    description=(
        "Needed only when calling an operator route from another computer; requests from "
        "the computer running the API are allowed without it."
    ),
)


def require_operator(
    request: Request,
    container: ContainerDep,
    key: Annotated[str | None, Depends(_operator_key)],
) -> None:
    """Allow the operator routes only from the computer running the API, or with the
    operator key.

    These routes have no user sign-in (ADR-022) and expose the operator's own data and
    controls, while the API listens on the network so the phone can reach the app's
    routes. Behind a reverse proxy on the same machine, Uvicorn takes the client address
    from the proxy's forwarded header, so "this computer" still means the real client.

    A deployed API accepts only the key: behind a hosting platform's proxy the client
    address is only as trustworthy as the forwarded-header settings, and one permissive
    setting would let anyone claim to be 127.0.0.1.
    """
    settings = container.settings
    configured = settings.OPERATOR_API_KEY
    if configured is not None and key is not None and hmac.compare_digest(key, configured):
        return
    if (
        not settings.is_deployed
        and request.client is not None
        and _is_loopback(request.client.host)
    ):
        return
    raise OperatorAccessDeniedError


def _is_loopback(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def get_user_service(container: ContainerDep) -> UserService:
    return container.user_service


def get_chat_service(container: ContainerDep) -> ChatService:
    return container.chat_service


def get_chat_turn_service(container: ContainerDep) -> ChatTurnService:
    return container.chat_turn_service


def get_schedule_service(container: ContainerDep) -> ScheduleService:
    return container.schedule_service


def get_tool_connection_service(container: ContainerDep) -> ToolConnectionService:
    return container.tool_connection_service


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
ChatTurnServiceDep = Annotated[ChatTurnService, Depends(get_chat_turn_service)]
ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]
ToolConnectionServiceDep = Annotated[ToolConnectionService, Depends(get_tool_connection_service)]


def get_usage_service(container: ContainerDep) -> UsageService:
    return container.usage_service


def get_account_service(container: ContainerDep) -> AccountService:
    return container.account_service


def get_push_service(container: ContainerDep) -> PushService:
    return container.push_service


UsageServiceDep = Annotated[UsageService, Depends(get_usage_service)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
PushServiceDep = Annotated[PushService, Depends(get_push_service)]


def get_retrieval_engine(container: ContainerDep) -> RetrievalEngine:
    return container.retrieval_engine


RetrievalEngineDep = Annotated[RetrievalEngine, Depends(get_retrieval_engine)]


def get_memory_service(container: ContainerDep) -> MemoryService:
    return container.memory_service


def get_memory_review_service(container: ContainerDep) -> MemoryReviewService:
    return container.memory_review_service


def get_people_service(container: ContainerDep) -> PeopleService:
    return container.people_service


def get_export_service(container: ContainerDep) -> ExportService:
    return container.export_service


MemoryServiceDep = Annotated[MemoryService, Depends(get_memory_service)]
MemoryReviewServiceDep = Annotated[MemoryReviewService, Depends(get_memory_review_service)]
PeopleServiceDep = Annotated[PeopleService, Depends(get_people_service)]
ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]


def get_life_state_service(container: ContainerDep) -> LifeStateService:
    return container.life_state_service


LifeStateServiceDep = Annotated[LifeStateService, Depends(get_life_state_service)]


def get_insight_service(container: ContainerDep) -> InsightService:
    return container.insight_service


InsightServiceDep = Annotated[InsightService, Depends(get_insight_service)]


def get_import_service(container: ContainerDep) -> ImportService:
    return container.import_service


def get_file_capture(container: ContainerDep) -> FileCapture:
    return container.file_capture


def get_source_sync_service(container: ContainerDep) -> SourceSyncService:
    return container.source_sync_service


ImportServiceDep = Annotated[ImportService, Depends(get_import_service)]
FileCaptureDep = Annotated[FileCapture, Depends(get_file_capture)]
SourceSyncServiceDep = Annotated[SourceSyncService, Depends(get_source_sync_service)]
