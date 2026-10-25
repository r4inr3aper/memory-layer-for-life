from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.health import HealthService

router = APIRouter()


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness check",
    description="Confirms the application process is responsive.",
)
async def liveness(
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    return HealthResponse(
        status="alive",
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description="Verifies database connectivity.",
    responses={
        503: {"model": ReadinessResponse, "description": "Service unavailable"},
    },
)
async def readiness(
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    service = HealthService(session)
    is_healthy, detail = await service.check_database()

    response = ReadinessResponse(
        status="ready" if is_healthy else "unavailable",
        database="connected" if is_healthy else "disconnected",
        details=detail if not is_healthy else None,
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(),
    )
