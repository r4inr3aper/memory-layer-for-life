"""The assistant's tools: input validation, side effects, and safety rules."""

import json
from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import (
    ProposalStatus,
    ScheduleDelivery,
    ScheduleFrequency,
    ToolConnectionStatus,
    Weekday,
)
from app.domain.tool_catalog import find_tool
from app.integrations.composio import ComposioToolMatch
from app.schemas.message_metadata import ScheduleProposal
from app.services.assistant.context import (
    BrowserUpdate,
    ConnectLinkShown,
    ProgressEvent,
    TurnContext,
    WritePolicy,
)
from app.services.assistant.tools import (
    AppAccess,
    AssistantToolbox,
    BrowseWebTool,
    ConnectAppTool,
    FindAppToolsTool,
    ProposeScheduleTool,
    RunAppToolTool,
    changes_data,
)
from app.services.tool_connections import StartedConnection, ToolView
from tests.support.assistant import FakeBrowser, FakeComposio, FakeTime, browser_run, new_principal
from tests.support.pipeline import FakeClock


def turn(**options: Any) -> tuple[TurnContext, list[ProgressEvent]]:
    events: list[ProgressEvent] = []

    async def emit(event: ProgressEvent) -> None:
        events.append(event)

    context = TurnContext(
        principal=new_principal(),
        timezone_name=options.pop("timezone_name", "Europe/Berlin"),
        original_prompt="Every Monday at 9 send me the news",
        emit=emit,
        **options,
    )
    return context, events


# --- propose_schedule ------------------------------------------------------------------

# The test clock starts on Thursday 2026-10-01 at 12:00 UTC (14:00 in Berlin).
NOW = FakeClock()

PROPOSAL = {
    "title": "Monday news",
    "task": "Summarize the top three AI news stories of the past week.",
    "frequency": "weekly",
    "weekdays": ["monday"],
    "time": "09:00",
    "summary": "Every Monday at 9:00 I will send you the news.",
}


class FakeConnections:
    """Answers which apps the user connected, as last seen."""

    def __init__(self, *apps: str) -> None:
        self.apps = list(apps)

    async def last_connected(self, principal: object) -> list[str]:
        return self.apps


def propose_tool(*connected: str) -> ProposeScheduleTool:
    return ProposeScheduleTool(FakeConnections(*connected), clock=NOW)  # type: ignore[arg-type]


async def proposed(arguments: dict[str, Any], *connected: str) -> ScheduleProposal:
    context, _ = turn()
    output = await propose_tool(*connected).run(arguments, context)
    assert not output.is_error, output.content
    assert context.proposal is not None
    return context.proposal


async def test_a_valid_proposal_is_kept_for_the_card() -> None:
    proposal = await proposed(PROPOSAL)

    assert (proposal.frequency, proposal.weekdays, proposal.local_time) == (
        ScheduleFrequency.WEEKLY,
        [Weekday.MONDAY],
        "09:00",
    )
    assert proposal.timezone == "Europe/Berlin"
    assert proposal.delivery is ScheduleDelivery.CHAT
    assert proposal.status is ProposalStatus.PENDING
    assert proposal.original_prompt == "Every Monday at 9 send me the news"


async def test_one_weekday_named_the_old_way_still_works() -> None:
    legacy = {key: value for key, value in PROPOSAL.items() if key != "weekdays"}

    proposal = await proposed({**legacy, "weekday": "monday"})

    assert proposal.weekdays == [Weekday.MONDAY]


async def test_weekdays_are_monday_to_friday_in_order() -> None:
    days = ["friday", "monday", "wednesday", "tuesday", "thursday"]

    proposal = await proposed({**PROPOSAL, "weekdays": days})

    assert proposal.weekdays == [
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
    ]


async def test_a_one_time_reminder_keeps_its_date() -> None:
    proposal = await proposed(
        {**PROPOSAL, "frequency": "once", "weekdays": None, "date": "2026-10-02", "time": "07:30"}
    )

    assert (proposal.frequency, proposal.start_date, proposal.local_time) == (
        ScheduleFrequency.ONCE,
        date(2026, 10, 2),
        "07:30",
    )


async def test_monthly_and_interval_proposals_keep_their_fields() -> None:
    monthly = await proposed(
        {**PROPOSAL, "frequency": "monthly", "weekdays": None, "day_of_month": 31}
    )
    interval = await proposed(
        {**PROPOSAL, "frequency": "interval", "weekdays": None, "interval_hours": 4}
    )

    assert monthly.day_of_month == 31
    # Without a date an interval starts today, in the user's timezone.
    assert (interval.interval_hours, interval.start_date) == (4, date(2026, 10, 1))


async def test_a_moment_in_the_past_is_refused() -> None:
    context, _ = turn()
    arguments = {**PROPOSAL, "frequency": "once", "weekdays": None, "date": "2026-10-01"}

    output = await propose_tool().run({**arguments, "time": "09:00"}, context)

    assert output.is_error
    assert "already passed" in output.content
    assert context.proposal is None


@pytest.mark.parametrize(
    "change",
    [
        {"time": "9am"},
        {"weekdays": None},
        {"frequency": "hourly"},
        {"frequency": "monthly", "weekdays": None},
        {"frequency": "once", "weekdays": None},
        {"frequency": "interval", "weekdays": None, "interval_hours": 0},
        {"frequency": "once", "weekdays": None, "date": "2026-13-01"},
        {"delivery": "carrier_pigeon"},
        {"unexpected": "field"},
    ],
)
async def test_invalid_proposals_are_reported_back(change: dict[str, Any]) -> None:
    context, _ = turn()
    arguments = {**PROPOSAL, **change}

    output = await propose_tool().run(
        {key: value for key, value in arguments.items() if value is not None}, context
    )

    assert output.is_error
    assert context.proposal is None


async def test_results_go_only_to_a_connected_app() -> None:
    context, _ = turn()
    arguments = {**PROPOSAL, "delivery": "slack", "delivery_target": "#news"}

    refused = await propose_tool("gmail").run(arguments, context)
    accepted = await proposed(arguments, "slack")

    assert refused.is_error
    assert "Slack is not connected" in refused.content
    assert "connect_app" in refused.content
    assert accepted.delivery is ScheduleDelivery.SLACK


async def test_only_one_proposal_per_reply() -> None:
    context, _ = turn()
    tool = propose_tool()
    await tool.run(PROPOSAL, context)

    output = await tool.run(PROPOSAL, context)

    assert output.is_error


async def test_scheduled_runs_cannot_propose_schedules() -> None:
    context, _ = turn(allow_proposals=False)

    output = await propose_tool().run(PROPOSAL, context)

    assert output.is_error


# --- browse_web ------------------------------------------------------------------------


def browse_tool(browser: FakeBrowser, timeout: float = 60) -> tuple[BrowseWebTool, FakeTime]:
    fake_time = FakeTime()
    tool = BrowseWebTool(
        browser,  # type: ignore[arg-type]
        timeout_seconds=timeout,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
    )
    return tool, fake_time


async def test_a_browser_task_shows_its_live_view_and_returns_the_result() -> None:
    browser = FakeBrowser(
        browser_run(),
        browser_run(),
        browser_run("COMPLETED", summary="The price is 999 dollars."),
    )
    tool, _ = browse_tool(browser)
    context, events = turn()

    output = await tool.run({"task": "Find the price", "start_url": "https://shop.test"}, context)

    assert json.loads(output.content)["summary"] == "The price is 999 dollars."
    assert not output.is_error
    assert browser.tasks == ["Find the price\nStart at https://shop.test."]
    previews = [event.preview for event in events if isinstance(event, BrowserUpdate)]
    assert previews[0].live_view_url == "https://live.browserbase.example/bb_session_1"
    assert previews[-1].status == "completed"
    assert context.browser_preview == previews[-1]


async def test_a_sign_in_wall_is_reported_as_login_required() -> None:
    browser = FakeBrowser(browser_run(), browser_run("COMPLETED", login_required=True))
    tool, _ = browse_tool(browser)
    context, _ = turn()

    output = await tool.run({"task": "Check my orders"}, context)

    assert json.loads(output.content)["status"] == "login_required"
    assert context.browser_preview is not None
    assert context.browser_preview.status == "login_required"


async def test_a_slow_browser_task_times_out_and_is_stopped() -> None:
    browser = FakeBrowser(browser_run())
    tool, fake_time = browse_tool(browser, timeout=10)
    context, _ = turn()

    output = await tool.run({"task": "Book a table"}, context)

    assert output.is_error
    assert json.loads(output.content)["status"] == "timed_out"
    assert browser.stopped_runs == ["run_1"]
    assert fake_time.now >= 10


async def test_a_start_url_must_be_a_web_address() -> None:
    tool, _ = browse_tool(FakeBrowser(browser_run()))
    context, _ = turn()

    output = await tool.run({"task": "x", "start_url": "javascript:alert(1)"}, context)

    assert output.is_error


# --- App tools -------------------------------------------------------------------------


def app_tools(composio: FakeComposio) -> tuple[FindAppToolsTool, RunAppToolTool]:
    connections = AsyncMock()

    async def active_accounts(principal: object) -> dict[str, list[str]]:
        accounts: dict[str, list[str]] = {}
        for account in await composio.list_active_accounts(str(principal.id)):  # type: ignore[attr-defined]
            accounts.setdefault(account.toolkit_slug or "", []).append(account.id)
        return accounts

    connections.active_accounts.side_effect = active_accounts
    access = AppAccess(composio, connections)  # type: ignore[arg-type]
    return FindAppToolsTool(access), RunAppToolTool(access)


async def test_find_app_tools_lists_only_the_app_s_own_tools() -> None:
    composio = FakeComposio(
        tools={
            "slack": [
                ComposioToolMatch("SLACK_SEND_MESSAGE", "Send a message", {"type": "object"}),
                ComposioToolMatch("GMAIL_SEND_EMAIL", "Not Slack", None),
            ]
        }
    )
    find, _ = app_tools(composio)
    context, _ = turn()
    composio.add_account(context.principal.id, "slack")

    output = await find.run({"app": "slack", "use_case": "post a message"}, context)

    tools = json.loads(output.content)["tools"]
    assert [tool["tool_slug"] for tool in tools] == ["SLACK_SEND_MESSAGE"]


async def test_an_app_that_is_not_connected_asks_for_a_connection() -> None:
    find, _ = app_tools(FakeComposio())
    context, _ = turn()

    output = await find.run({"app": "gmail", "use_case": "read email"}, context)

    assert json.loads(output.content) == {
        "connected": False,
        "message": "Gmail is not connected. Call connect_app.",
    }


async def test_run_app_tool_executes_in_the_app_s_session_once_per_turn() -> None:
    composio = FakeComposio()
    _, run = app_tools(composio)
    context, _ = turn()
    composio.add_account(context.principal.id, "slack")

    for _ in range(2):
        output = await run.run(
            {"app": "slack", "tool_slug": "SLACK_SEARCH_MESSAGES", "arguments": {"query": "hi"}},
            context,
        )
        assert not output.is_error

    assert len(composio.sessions) == 1
    assert [slug for _, slug, _ in composio.executions] == ["SLACK_SEARCH_MESSAGES"] * 2
    assert context.executed == [("slack", "SLACK_SEARCH_MESSAGES")] * 2


async def test_a_tool_of_another_app_is_refused() -> None:
    _, run = app_tools(FakeComposio())
    context, _ = turn()

    output = await run.run(
        {"app": "slack", "tool_slug": "GMAIL_SEND_EMAIL", "arguments": {}}, context
    )

    assert output.is_error


async def test_a_scheduled_run_changes_data_only_in_its_delivery_app() -> None:
    composio = FakeComposio()
    _, run = app_tools(composio)
    context, _ = turn(write_policy=WritePolicy.DELIVERY_APP_ONLY, delivery_app="slack")
    composio.add_account(context.principal.id, "slack")
    composio.add_account(context.principal.id, "gmail")

    blocked = await run.run(
        {"app": "gmail", "tool_slug": "GMAIL_SEND_EMAIL", "arguments": {}}, context
    )
    reading = await run.run(
        {"app": "gmail", "tool_slug": "GMAIL_FETCH_EMAILS", "arguments": {}}, context
    )
    delivering = await run.run(
        {"app": "slack", "tool_slug": "SLACK_SEND_MESSAGE", "arguments": {}}, context
    )

    assert blocked.is_error
    assert not reading.is_error
    assert not delivering.is_error
    assert [slug for _, slug, _ in composio.executions] == [
        "GMAIL_FETCH_EMAILS",
        "SLACK_SEND_MESSAGE",
    ]


async def test_chat_write_actions_require_explicit_confirmation() -> None:
    composio = FakeComposio()
    _, run = app_tools(composio)
    context, _ = turn(user_confirmed_action=False)
    composio.add_account(context.principal.id, "slack")

    blocked = await run.run(
        {"app": "slack", "tool_slug": "SLACK_SEND_MESSAGE", "arguments": {}}, context
    )

    assert blocked.is_error
    assert "explicit confirmation" in blocked.content


async def test_confirmed_flag_without_user_approval_is_refused() -> None:
    composio = FakeComposio()
    _, run = app_tools(composio)
    context, _ = turn(user_confirmed_action=False)
    composio.add_account(context.principal.id, "slack")

    blocked = await run.run(
        {
            "app": "slack",
            "tool_slug": "SLACK_SEND_MESSAGE",
            "arguments": {"text": "hello"},
            "confirmed": True,
        },
        context,
    )

    assert blocked.is_error


async def test_chat_write_actions_run_after_explicit_confirmation() -> None:
    composio = FakeComposio()
    _, run = app_tools(composio)
    context, _ = turn(user_confirmed_action=True)
    composio.add_account(context.principal.id, "slack")

    allowed = await run.run(
        {
            "app": "slack",
            "tool_slug": "SLACK_SEND_MESSAGE",
            "arguments": {"text": "hello"},
            "confirmed": True,
        },
        context,
    )

    assert not allowed.is_error
    assert [slug for _, slug, _ in composio.executions] == ["SLACK_SEND_MESSAGE"]


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("GMAIL_SEND_EMAIL", True),
        ("SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL", True),
        ("GOOGLECALENDAR_CREATE_EVENT", True),
        ("NOTION_UPDATE_PAGE", True),
        ("GMAIL_FETCH_EMAILS", False),
        ("GOOGLECALENDAR_LIST_EVENTS", False),
        ("SLACK_SEARCH_MESSAGES", False),
    ],
)
def test_actions_that_change_data_are_recognized(slug: str, expected: bool) -> None:
    assert changes_data(slug) is expected


async def test_connect_app_shows_a_connect_button() -> None:
    connections = AsyncMock()
    context, events = turn()
    gmail = find_tool("gmail")
    assert gmail is not None
    spec_view = ToolView(spec=gmail, status=ToolConnectionStatus.PENDING, connection=None)
    connections.start_connection.return_value = StartedConnection(
        view=spec_view, connect_url="https://connect.composio.dev/link/lk_1"
    )

    output = await ConnectAppTool(connections).run({"app": "gmail"}, context)

    assert not output.is_error
    assert context.connect_link is not None
    assert context.connect_link.connect_url == "https://connect.composio.dev/link/lk_1"
    assert any(isinstance(event, ConnectLinkShown) for event in events)


def test_the_toolbox_offers_only_configured_tools() -> None:
    connections = AsyncMock()
    bare = AssistantToolbox(
        connections=connections, composio=None, browser=None, browser_timeout_seconds=60
    )
    full = AssistantToolbox(
        connections=connections,
        composio=FakeComposio(),  # type: ignore[arg-type]
        browser=FakeBrowser(browser_run()),  # type: ignore[arg-type]
        browser_timeout_seconds=60,
    )

    assert [tool.definition.name for tool in bare.for_chat()] == ["propose_schedule"]
    assert [tool.definition.name for tool in full.for_chat()] == [
        "propose_schedule",
        "browse_web",
        "find_app_tools",
        "run_app_tool",
        "connect_app",
    ]
    # Scheduled runs never browse: nothing could keep a browser task to reading only.
    assert [tool.definition.name for tool in full.for_schedule()] == [
        "find_app_tools",
        "run_app_tool",
    ]
    assert bare.capabilities.browser is False
    assert full.capabilities.apps is True


def test_tool_definitions_are_valid_object_schemas() -> None:
    full = AssistantToolbox(
        connections=AsyncMock(),
        composio=FakeComposio(),  # type: ignore[arg-type]
        browser=FakeBrowser(browser_run()),  # type: ignore[arg-type]
        browser_timeout_seconds=60,
    )

    for tool in full.for_chat():
        schema = tool.definition.input_schema
        assert schema["type"] == "object"
        assert set(schema.get("required", [])) <= set(schema["properties"])  # type: ignore[arg-type]
