import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    ChatServiceDep,
    ChatTurnServiceDep,
    PrincipalDep,
    ScheduleServiceDep,
)
from app.api.v1.app_mappers import (
    to_message_response,
    to_schedule_response,
    to_stream_event,
    to_thread_response,
)
from app.core.exceptions import ErrorResponse
from app.domain.enums import ThreadKind
from app.integrations.assistant.base import Attachment
from app.schemas.app import (
    ChatMessageResponse,
    ConfirmProposalResponse,
    CreateThreadRequest,
    SendMessageRequest,
    ThreadResponse,
)
from app.schemas.common import Page, PageParams
from app.services.assistant.context import TurnEvent

router = APIRouter()

# Well under the idle timeouts of common proxies and load balancers (60 s and up).
STREAM_KEEPALIVE_SECONDS: Final = 15.0

# FastAPI's type for documented responses.
Responses = dict[int | str, dict[str, Any]]

_NOT_FOUND: Responses = {
    404: {"model": ErrorResponse, "description": "No such thread for this user"}
}
_AUTH: Responses = {
    401: {"model": ErrorResponse, "description": "No valid access token"},
    503: {"model": ErrorResponse, "description": "User sign-in or the model is not configured"},
}


@router.get(
    "",
    response_model=Page[ThreadResponse],
    responses=_AUTH,
    summary="List threads",
    description="Most recent activity first.",
)
async def list_threads(
    principal: PrincipalDep,
    chat: ChatServiceDep,
    page: Annotated[PageParams, Depends()],
    kind: ThreadKind | None = None,
) -> Page[ThreadResponse]:
    threads, total = await chat.list_threads(
        principal, kind=kind, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[to_thread_response(thread) for thread in threads],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ThreadResponse,
    responses=_AUTH,
    summary="Start a side thread",
)
async def create_thread(
    payload: CreateThreadRequest, principal: PrincipalDep, chat: ChatServiceDep
) -> ThreadResponse:
    return to_thread_response(await chat.create_side_thread(principal, title=payload.title))


@router.post(
    "/main",
    response_model=ThreadResponse,
    responses=_AUTH,
    summary="Get the main thread",
    description="Returns the user's main thread, creating it on first use. Idempotent.",
)
async def ensure_main_thread(principal: PrincipalDep, chat: ChatServiceDep) -> ThreadResponse:
    return to_thread_response(await chat.ensure_main_thread(principal))


@router.get(
    "/{thread_id}",
    response_model=ThreadResponse,
    responses={**_AUTH, **_NOT_FOUND},
    summary="Show one thread",
)
async def get_thread(
    thread_id: uuid.UUID, principal: PrincipalDep, chat: ChatServiceDep
) -> ThreadResponse:
    return to_thread_response(await chat.get_thread(principal, thread_id))


@router.delete(
    "/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **_AUTH,
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The main thread cannot be deleted"},
    },
    summary="Delete a side thread and its messages",
)
async def delete_thread(
    thread_id: uuid.UUID, principal: PrincipalDep, chat: ChatServiceDep
) -> Response:
    await chat.delete_thread(principal, thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{thread_id}/messages",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **_AUTH,
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "A reply is running in this thread"},
    },
    summary="Clear a thread",
    description="Deletes every message of the thread and keeps the thread.",
)
async def clear_messages(
    thread_id: uuid.UUID, principal: PrincipalDep, chat: ChatServiceDep
) -> Response:
    await chat.clear_messages(principal, thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{thread_id}/messages",
    response_model=Page[ChatMessageResponse],
    responses={**_AUTH, **_NOT_FOUND},
    summary="List a thread's messages",
    description=(
        "The most recent `limit` messages, oldest first. `offset` skips that many of the "
        "newest messages, to page back in time."
    ),
)
async def list_messages(
    thread_id: uuid.UUID,
    principal: PrincipalDep,
    chat: ChatServiceDep,
    page: Annotated[PageParams, Depends()],
) -> Page[ChatMessageResponse]:
    messages, total = await chat.list_messages(
        principal, thread_id, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[to_message_response(message) for message in messages],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/{thread_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Newline-delimited JSON events. `turn_started` carries the stored user "
                "message; then any of `text_delta`, `tool_started`, `browser`, and "
                "`connect_link`; then `final` with the stored reply, or `error`. Blank "
                "lines are keep-alives sent while the reply is quiet; skip them."
            ),
            "content": {"application/x-ndjson": {}},
        },
        **_AUTH,
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "A reply is already running here"},
        422: {"model": ErrorResponse, "description": "The message or a file is not valid"},
        429: {"model": ErrorResponse, "description": "Daily prompt limit reached"},
    },
    summary="Send a message and stream the reply",
    description=(
        "Stores the message, then streams the assistant's reply as it is written. The "
        "reply is stored when it ends, even if the client disconnects first."
    ),
)
async def send_message(
    thread_id: uuid.UUID,
    payload: SendMessageRequest,
    principal: PrincipalDep,
    turns: ChatTurnServiceDep,
) -> StreamingResponse:
    events = await turns.start(
        principal,
        thread_id,
        payload.content,
        timezone_name=payload.timezone,
        attachments=[
            Attachment(name=item.name, media_type=item.media_type, data=item.decoded())
            for item in payload.attachments
        ],
    )
    return StreamingResponse(
        _ndjson(events),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _ndjson(
    events: AsyncIterator[TurnEvent], *, keepalive_seconds: float = STREAM_KEEPALIVE_SECONDS
) -> AsyncIterator[bytes]:
    """One JSON event per line, and a blank line whenever the reply has been quiet for
    ``keepalive_seconds``.

    A tool can run for minutes without an event (a browser task, say), and the proxies in
    front of a hosted API close connections that send nothing. The app skips blank lines.
    The pending read is never cancelled by the wait, only when the response ends.
    """
    iterator = aiter(events)

    async def next_event() -> TurnEvent:
        return await anext(iterator)

    pending: asyncio.Task[TurnEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(next_event())
            done, _ = await asyncio.wait({pending}, timeout=keepalive_seconds)
            if not done:
                yield b"\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield (to_stream_event(event).model_dump_json() + "\n").encode()
    finally:
        if pending is not None and not pending.done():
            pending.cancel()


@router.post(
    "/{thread_id}/messages/{message_id}/proposal/confirm",
    status_code=status.HTTP_201_CREATED,
    response_model=ConfirmProposalResponse,
    responses={
        **_AUTH,
        404: {"model": ErrorResponse, "description": "No such thread or message"},
        409: {"model": ErrorResponse, "description": "No pending proposal on this message"},
    },
    summary="Confirm a proposed schedule",
    description="Creates the schedule exactly as proposed, and marks the proposal confirmed.",
)
async def confirm_proposal(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: PrincipalDep,
    schedules: ScheduleServiceDep,
) -> ConfirmProposalResponse:
    task, message = await schedules.confirm_proposal(principal, thread_id, message_id)
    return ConfirmProposalResponse(
        message=to_message_response(message), schedule=to_schedule_response(task, 0)
    )


@router.post(
    "/{thread_id}/messages/{message_id}/proposal/dismiss",
    response_model=ChatMessageResponse,
    responses={
        **_AUTH,
        404: {"model": ErrorResponse, "description": "No such thread or message"},
        409: {"model": ErrorResponse, "description": "No pending proposal on this message"},
    },
    summary="Dismiss a proposed schedule",
)
async def dismiss_proposal(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    principal: PrincipalDep,
    chat: ChatServiceDep,
) -> ChatMessageResponse:
    return to_message_response(await chat.dismiss_proposal(principal, thread_id, message_id))
