from fastapi import APIRouter, status

from app.api.dependencies import PrincipalDep, UserServiceDep
from app.core.exceptions import ErrorResponse
from app.schemas.app import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackResponse,
    responses={
        401: {"model": ErrorResponse, "description": "No valid access token"},
        422: {"model": ErrorResponse, "description": "The message is not valid"},
    },
    summary="Send feedback",
)
async def send_feedback(
    payload: FeedbackRequest, principal: PrincipalDep, users: UserServiceDep
) -> FeedbackResponse:
    feedback = await users.submit_feedback(
        principal,
        message=payload.message,
        platform=payload.platform.value if payload.platform is not None else None,
        app_version=payload.app_version,
    )
    return FeedbackResponse(id=feedback.id, created_at=feedback.created_at)
