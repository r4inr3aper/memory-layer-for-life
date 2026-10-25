"""The assistant's model steps through the Anthropic Messages API, streamed."""

import base64
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final, Literal, cast

import anthropic
from anthropic import AsyncAnthropic, omit
from anthropic.types import (
    DocumentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
    ToolParam,
    ToolResultBlockParam,
)

from app.core.config import EffortLevel
from app.domain.errors import (
    AssistantBillingError,
    AssistantModelError,
    AssistantRefusedError,
    AssistantTruncatedError,
)
from app.integrations.anthropic_calls import PROVIDER_NAME, AnthropicCallObserver
from app.integrations.anthropic_errors import describe_provider_failure
from app.integrations.assistant.base import (
    AssistantText,
    Attachment,
    ModelStep,
    StepRequest,
    TextSink,
    ToolDefinition,
    ToolResults,
    ToolUse,
    TranscriptItem,
    UserText,
)
from app.integrations.llm_calls import LlmCallSpec

if TYPE_CHECKING:
    from anthropic.types import ContentBlock

_CONTEXT_EXHAUSTED: Final = "model_context_window_exceeded"
ImageMediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]


def to_tool_param(tool: ToolDefinition) -> ToolParam:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": dict(tool.input_schema),
    }


def attachment_block(attachment: Attachment) -> ImageBlockParam | DocumentBlockParam:
    """An attached file as the content block the Messages API reads: PDFs as documents,
    images as images. The chat service accepts only these types."""
    data = base64.b64encode(attachment.data).decode("ascii")
    if attachment.media_type == "application/pdf":
        document: DocumentBlockParam = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            "title": attachment.name,
        }
        return document
    image: ImageBlockParam = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": cast("ImageMediaType", attachment.media_type),
            "data": data,
        },
    }
    return image


def to_message_params(transcript: Sequence[TranscriptItem]) -> list[MessageParam]:
    """Translate the transcript into Messages API turns.

    A step's own content blocks are sent back unchanged: the API requires reasoning
    blocks to come back exactly as they were produced.
    """
    params: list[MessageParam] = []
    for item in transcript:
        match item:
            case UserText(text=text, attachments=()):
                params.append({"role": "user", "content": text})
            case UserText(text=text, attachments=attachments):
                parts: list[ImageBlockParam | DocumentBlockParam | TextBlockParam] = [
                    attachment_block(attachment) for attachment in attachments
                ]
                parts.append({"type": "text", "text": text})
                params.append({"role": "user", "content": parts})
            case AssistantText(text=text):
                params.append({"role": "assistant", "content": text})
            case ModelStep(provider_content=content):
                params.append(
                    {"role": "assistant", "content": cast("list[ContentBlock]", list(content))}
                )
            case ToolResults(results=results):
                blocks: list[ToolResultBlockParam] = [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                    for result in results
                ]
                params.append({"role": "user", "content": blocks})
    return params


class AnthropicAssistantModel:
    """``AssistantModel`` backed by a Claude model.

    The client is the process-wide one owned by ``AnthropicClientManager``. Every call
    goes through the observer, so it is written to the call log like any other.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        *,
        model: str,
        effort: EffortLevel,
        max_tokens: int,
        observer: AnthropicCallObserver,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: EffortLevel = effort
        self._max_tokens = max_tokens
        self._observer = observer

    @property
    def model(self) -> str:
        return self._model

    async def step(self, request: StepRequest, on_text: TextSink) -> ModelStep:
        spec = LlmCallSpec(
            provider=PROVIDER_NAME,
            operation=request.operation,
            requested_model=self._model,
            prompt_version=request.prompt_version,
            effort=self._effort,
            max_tokens=self._max_tokens,
            context=request.call_context,
        )
        # The instructions are identical for every request, so they are cached together
        # with the tool definitions that precede them. The per-request context is not.
        system: list[TextBlockParam] = [
            {"type": "text", "text": request.instructions, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": request.context},
        ]
        async with self._observer.observe(spec) as call:
            try:
                async with self._client.messages.stream(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=to_message_params(request.transcript),
                    tools=[to_tool_param(tool) for tool in request.tools] or omit,
                    output_config={"effort": self._effort},
                ) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            await on_text(event.text)
                    message = await stream.get_final_message()
                    request_id = stream.request_id
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
                failure = describe_provider_failure(error, model=self._model)
                if failure.billing:
                    raise AssistantBillingError(failure.message) from error
                raise AssistantModelError(failure.message, retryable=failure.retryable) from error
            # Noted before the answer is judged: an unusable answer was still billed.
            call.answered(message, request_id=request_id)

            if message.stop_reason == "refusal":
                raise AssistantRefusedError("The model declined to answer this request.")
            if message.stop_reason == _CONTEXT_EXHAUSTED:
                raise AssistantTruncatedError(
                    "This conversation is too long for the model. Start a new side chat."
                )
            tool_uses = tuple(
                ToolUse(
                    id=block.id,
                    name=block.name,
                    input=block.input if isinstance(block.input, dict) else {},
                )
                for block in message.content
                if block.type == "tool_use"
            )
            if message.stop_reason == "max_tokens" and tool_uses:
                # A tool call cut off mid-way has incomplete arguments and must not run.
                raise AssistantTruncatedError(
                    "The model reached its output limit while preparing a tool call."
                )
            text = "".join(block.text for block in message.content if block.type == "text")
            return ModelStep(
                text=text,
                tool_uses=tool_uses,
                stop_reason=message.stop_reason,
                provider_content=tuple(message.content),
            )
