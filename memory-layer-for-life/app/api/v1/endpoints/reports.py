from fastapi import APIRouter

from app.api.dependencies import ReportServiceDep
from app.api.v1.console_mappers import to_report_response
from app.core.exceptions import ErrorResponse
from app.schemas.console import ReportResponse

router = APIRouter()


@router.get(
    "/{slug}",
    response_model=ReportResponse,
    responses={404: {"model": ErrorResponse, "description": "No such report"}},
    summary="Read a written project report",
    description="A Markdown report kept in the project, such as the Phase 1 report.",
)
async def get_report(slug: str, reports: ReportServiceDep) -> ReportResponse:
    return to_report_response(reports.get(slug))
