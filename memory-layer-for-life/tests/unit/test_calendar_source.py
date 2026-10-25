"""Reading calendar events from Composio's answer, and the memory each becomes."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.services.source_sync import CalendarEvent, event_memory, parse_events

KOLKATA = ZoneInfo("Asia/Kolkata")


def test_events_are_found_wherever_the_answer_nests_them() -> None:
    item = {
        "id": "e1",
        "summary": " Dentist  visit ",
        "start": {"dateTime": "2026-10-03T04:30:00Z"},
    }

    for data in (
        {"items": [item]},
        {"response_data": {"items": [item]}},
        {"data": {"events": [item]}},
    ):
        [event] = parse_events(data)
        assert (event.id, event.summary) == ("e1", "Dentist visit")
        assert event.start == datetime(2026, 10, 3, 4, 30, tzinfo=UTC)


def test_unusable_and_cancelled_events_are_skipped_and_repeats_dropped() -> None:
    data = {
        "items": [
            {"id": "ok", "summary": "Holiday", "start": {"date": "2026-10-05"}, "updated": "v3"},
            {"id": "ok", "summary": "Holiday", "start": {"date": "2026-10-05"}},
            {
                "id": "gone",
                "summary": "Old",
                "start": {"date": "2026-10-05"},
                "status": "cancelled",
            },
            {"id": "no-title", "start": {"date": "2026-10-05"}},
            {"id": "no-start", "summary": "Floating"},
            {"id": "bad-date", "summary": "Typo", "start": {"date": "2026-13-45"}},
            "not an event",
        ]
    }

    [event] = parse_events(data)

    assert (event.id, event.start, event.updated) == ("ok", date(2026, 10, 5), "v3")
    assert parse_events(None) == []
    assert parse_events({"items": "nope"}) == []


def test_an_event_reads_with_its_local_time_and_place() -> None:
    timed = CalendarEvent(
        id="e1",
        summary="Dentist",
        start=datetime(2026, 10, 3, 4, 30, tzinfo=UTC),
        location="Smile Clinic",
        updated=None,
    )
    all_day = CalendarEvent(
        id="e2", summary="Holiday", start=date(2026, 10, 5), location=None, updated=None
    )

    assert event_memory(timed, KOLKATA) == (
        "Dentist (Sat 3 Oct at 10:00, at Smile Clinic)",
        date(2026, 10, 3),
    )
    assert event_memory(all_day, KOLKATA) == ("Holiday (Mon 5 Oct, all day)", date(2026, 10, 5))
