"""Turns service results of the assistant app into API responses."""

from zoneinfo import ZoneInfo

from app.domain.enums import (
    ChatRole,
    ScheduleDelivery,
    ScheduleFrequency,
    ScheduleRunStatus,
    ScheduleRunTrigger,
    ScheduleStatus,
    Weekday,
)
from app.models.app_user import AppUser
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.schemas.app import (
    ActivityItemResponse,
    BrowserEvent,
    ChatMessageResponse,
    ConnectLinkEvent,
    ErrorEvent,
    FinalEvent,
    MeResponse,
    ScheduleResponse,
    ScheduleRunResponse,
    TextDeltaEvent,
    ThreadResponse,
    ToolActionResponse,
    ToolResponse,
    ToolStartedEvent,
    TurnStartedEvent,
    TurnStreamEvent,
    UsageHistoryResponse,
    UsagePeriodResponse,
    UsageResponse,
)
from app.schemas.message_metadata import MessageMetadata
from app.services.assistant.context import (
    BrowserUpdate,
    ConnectLinkShown,
    TextDelta,
    ToolStarted,
    TurnEvent,
    TurnFailed,
    TurnFinished,
    TurnStarted,
)
from app.services.schedules import ActivityEntry
from app.services.tool_connections import ToolView
from app.services.usage import UsageHistory, UsageReport


def to_usage_history_response(history: UsageHistory) -> UsageHistoryResponse:
    return UsageHistoryResponse(
        granularity=history.granularity,
        currency=history.currency,
        periods=[
            UsagePeriodResponse(
                start=period.start,
                prompts=period.prompts,
                cost_usd=period.cost_usd,
                cost=period.cost,
                input_tokens=period.input_tokens,
                output_tokens=period.output_tokens,
            )
            for period in history.periods
        ],
        total_cost_usd=history.total_cost_usd,
        total_cost=history.total_cost,
        total_prompts=history.total_prompts,
    )


def to_me_response(user: AppUser) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        assistant_name=user.assistant_name,
        assistant_subtitle=user.assistant_subtitle,
        assistant_icon=user.assistant_icon,
        assistant_color=user.assistant_color,
        notifications_enabled=user.notifications_enabled,
        memory_capture_enabled=user.memory_capture_enabled,
        timezone=user.timezone,
        brief_enabled=user.brief_enabled,
        brief_time=f"{user.brief_time:%H:%M}",
        reminders_enabled=user.reminders_enabled,
        quiet_hours_start=(
            f"{user.quiet_hours_start:%H:%M}" if user.quiet_hours_start is not None else None
        ),
        quiet_hours_end=f"{user.quiet_hours_end:%H:%M}"
        if user.quiet_hours_end is not None
        else None,
        created_at=user.created_at,
    )


def to_usage_response(report: UsageReport) -> UsageResponse:
    return UsageResponse(
        day=report.day,
        resets_at=report.resets_at,
        prompts_used=report.prompts_used,
        prompt_limit=report.prompt_limit,
        prompts_remaining=report.prompts_remaining,
        chat_messages=report.chat_messages,
        scheduled_runs=report.scheduled_runs,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        estimated_cost_usd=report.estimated_cost_usd,
        currency=report.currency,
        estimated_cost=report.estimated_cost,
    )


def to_activity_response(entry: ActivityEntry) -> ActivityItemResponse:
    run, task = entry.run, entry.task
    return ActivityItemResponse(
        run_id=run.id,
        scheduled_task_id=task.id,
        title=task.title,
        trigger=ScheduleRunTrigger(run.trigger),
        status=ScheduleRunStatus(run.status),
        summary=run.summary,
        error_message=run.error_message,
        delivery=ScheduleDelivery(task.delivery),
        finished_at=run.finished_at,
        thread_id=entry.thread_id,
        chat_message_id=run.chat_message_id,
    )


def to_thread_response(thread: ChatThread) -> ThreadResponse:
    return ThreadResponse.model_validate(thread)


def to_message_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        thread_id=message.thread_id,
        role=ChatRole(message.role),
        content=message.content,
        metadata=MessageMetadata.from_json(message.metadata_),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def to_stream_event(event: TurnEvent) -> TurnStreamEvent:
    match event:
        case TurnStarted(user_message=message):
            return TurnStartedEvent(user_message=to_message_response(message))
        case TextDelta(text=text):
            return TextDeltaEvent(text=text)
        case ToolStarted(tool=tool, label=label):
            return ToolStartedEvent(tool=tool, label=label)
        case BrowserUpdate(preview=preview):
            return BrowserEvent(browser_preview=preview)
        case ConnectLinkShown(link=link):
            return ConnectLinkEvent(connect_link=link)
        case TurnFinished(message=message):
            return FinalEvent(message=to_message_response(message))
        case TurnFailed(error_code=code, message=text):
            return ErrorEvent(error_code=code, message=text)


def to_schedule_response(task: ScheduledTask, run_count: int) -> ScheduleResponse:
    return ScheduleResponse(
        id=task.id,
        title=task.title,
        original_prompt=task.original_prompt,
        task=task.task,
        frequency=ScheduleFrequency(task.frequency),
        local_time=f"{task.local_time:%H:%M}",
        weekdays=[Weekday(day) for day in task.weekdays or ()],
        day_of_month=task.day_of_month,
        start_date=task.start_date,
        interval_hours=task.interval_hours,
        timezone=task.timezone,
        delivery=ScheduleDelivery(task.delivery),
        delivery_target=task.delivery_target,
        status=ScheduleStatus(task.status),
        next_run_at=task.next_run_at,
        next_run_local=(
            f"{task.next_run_at.astimezone(ZoneInfo(task.timezone)):%Y-%m-%dT%H:%M}"
            if task.next_run_at is not None
            else None
        ),
        last_run_at=task.last_run_at,
        last_run_status=(
            ScheduleRunStatus(task.last_run_status) if task.last_run_status is not None else None
        ),
        last_run_summary=task.last_run_summary,
        last_run_error=task.last_run_error,
        run_count=run_count,
        source_thread_id=task.source_thread_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def to_run_response(run: ScheduledTaskRun) -> ScheduleRunResponse:
    return ScheduleRunResponse.model_validate(run)


def to_tool_response(view: ToolView) -> ToolResponse:
    spec, connection = view.spec, view.connection
    return ToolResponse(
        slug=spec.slug,
        name=spec.name,
        description=spec.description,
        category=spec.category,
        logo_url=spec.logo_url,
        actions=[
            ToolActionResponse(name=action.name, description=action.description)
            for action in spec.actions
        ],
        status=view.status,
        connected_label=connection.connected_label if connection else None,
        connected_email=connection.connected_email if connection else None,
        connected_at=connection.connected_at if connection else None,
        last_checked_at=connection.last_checked_at if connection else None,
    )
