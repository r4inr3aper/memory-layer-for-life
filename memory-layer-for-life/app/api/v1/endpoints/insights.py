"""The signed-in user's insights, and feedback on them."""

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.dependencies import InsightServiceDep, PrincipalDep
from app.core.exceptions import ErrorResponse
from app.schemas.insights import InsightFeedbackRequest, InsightResponse, InsightsResponse

router = APIRouter()

Responses = dict[int | str, dict[str, Any]]

_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in is not configured"},
}


@router.get(
    "",
    response_model=InsightsResponse,
    responses=_AUTH,
    summary="Show what my memories say over time",
    description=(
        "Money noted this month, people on the user's mind or gone quiet, how much of what "
        "they plan gets done, quiet goals, and recurring themes. Computed from the user's "
        "own memories without any model; each names the memories it rests on. Insights "
        "marked not useful are left out for their period."
    ),
)
async def list_insights(principal: PrincipalDep, insights: InsightServiceDep) -> InsightsResponse:
    found = await insights.list_insights(principal)
    return InsightsResponse(
        items=[
            InsightResponse(
                key=insight.key,
                kind=insight.kind,
                title=insight.title,
                body=insight.body,
                memory_ids=list(insight.memory_ids),
                target=insight.target,
                target_id=insight.target_id,
            )
            for insight in found
        ]
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_AUTH, 422: {"model": ErrorResponse, "description": "Not valid feedback"}},
    summary="Say whether an insight helped",
    description="A later answer replaces an earlier one. Not useful hides it for its period.",
)
async def give_feedback(
    payload: InsightFeedbackRequest, principal: PrincipalDep, insights: InsightServiceDep
) -> Response:
    await insights.record_feedback(principal, payload.key, payload.kind, useful=payload.useful)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
