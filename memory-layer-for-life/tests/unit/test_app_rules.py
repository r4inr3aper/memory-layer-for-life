"""Pure rules behind the app's newer features: the usage day, the assistant's name,
request validation, and how attached files reach the model."""

import base64
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.domain.enums import UsageGranularity
from app.integrations.assistant.anthropic_model import to_message_params
from app.integrations.assistant.base import Attachment, UserText
from app.schemas.app import AttachmentInput, SendMessageRequest, UpdateMeRequest
from app.services.assistant.prompts import chat_context, scheduled_context
from app.services.usage import UsageReport, day_window, period_starts

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)

# --- The usage day --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "day", "resets_at"),
    [
        (NOW, date(2026, 10, 19), datetime(2026, 10, 20, tzinfo=UTC)),
        (
            datetime(2026, 12, 31, 23, 59, tzinfo=UTC),
            date(2026, 12, 31),
            datetime(2027, 1, 1, tzinfo=UTC),
        ),
        # 01:00 in Kolkata is still the previous UTC day.
        (
            datetime(2026, 10, 20, 1, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            date(2026, 10, 19),
            datetime(2026, 10, 20, tzinfo=UTC),
        ),
    ],
)
def test_the_usage_day_is_the_utc_calendar_day(
    now: datetime, day: date, resets_at: datetime
) -> None:
    assert day_window(now) == (day, resets_at)


def report(chat_messages: int, scheduled_runs: int, limit: int | None) -> UsageReport:
    day, resets_at = day_window(NOW)
    return UsageReport(
        day=day,
        resets_at=resets_at,
        prompt_limit=limit,
        chat_messages=chat_messages,
        scheduled_runs=scheduled_runs,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=Decimal("0"),
        currency="INR",
        estimated_cost=Decimal("0"),
    )


@pytest.mark.parametrize(
    ("chat_messages", "scheduled_runs", "limit", "remaining"),
    [(3, 2, 40, 35), (30, 12, 40, 0), (3, 0, None, None)],
)
def test_prompts_remaining_never_goes_below_zero(
    chat_messages: int, scheduled_runs: int, limit: int | None, remaining: int | None
) -> None:
    usage = report(chat_messages, scheduled_runs, limit)

    assert usage.prompts_used == chat_messages + scheduled_runs
    assert usage.prompts_remaining == remaining


@pytest.mark.parametrize(
    ("granularity", "today", "first", "last"),
    [
        (UsageGranularity.DAY, date(2026, 10, 1), date(2026, 9, 18), date(2026, 10, 1)),
        # Thursday: the current week began on Monday 28 September.
        (UsageGranularity.WEEK, date(2026, 10, 1), date(2026, 7, 13), date(2026, 9, 28)),
        # A Monday is the first day of its own week.
        (UsageGranularity.WEEK, date(2026, 9, 28), date(2026, 7, 13), date(2026, 9, 28)),
        (UsageGranularity.MONTH, date(2026, 10, 19), date(2025, 11, 1), date(2026, 10, 1)),
        # Twelve months back from January crosses into the previous year.
        (UsageGranularity.MONTH, date(2026, 1, 31), date(2025, 2, 1), date(2026, 1, 1)),
    ],
)
def test_history_periods_end_with_the_current_one(
    granularity: UsageGranularity, today: date, first: date, last: date
) -> None:
    starts = period_starts(granularity, today)

    assert (starts[0], starts[-1]) == (first, last)
    assert starts == sorted(set(starts))


# --- The assistant's name --------------------------------------------------------------


def test_the_assistant_is_called_cooper_until_the_user_renames_it() -> None:
    default = chat_context(now=NOW, timezone_name="UTC", user_name="Ada", connected_apps=[])
    renamed = chat_context(
        now=NOW, timezone_name="UTC", user_name="Ada", connected_apps=[], assistant_name="Nova"
    )
    scheduled = scheduled_context(
        now=NOW,
        timezone_name="UTC",
        title="News",
        delivery_name="chat",
        delivery_target=None,
        connected_apps=[],
        assistant_name="Nova",
    )

    assert "Your name: Cooper." in default
    assert "Your name: Nova." in renamed
    assert "Your name: Nova." in scheduled


# --- Requests --------------------------------------------------------------------------


def test_a_profile_change_knows_which_fields_were_sent() -> None:
    change = UpdateMeRequest.model_validate({"assistant_name": " ", "notifications_enabled": True})

    assert change.model_fields_set == {"assistant_name", "notifications_enabled"}
    assert change.assistant_name is None


def test_a_message_needs_text_or_files() -> None:
    with pytest.raises(ValidationError, match="send text, files, or both"):
        SendMessageRequest.model_validate({"content": "  "})

    files_only = SendMessageRequest.model_validate(
        {
            "attachments": [
                {
                    "name": "a.png",
                    "media_type": "image/png",
                    "data": base64.b64encode(b"x").decode(),
                }
            ]
        }
    )
    assert files_only.content == ""


def test_an_attachment_decodes_to_its_bytes() -> None:
    attachment = AttachmentInput(
        name="a.pdf", media_type="application/pdf", data=base64.b64encode(b"%PDF-1.7").decode()
    )

    assert attachment.decoded() == b"%PDF-1.7"


@pytest.mark.parametrize(
    "fields",
    [
        {"media_type": "image/heic", "data": "eA=="},
        {"media_type": "image/png", "data": "***"},
    ],
)
def test_unsupported_or_malformed_attachments_are_refused(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AttachmentInput.model_validate({"name": "file", **fields})


# --- Attached files in the Messages API ------------------------------------------------


def test_attached_files_come_before_the_text_as_image_and_document_blocks() -> None:
    [param] = to_message_params(
        [
            UserText(
                "Compare these.",
                attachments=(
                    Attachment("chart.png", "image/png", b"png-bytes"),
                    Attachment("report.pdf", "application/pdf", b"pdf-bytes"),
                ),
            )
        ]
    )

    assert param == {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(b"png-bytes").decode(),
                },
            },
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(b"pdf-bytes").decode(),
                },
                "title": "report.pdf",
            },
            {"type": "text", "text": "Compare these."},
        ],
    }


def test_a_message_without_files_stays_plain_text() -> None:
    assert to_message_params([UserText("hi")]) == [{"role": "user", "content": "hi"}]
