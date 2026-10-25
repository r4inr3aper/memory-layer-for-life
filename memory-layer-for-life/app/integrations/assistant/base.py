"""Provider-independent contract for one step of the assistant's tool-use loop.

A step sends the conversation so far and the available tools to the model, streams the
visible text as it is written, and returns what the model wants next: either a final
answer or tool calls. The loop that runs tools and calls ``step`` again lives in
``app.services.assistant`` and never imports a provider SDK.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.domain.enums import LlmOperation
from app.integrations.llm_calls import LlmCallContext


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ToolUse:
    """One tool call the model asked for. ``input`` is untrusted model output."""

    id: str
    name: str
    input: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file sent with a user message: an image or a PDF, as raw bytes."""

    name: str
    media_type: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class UserText:
    text: str
    # Only the message that starts a turn carries its files; earlier messages carry a
    # note of what was attached instead.
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True, slots=True)
class AssistantText:
    """An earlier reply, read back from the thread's history."""

    text: str


@dataclass(frozen=True, slots=True)
class ModelStep:
    """What the model answered in one step.

    ``provider_content`` is the answer in the provider's own form. Only the adapter that
    produced it reads it, to send it back unchanged in the next step, which keeps
    reasoning blocks and their signatures intact.
    """

    text: str
    tool_uses: tuple[ToolUse, ...]
    stop_reason: str | None
    provider_content: tuple[object, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ToolResults:
    results: tuple[ToolResult, ...]


TranscriptItem = UserText | AssistantText | ModelStep | ToolResults
TextSink = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class StepRequest:
    """``instructions`` are identical across requests and cached by the provider.
    ``context`` changes per request, for example the current time.
    """

    instructions: str
    context: str
    transcript: Sequence[TranscriptItem]
    tools: Sequence[ToolDefinition]
    operation: LlmOperation
    call_context: LlmCallContext
    prompt_version: str | None = None


class AssistantModel(Protocol):
    @property
    def model(self) -> str: ...

    async def step(self, request: StepRequest, on_text: TextSink) -> ModelStep:
        """Make one model call.

        Raises ``AssistantModelError`` or one of its subclasses when the call fails or the
        answer cannot be used.
        """
        ...
