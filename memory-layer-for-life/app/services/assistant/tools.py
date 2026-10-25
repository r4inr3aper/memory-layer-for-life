"""The tools the assistant can call.


Tool input is model output and therefore untrusted: each tool validates it with a strict
model before acting, and reports problems back to the model as an error result rather
than raising. Results are short JSON or plain text, cut to a size the model can use.


Which tools exist depends on configuration. Without a Browserbase key there is no
browser tool, without a Composio key there are no app tools, and without a retrieval
engine there is no memory search.


Scheduled runs never get the browser. A run may change data only in the app it delivers
to, and a browser task is free-form instructions to a browser agent: nothing can tell
reading a page from submitting a form or booking, so the rule could not be enforced.
"""


import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo


import structlog
from pydantic import Field, ValidationError


from app.core.clock import Clock, utc_now
from app.domain.enums import LlmCallOrigin, ScheduleDelivery, ScheduleFrequency, Weekday
from app.domain.errors import (
    DomainError,
    IntegrationError,
    InvalidRetrievalQueryError,
    InvalidScheduleError,
)
from app.domain.retrieval import RetrievalQuery
from app.domain.schedule_rules import (
    MAX_INTERVAL_HOURS,
    MIN_INTERVAL_HOURS,
    RuleFields,
    ScheduleRule,
    parse_local_date,
    parse_local_time,
)
from app.domain.tool_catalog import DELIVERY_TOOLKITS, TOOL_CATALOG, find_tool
from app.integrations.assistant.base import ToolDefinition
from app.integrations.browserbase import BrowserbaseClient, BrowserRun
from app.integrations.composio import ComposioClient
from app.integrations.llm_calls import LlmCallContext
from app.schemas.message_metadata import BrowserPreview, ConnectLink, ScheduleProposal
from app.services.assistant.context import (
    BrowserUpdate,
    ConnectLinkShown,
    TurnContext,
    WritePolicy,
)
from app.services.assistant.life_tools import (
    CreateReminderTool,
    ListOpenItemsTool,
    UpdateOpenItemTool,
)
from app.services.assistant.prompts import Capabilities
from app.services.assistant.tool_base import (
    AssistantTool,
    ToolInput,
    ToolOutput,
    invalid_input,
)
from app.services.life_state import LifeStateService
from app.services.retrieval.documents import memory_type_label
from app.services.retrieval.engine import RetrievalEngine, RetrievalResult
from app.services.tool_connections import ToolConnectionService


logger = structlog.get_logger(__name__)


_MAX_RESULT_CHARS: Final = 12_000
_MAX_SCHEMA_CHARS: Final = 2_500
_MAX_TOOL_MATCHES: Final = 5
_BROWSER_POLL_SECONDS: Final = 2.0
_APP_SLUGS: Final = [spec.slug for spec in TOOL_CATALOG]
# Words in a Composio tool slug that mark an action changing data. Erring towards
# "changes data" only ever blocks a call in a scheduled run.
_WRITE_WORDS: Final = frozenset(
    {
        "ADD", "APPEND", "ARCHIVE", "BATCH", "CLEAR", "CREATE", "CREATES", "DELETE",
        "DELETES", "EDIT", "FORWARD", "INSERT", "INVITE", "MODIFY", "MOVE", "PATCH", "POST",
        "POSTS", "REMOVE", "REPLY", "SEND", "SENDS", "SET", "SHARE", "TRASH", "UPDATE",
        "UPDATES", "UPLOAD", "UPSERT", "WRITE",
    }
)  # fmt: skip


Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]




def changes_data(tool_slug: str) -> bool:
    return any(word in _WRITE_WORDS for word in tool_slug.upper().split("_"))




def compact(value: object, limit: int = _MAX_RESULT_CHARS) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else f"{text[:limit]}… (cut, {len(text)} characters)"




# --- propose_schedule ----------------------------------------------------------------




class ProposeScheduleInput(ToolInput):
    title: str = Field(min_length=1, max_length=120)
    task: str = Field(min_length=1, max_length=2000)
    frequency: ScheduleFrequency
    time: str
    date: str | None = None
    weekdays: list[Weekday] | None = Field(default=None, min_length=1, max_length=7)
    # Models sometimes name one day the old way; it means the same as a one-day list.
    weekday: Weekday | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    interval_hours: int | None = Field(default=None, ge=1, le=24)
    delivery: ScheduleDelivery = ScheduleDelivery.CHAT
    delivery_target: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=1, max_length=400)




class ProposeScheduleTool:
    label = "Preparing a schedule"
    definition = ToolDefinition(
        name="propose_schedule",
        description=(
            "Show the user a card proposing a one-time or recurring task, which they confirm "
            "or dismiss. Nothing is scheduled until they confirm. Call at most once per reply."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "A short name for the task."},
                "task": {
                    "type": "string",
                    "description": (
                        "A complete instruction for running the task later without this "
                        "conversation, for example 'Find the three most important AI news "
                        "stories of the last day and summarize each in two sentences.'"
                    ),
                },
                "frequency": {
                    "type": "string",
                    "enum": [item.value for item in ScheduleFrequency],
                    "description": (
                        "once: a one-time reminder or task on 'date'. daily. weekly: on "
                        "'weekdays' (Monday to Friday for weekdays). monthly: on "
                        "'day_of_month'. interval: every 'interval_hours' hours from 'time'."
                    ),
                },
                "time": {
                    "type": "string",
                    "description": (
                        "HH:MM, 24-hour, user's local time. For interval, the first run."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": (
                        "YYYY-MM-DD in the user's calendar. Required for once; for interval, "
                        "the day of the first run (default today)."
                    ),
                },
                "weekdays": {
                    "type": "array",
                    "items": {"type": "string", "enum": [item.value for item in Weekday]},
                    "description": "Required for weekly: one or more days.",
                },
                "day_of_month": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 31,
                    "description": "Required for monthly. 31 means the last day of each month.",
                },
                "interval_hours": {
                    "type": "integer",
                    "minimum": MIN_INTERVAL_HOURS,
                    "maximum": MAX_INTERVAL_HOURS,
                    "description": "Required for interval: hours between runs.",
                },
                "delivery": {
                    "type": "string",
                    "enum": [item.value for item in ScheduleDelivery],
                    "description": (
                        "Where the result goes: 'chat' unless the user names one. An app "
                        "must be connected."
                    ),
                },
                "delivery_target": {
                    "type": "string",
                    "description": "A Slack channel, email address, or similar, when needed.",
                },
                "summary": {
                    "type": "string",
                    "description": "One sentence for the card saying what will happen.",
                },
            },
            "required": ["title", "task", "frequency", "time", "summary"],
        },
    )


    def __init__(self, connections: ToolConnectionService, *, clock: Clock = utc_now) -> None:
        self._connections = connections
        self._clock = clock


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        if not turn.allow_proposals:
            return ToolOutput("Schedules cannot be proposed here.", is_error=True)
        if turn.proposal is not None:
            return ToolOutput("A schedule was already proposed in this reply.", is_error=True)
        try:
            proposal_input = ProposeScheduleInput.model_validate(arguments)
            weekdays = tuple(proposal_input.weekdays or ())
            if not weekdays and proposal_input.weekday is not None:
                weekdays = (proposal_input.weekday,)
            fields = RuleFields(
                frequency=proposal_input.frequency,
                local_time=parse_local_time(proposal_input.time),
                timezone=turn.timezone_name,
                weekdays=weekdays,
                day_of_month=proposal_input.day_of_month,
                start_date=(
                    parse_local_date(proposal_input.date)
                    if proposal_input.date is not None
                    else None
                ),
                interval_hours=proposal_input.interval_hours,
            )
            rule = _proposal_rule(fields, self._clock())
        except ValidationError as error:
            return invalid_input(error)
        except DomainError as error:
            return ToolOutput(error.message, is_error=True)


        app = delivery_app(proposal_input.delivery)
        if app is not None and app not in await self._connections.last_connected(turn.principal):
            spec = find_tool(app)
            name = spec.name if spec is not None else app
            return ToolOutput(
                f"{name} is not connected, so results cannot be sent there. Offer to connect it "
                "(connect_app), or deliver to chat instead.",
                is_error=True,
            )


        turn.proposal = ScheduleProposal(
            title=proposal_input.title,
            original_prompt=turn.original_prompt,
            task=proposal_input.task,
            frequency=rule.frequency,
            local_time=f"{rule.local_time:%H:%M}",
            weekdays=list(rule.weekdays) or None,
            day_of_month=rule.day_of_month,
            start_date=rule.start_date,
            interval_hours=rule.interval_hours,
            timezone=rule.timezone_name,
            delivery=proposal_input.delivery,
            delivery_target=proposal_input.delivery_target,
            summary=proposal_input.summary,
        )
        return ToolOutput(
            "The confirmation card is shown to the user. Tell them in a sentence what will "
            "happen and that it starts once they confirm. Do not say it is already scheduled."
        )




def _proposal_rule(fields: RuleFields, now: datetime) -> ScheduleRule:
    """The rule, checked: it must have a run still to come, or confirming would fail."""
    rule = fields.build(now)
    if rule.next_after(now) is None:
        raise InvalidScheduleError(
            "That time has already passed. Ask the user for a time in the future."
        )
    return rule




# --- browse_web ----------------------------------------------------------------------




class BrowseWebInput(ToolInput):
    task: str = Field(min_length=1, max_length=2000)
    start_url: str | None = Field(default=None, max_length=2000)




class BrowseWebTool:
    label = "Browsing the web"
    definition = ToolDefinition(
        name="browse_web",
        description=(
            "Run a task in a cloud browser that visits and interacts with websites, and "
            "return what it found. The user can watch it live. Use one call per goal."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The complete goal, including what to report back.",
                },
                "start_url": {
                    "type": "string",
                    "description": "A full URL to begin at, when one is obvious.",
                },
            },
            "required": ["task"],
        },
    )


    def __init__(
        self,
        browser: BrowserbaseClient,
        *,
        timeout_seconds: float,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic = time.monotonic,
    ) -> None:
        self._browser = browser
        self._timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            browse_input = BrowseWebInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        if browse_input.start_url and not browse_input.start_url.startswith(
            ("https://", "http://")
        ):
            return ToolOutput("start_url must be a full http(s) URL.", is_error=True)


        task = browse_input.task
        if browse_input.start_url:
            task = f"{task}\nStart at {browse_input.start_url}."
        deadline = self._monotonic() + self._timeout_seconds


        run = await self._browser.start_run(task)
        try:
            preview = await self._publish(turn, run, browse_input.task, live_view_url=None)
            while not run.finished and self._monotonic() < deadline:
                await self._sleep(_BROWSER_POLL_SECONDS)
                had_session = run.session_id is not None
                run = await self._browser.get_run(run.run_id)
                if run.session_id is not None and not had_session:
                    # The browser just started: show its live view.
                    preview = await self._publish(turn, run, browse_input.task, live_view_url=None)
        except asyncio.CancelledError:
            # The reply was cancelled (the server is stopping): stop the remote run rather
            # than leave a browser working, and billing, for nobody.
            await asyncio.shield(self._stop(run.run_id))
            raise


        if not run.finished:
            # Nobody would ever collect its result, so it is stopped, not left running.
            await self._stop(run.run_id)
            await self._publish(turn, run, browse_input.task, preview.live_view_url, "failed")
            return ToolOutput(
                compact(
                    {
                        "status": "timed_out",
                        "note": (
                            f"The browser task took longer than {round(self._timeout_seconds)}"
                            " seconds and was stopped. Tell the user, and suggest a narrower"
                            " task."
                        ),
                    }
                ),
                is_error=True,
            )


        status = _browser_status(run)
        await self._publish(turn, run, browse_input.task, preview.live_view_url, status)
        return ToolOutput(
            compact(
                {
                    "status": status,
                    "summary": run.summary,
                    "source_url": run.source_url,
                    "error": run.error,
                }
            ),
            is_error=status == "failed",
        )


    async def _publish(
        self,
        turn: TurnContext,
        run: BrowserRun,
        task: str,
        live_view_url: str | None,
        status: str = "running",
    ) -> BrowserPreview:
        if live_view_url is None and run.session_id is not None:
            try:
                live_view_url = await self._browser.live_view_url(run.session_id)
            except IntegrationError:
                # The task goes on without its preview.
                logger.warning("browser_live_view_unavailable", session_id=run.session_id)
        preview = BrowserPreview(
            run_id=run.run_id,
            session_id=run.session_id,
            live_view_url=live_view_url,
            task=task,
            status=status,
        )
        turn.browser_preview = preview
        await turn.emit(BrowserUpdate(preview))
        return preview


    async def _stop(self, run_id: str) -> None:
        try:
            await self._browser.stop_run(run_id)
        except IntegrationError:
            logger.warning("browser_run_stop_failed", run_id=run_id)




def _browser_status(run: BrowserRun) -> str:
    if run.login_required or run.status == "PAUSED":
        return "login_required"
    return "completed" if run.status == "COMPLETED" else "failed"




# --- App tools -----------------------------------------------------------------------




class AppAccess:
    """Composio sessions and connected accounts, looked up once per turn."""


    def __init__(self, composio: ComposioClient, connections: ToolConnectionService) -> None:
        self.composio = composio
        self.connections = connections


    async def accounts(self, turn: TurnContext) -> dict[str, list[str]]:
        if turn.active_accounts is None:
            turn.active_accounts = await self.connections.active_accounts(turn.principal)
        return turn.active_accounts


    async def session(self, turn: TurnContext, app: str) -> str | None:
        """The app's tool session, or None when the user has not connected the app."""
        accounts = (await self.accounts(turn)).get(app)
        if not accounts:
            return None
        if app not in turn.app_sessions:
            turn.app_sessions[app] = await self.composio.create_session(
                str(turn.principal.id), app, accounts
            )
        return turn.app_sessions[app]




def _not_connected(app: str, turn: TurnContext) -> ToolOutput:
    spec = find_tool(app)
    name = spec.name if spec is not None else app
    if turn.write_policy is WritePolicy.DELIVERY_APP_ONLY:
        return ToolOutput(f"{name} is not connected, so it cannot be used now.", is_error=True)
    return ToolOutput(
        compact({"connected": False, "message": f"{name} is not connected. Call connect_app."})
    )




_APP_PROPERTY: Final = {"type": "string", "enum": _APP_SLUGS, "description": "The app."}




class FindAppToolsInput(ToolInput):
    app: str
    use_case: str = Field(min_length=1, max_length=1000)




class FindAppToolsTool:
    label = "Looking at your apps"
    definition = ToolDefinition(
        name="find_app_tools",
        description=(
            "Find the actions available in one of the user's connected apps for a use case. "
            "Returns tool slugs with their input schemas, for run_app_tool."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app": _APP_PROPERTY,
                "use_case": {
                    "type": "string",
                    "description": "What you want to do, for example 'list today's events'.",
                },
            },
            "required": ["app", "use_case"],
        },
    )


    def __init__(self, access: AppAccess) -> None:
        self._access = access


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            find_input = FindAppToolsInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        app = find_input.app.lower()
        if find_tool(app) is None:
            return ToolOutput(f"Unknown app: {app}.", is_error=True)
        session_id = await self._access.session(turn, app)
        if session_id is None:
            return _not_connected(app, turn)
        matches = await self._access.composio.search_tools(session_id, find_input.use_case)
        tools = [
            {
                "tool_slug": match.slug,
                "description": match.description,
                "input_schema": compact(match.input_schema, _MAX_SCHEMA_CHARS)
                if match.input_schema
                else None,
            }
            for match in matches
            if match.slug.lower().startswith(f"{app}_")
        ][:_MAX_TOOL_MATCHES]
        if not tools:
            return ToolOutput(f"No {app} action fits that use case.", is_error=True)
        return ToolOutput(compact({"connected": True, "tools": tools}))




class RunAppToolInput(ToolInput):
    app: str
    tool_slug: str = Field(min_length=1, max_length=200)
    arguments: dict[str, object] = Field(default_factory=dict)




class RunAppToolTool:
    label = "Working in your apps"
    definition = ToolDefinition(
        name="run_app_tool",
        description=(
            "Run one action in a connected app with arguments matching its input schema. "
            "Actions that send, create, change, or delete data need the user's confirmation "
            "first."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "app": _APP_PROPERTY,
                "tool_slug": {"type": "string", "description": "A slug from find_app_tools."},
                "arguments": {"type": "object", "description": "The action's input."},
            },
            "required": ["app", "tool_slug", "arguments"],
        },
    )


    def __init__(self, access: AppAccess) -> None:
        self._access = access


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            run_input = RunAppToolInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        app = run_input.app.lower()
        slug = run_input.tool_slug.upper()
        if find_tool(app) is None:
            return ToolOutput(f"Unknown app: {app}.", is_error=True)
        if not slug.lower().startswith(f"{app}_"):
            return ToolOutput(f"{slug} is not an action of {app}.", is_error=True)
        if (
            turn.write_policy is WritePolicy.DELIVERY_APP_ONLY
            and changes_data(slug)
            and app != turn.delivery_app
        ):
            return ToolOutput(
                "A scheduled run may only change data in the app it delivers to.",
                is_error=True,
            )


        session_id = await self._access.session(turn, app)
        if session_id is None:
            return _not_connected(app, turn)
        execution = await self._access.composio.execute_tool(session_id, slug, run_input.arguments)
        if execution.successful:
            turn.executed.append((app, slug))
        return ToolOutput(
            compact(
                {
                    "successful": execution.successful,
                    "data": execution.data,
                    "error": execution.error,
                }
            ),
            is_error=not execution.successful,
        )




class ConnectAppInput(ToolInput):
    app: str




class ConnectAppTool:
    label = "Preparing a connection"
    definition = ToolDefinition(
        name="connect_app",
        description=(
            "Show the user a button to connect one of their apps. Use it when an app the "
            "request needs is not connected."
        ),
        input_schema={"type": "object", "properties": {"app": _APP_PROPERTY}, "required": ["app"]},
    )


    def __init__(self, connections: ToolConnectionService) -> None:
        self._connections = connections


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            connect_input = ConnectAppInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        spec = find_tool(connect_input.app)
        if spec is None:
            return ToolOutput(f"Unknown app: {connect_input.app}.", is_error=True)
        started = await self._connections.start_connection(
            turn.principal, spec.slug, callback_url=None
        )
        if started.connect_url is None:
            turn.active_accounts = None
            return ToolOutput(f"{spec.name} is already connected.")
        link = ConnectLink(toolkit=spec.slug, tool_name=spec.name, connect_url=started.connect_url)
        turn.connect_link = link
        await turn.emit(ConnectLinkShown(link))
        return ToolOutput(
            f"A Connect button for {spec.name} is shown in the chat. Ask the user to tap it, "
            "finish authorizing, and tell you when they are done."
        )




# --- search_memories -----------------------------------------------------------------


_MAX_MEMORY_RESULTS: Final = 10
_MAX_EVIDENCE_QUOTE: Final = 200




class SearchMemoriesInput(ToolInput):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=_MAX_MEMORY_RESULTS)




class SearchMemoriesTool:
    label = "Checking your memories"
    definition = ToolDefinition(
        name="search_memories",
        description=(
            "Search what the user told you in earlier messages (their saved memories) by "
            "words, names, and meaning. Returns the most relevant memories, newest facts "
            "marked with when they were noted, each with the user's own words as evidence."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What you need to know, in a few words, for example 'Priya' or "
                        "'money Raju owes' or 'plans for the weekend'."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_MEMORY_RESULTS,
                    "description": "How many memories to return; 5 unless you need more.",
                },
            },
            "required": ["query"],
        },
    )


    def __init__(self, engine: RetrievalEngine) -> None:
        self._engine = engine


    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            parsed = SearchMemoriesInput.model_validate(arguments)
            query = RetrievalQuery(
                text=parsed.query, owner_id=turn.principal.id, limit=parsed.limit
            )
        except ValidationError as error:
            return invalid_input(error)
        except InvalidRetrievalQueryError as error:
            return ToolOutput(error.message, is_error=True)
        result = await self._engine.search(
            query,
            context=LlmCallContext(origin=LlmCallOrigin.RETRIEVAL, user_id=turn.principal.id),
        )
        return ToolOutput(format_memories(result, timezone_name=turn.timezone_name))




def format_memories(result: RetrievalResult, *, timezone_name: str) -> str:
    """The search result as the model reads it: numbered memories, each with its kind,
    when it was noted, its review status, and the user's own words as evidence."""
    if not result.items:
        return (
            "No saved memory matches this. Say you do not have it rather than guessing, "
            "and ask the user if it matters."
        )
    zone = ZoneInfo(timezone_name)
    lines = ["Memories from the user's own earlier messages, most relevant first:"]
    for item in result.items:
        memory = item.memory
        noted = (memory.observed_at or memory.created_at).astimezone(zone)
        review = "reviewed" if memory.status.value == "active" else "not yet reviewed"
        lines.append(
            f"{item.rank}. [{memory_type_label(memory.memory_type.value)}, noted "
            f"{noted:%d %b %Y}, {review}] {memory.content}"
        )
        quote = next((source.evidence or source.content for source in item.sources), None)
        if quote:
            lines.append(f'   The user wrote: "{" ".join(quote.split())[:_MAX_EVIDENCE_QUOTE]}"')
    if result.degraded:
        lines.append("(Search by meaning was unavailable; these were found by words and names.)")
    return "\n".join(lines)




# --- Toolbox -------------------------------------------------------------------------




class AssistantToolbox:
    """Builds the tool set for a chat turn or a scheduled run from what is configured."""


    def __init__(
        self,
        *,
        connections: ToolConnectionService,
        composio: ComposioClient | None,
        browser: BrowserbaseClient | None,
        browser_timeout_seconds: float,
        memories: RetrievalEngine | None = None,
        life: LifeStateService | None = None,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic = time.monotonic,
        clock: Clock = utc_now,
    ) -> None:
        self._connections = connections
        self._propose = ProposeScheduleTool(connections, clock=clock)
        self._memories = SearchMemoriesTool(memories) if memories is not None else None
        self._life_read: tuple[AssistantTool, ...] = (
            (ListOpenItemsTool(life),) if life is not None else ()
        )
        self._life_write: tuple[AssistantTool, ...] = (
            (CreateReminderTool(life), UpdateOpenItemTool(life, clock=clock))
            if life is not None
            else ()
        )
        self._browse = (
            BrowseWebTool(
                browser, timeout_seconds=browser_timeout_seconds, sleep=sleep, monotonic=monotonic
            )
            if browser is not None
            else None
        )
        access = AppAccess(composio, connections) if composio is not None else None
        self._app_tools: tuple[AssistantTool, ...] = (
            (FindAppToolsTool(access), RunAppToolTool(access)) if access is not None else ()
        )
        self._connect = ConnectAppTool(connections) if composio is not None else None


    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            browser=self._browse is not None,
            apps=bool(self._app_tools),
            memories=self._memories is not None,
            life=bool(self._life_read),
        )


    def for_chat(self) -> list[AssistantTool]:
        tools: list[AssistantTool] = [self._propose]
        if self._memories is not None:
            tools.append(self._memories)
        tools.extend(self._life_read)
        tools.extend(self._life_write)
        if self._browse is not None:
            tools.append(self._browse)
        tools.extend(self._app_tools)
        if self._connect is not None:
            tools.append(self._connect)
        return tools


    def for_schedule(self) -> list[AssistantTool]:
        """No browser and no proposals or connect links (see the module docstring)."""
        tools: list[AssistantTool] = []
        if self._memories is not None:
            tools.append(self._memories)
        # Reading the user's list is fine in a run; changing it is not.
        tools.extend(self._life_read)
        tools.extend(self._app_tools)
        return tools




def delivery_app(delivery: ScheduleDelivery) -> str | None:
    return DELIVERY_TOOLKITS.get(delivery)





