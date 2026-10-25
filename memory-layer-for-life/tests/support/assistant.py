"""Doubles for the assistant app: a scripted model, a token verifier, and fake Composio and
Browserbase clients. The real services run around them, so tests exercise everything but
the network."""

import asyncio
import itertools
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.errors import AuthenticationRequiredError
from app.domain.principal import Principal
from app.integrations.assistant.base import ModelStep, StepRequest, TextSink, ToolUse
from app.integrations.browserbase import BrowserRun
from app.integrations.composio import (
    ComposioAccount,
    ComposioExecution,
    ComposioLink,
    ComposioNotFoundError,
    ComposioRejectedError,
    ComposioToolMatch,
)
from app.integrations.expo_push import PushMessage, PushReceipt

_ids = itertools.count(1)


@dataclass(frozen=True)
class ScriptedStep:
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = ()
    # The pieces the text streams in. Defaults to the whole text at once.
    chunks: tuple[str, ...] | None = None


def say(text: str, *chunks: str) -> ScriptedStep:
    return ScriptedStep(text=text, chunks=chunks or None)


def call(
    name: str, arguments: Mapping[str, object] | None = None, *, text: str = ""
) -> ScriptedStep:
    return ScriptedStep(
        text=text,
        tool_uses=(ToolUse(id=f"toolu_{next(_ids)}", name=name, input=dict(arguments or {})),),
    )


@dataclass(frozen=True)
class RecordedRequest:
    """A step request with its transcript copied, since the agent keeps appending to it."""

    request: StepRequest
    transcript: tuple[object, ...]


class ScriptedAssistantModel:
    """An ``AssistantModel`` that answers from a script and records every request.

    Set ``gate`` to hold every step until the test releases it.
    """

    model = "scripted-assistant"

    def __init__(self, *steps: ScriptedStep | Exception) -> None:
        self._steps: deque[ScriptedStep | Exception] = deque(steps)
        self.requests: list[RecordedRequest] = []
        self.gate: asyncio.Event | None = None

    def script(self, *steps: ScriptedStep | Exception) -> None:
        self._steps.extend(steps)

    @property
    def remaining(self) -> int:
        return len(self._steps)

    async def step(self, request: StepRequest, on_text: TextSink) -> ModelStep:
        self.requests.append(RecordedRequest(request, tuple(request.transcript)))
        if self.gate is not None:
            await self.gate.wait()
        if not self._steps:
            raise AssertionError("the scripted model has no step left")
        step = self._steps.popleft()
        if isinstance(step, Exception):
            raise step
        for chunk in step.chunks if step.chunks is not None else (step.text,):
            if chunk:
                await on_text(chunk)
        return ModelStep(
            text=step.text,
            tool_uses=step.tool_uses,
            stop_reason="tool_use" if step.tool_uses else "end_turn",
            provider_content=(("scripted", step.text),),
        )


class StaticTokenVerifier:
    """A ``TokenVerifier`` that knows the tokens it issued."""

    def __init__(self) -> None:
        self._principals: dict[str, Principal] = {}

    def issue(self, principal: Principal) -> str:
        token = f"token-{principal.id}-{principal.email}-{principal.display_name}"
        self._principals[token] = principal
        return token

    async def verify(self, token: str) -> Principal:
        try:
            return self._principals[token]
        except KeyError:
            raise AuthenticationRequiredError("The access token is not valid.") from None


def new_principal(name: str = "Ada") -> Principal:
    return Principal(id=uuid.uuid4(), email=f"{name.lower()}@example.com", display_name=name)


@dataclass
class _StoredAccount:
    account: ComposioAccount
    user_id: str


@dataclass
class FakeComposio:
    """In-memory stand-in for ``ComposioClient``.

    ``auth_configs`` are the project's, by toolkit. Composio refuses to set up managed
    sign-in for toolkits in ``managed_auth_refused``, and auth configs in
    ``removed_auth_configs`` were deleted in Composio.
    """

    auth_configs: dict[str, str] = field(default_factory=dict)
    created_auth_configs: list[str] = field(default_factory=list)
    managed_auth_refused: set[str] = field(default_factory=set)
    removed_auth_configs: set[str] = field(default_factory=set)
    auth_config_lookups: list[str] = field(default_factory=list)
    tools: dict[str, list[ComposioToolMatch]] = field(default_factory=dict)
    execution: ComposioExecution = field(
        default_factory=lambda: ComposioExecution(successful=True, data={"ok": True}, error=None)
    )
    accounts: dict[str, _StoredAccount] = field(default_factory=dict)
    links: list[tuple[str, str, str | None]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    sessions: dict[str, tuple[str, str, tuple[str, ...]]] = field(default_factory=dict)
    executions: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    def add_account(
        self,
        user_id: uuid.UUID,
        toolkit: str,
        *,
        status: str = "ACTIVE",
        label: str | None = None,
        email: str | None = None,
        account_id: str | None = None,
    ) -> ComposioAccount:
        account = ComposioAccount(
            id=account_id or f"ca_{next(_ids)}",
            status=status,
            toolkit_slug=toolkit,
            auth_config_id=None,
            label=label,
            email=email,
        )
        self.accounts[account.id] = _StoredAccount(account, str(user_id))
        return account

    async def list_active_accounts(self, user_id: str) -> list[ComposioAccount]:
        return [
            stored.account
            for stored in self.accounts.values()
            if stored.user_id == user_id and stored.account.status == "ACTIVE"
        ]

    async def get_account(self, account_id: str) -> ComposioAccount:
        stored = self.accounts.get(account_id)
        if stored is None:
            raise ComposioNotFoundError("Composio", "the requested record does not exist.")
        return stored.account

    async def delete_account(self, account_id: str) -> None:
        if self.accounts.pop(account_id, None) is None:
            raise ComposioNotFoundError("Composio", "the requested record does not exist.")
        self.deleted.append(account_id)

    async def find_auth_config(self, toolkit_slug: str) -> str | None:
        self.auth_config_lookups.append(toolkit_slug)
        return self.auth_configs.get(toolkit_slug)

    async def create_managed_auth_config(self, toolkit_slug: str) -> str:
        # A network call takes time: let concurrent connects interleave here.
        await asyncio.sleep(0)
        if toolkit_slug in self.managed_auth_refused:
            raise ComposioRejectedError(
                "Composio", "rejected the request (HTTP 400).", http_status=400
            )
        config_id = f"ac_managed_{toolkit_slug}_{next(_ids)}"
        self.auth_configs[toolkit_slug] = config_id
        self.created_auth_configs.append(toolkit_slug)
        return config_id

    def remove_auth_config(self, toolkit_slug: str) -> None:
        """Delete the project's auth config for the toolkit, as in Composio's dashboard."""
        self.removed_auth_configs.add(self.auth_configs.pop(toolkit_slug))

    async def link_account(
        self, user_id: str, auth_config_id: str, *, callback_url: str | None
    ) -> ComposioLink:
        if auth_config_id in self.removed_auth_configs:
            raise ComposioNotFoundError("Composio", "the requested record does not exist.")
        self.links.append((user_id, auth_config_id, callback_url))
        number = next(_ids)
        return ComposioLink(
            request_id=f"link_{number}",
            redirect_url=f"https://connect.composio.dev/link/lk_{number}",
            connected_account_id=f"ca_pending_{number}",
        )

    async def create_session(
        self, user_id: str, toolkit_slug: str, account_ids: Sequence[str]
    ) -> str:
        session_id = f"session_{next(_ids)}"
        self.sessions[session_id] = (user_id, toolkit_slug, tuple(account_ids))
        return session_id

    async def search_tools(
        self, session_id: str, use_case: str, *, known_fields: Mapping[str, object] | None = None
    ) -> list[ComposioToolMatch]:
        return self.tools.get(self.sessions[session_id][1], [])

    async def execute_tool(
        self, session_id: str, tool_slug: str, arguments: Mapping[str, object]
    ) -> ComposioExecution:
        self.executions.append((session_id, tool_slug, dict(arguments)))
        return self.execution


def browser_run(
    status: str = "RUNNING",
    *,
    run_id: str = "run_1",
    session_id: str | None = "bb_session_1",
    summary: str | None = None,
    login_required: bool = False,
) -> BrowserRun:
    return BrowserRun(
        run_id=run_id,
        status=status,
        session_id=session_id,
        summary=summary,
        source_url="https://example.com/page" if summary else None,
        login_required=login_required,
        error=None,
    )


class FakeBrowser:
    """Stand-in for ``BrowserbaseClient``: starts with one run state, then polls through more."""

    def __init__(self, start: BrowserRun, *polls: BrowserRun) -> None:
        self._start = start
        self._polls: deque[BrowserRun] = deque(polls)
        self._last = start
        self.tasks: list[str] = []

    async def start_run(self, task: str) -> BrowserRun:
        self.tasks.append(task)
        return self._start

    async def get_run(self, run_id: str) -> BrowserRun:
        if self._polls:
            self._last = self._polls.popleft()
        return self._last

    async def live_view_url(self, session_id: str) -> str | None:
        return f"https://live.browserbase.example/{session_id}"


class FakeTime:
    """A sleep and a monotonic clock that advance together, so polling loops run instantly."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakePushClient:
    """Stand-in for ``ExpoPushClient``: records messages; listed tokens report as dead."""

    sent: list[PushMessage] = field(default_factory=list)
    dead_tokens: set[str] = field(default_factory=set)

    async def send(self, messages: Sequence[PushMessage]) -> PushReceipt:
        self.sent.extend(messages)
        dead = tuple(m.token for m in messages if m.token in self.dead_tokens)
        return PushReceipt(sent=len(messages) - len(dead), unregistered_tokens=dead)


@dataclass
class FakeIdentityAdmin:
    """Stand-in for ``SupabaseAdminClient``."""

    deleted: list[uuid.UUID] = field(default_factory=list)

    async def delete_user(self, user_id: uuid.UUID) -> None:
        self.deleted.append(user_id)
