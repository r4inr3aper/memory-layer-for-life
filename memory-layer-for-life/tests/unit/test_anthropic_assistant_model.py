"""The assistant's Anthropic adapter: streaming, transcript translation, and failures."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest
from anthropic import omit

from app.domain.enums import LlmCallOrigin, LlmCallStatus, LlmOperation
from app.domain.errors import (
    AssistantBillingError,
    AssistantModelError,
    AssistantRefusedError,
    AssistantTruncatedError,
)
from app.integrations.anthropic_calls import AnthropicCallObserver
from app.integrations.assistant.anthropic_model import AnthropicAssistantModel, to_message_params
from app.integrations.assistant.base import (
    AssistantText,
    ModelStep,
    StepRequest,
    ToolDefinition,
    ToolResult,
    ToolResults,
    UserText,
)
from app.integrations.llm_calls import LlmCallContext, LlmCallRecord

HTTP_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
TOOL = ToolDefinition(name="echo", description="Echo.", input_schema={"type": "object"})


def message(*blocks: Any, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        model="claude-sonnet-5-5",
        usage=SimpleNamespace(
            input_tokens=50,
            output_tokens=20,
            cache_read_input_tokens=400,
            cache_creation_input_tokens=None,
        ),
        _request_id="req_1",
    )


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, arguments: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="toolu_1", name=name, input=arguments)


class FakeStream:
    # Like the SDK stream's property. None makes the adapter fall back to the message's id.
    request_id: str | None = None

    def __init__(self, deltas: list[str], final: SimpleNamespace) -> None:
        self._deltas = deltas
        self._final = final

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def __aiter__(self) -> Any:
        for delta in self._deltas:
            yield SimpleNamespace(type="text", text=delta)
        yield SimpleNamespace(type="message_stop")

    async def get_final_message(self) -> SimpleNamespace:
        return self._final


class RecordingRecorder:
    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    async def record(self, record: LlmCallRecord) -> None:
        self.records.append(record)


def adapter(
    result: FakeStream | Exception,
) -> tuple[AnthropicAssistantModel, MagicMock, RecordingRecorder]:
    client = MagicMock()
    if isinstance(result, Exception):
        client.messages.stream = MagicMock(side_effect=result)
    else:
        client.messages.stream = MagicMock(return_value=result)
    recorder = RecordingRecorder()
    model = AnthropicAssistantModel(
        client,
        model="claude-sonnet-5-5",
        effort="medium",
        max_tokens=8000,
        observer=AnthropicCallObserver(recorder),
    )
    return model, client, recorder


def request(*, tools: list[ToolDefinition] | None = None) -> StepRequest:
    return StepRequest(
        instructions="be Cooper",
        context="it is Sunday",
        transcript=[UserText("hi")],
        tools=[TOOL] if tools is None else tools,
        operation=LlmOperation.CHAT,
        call_context=LlmCallContext(origin=LlmCallOrigin.ASSISTANT),
        prompt_version="1.0",
    )


async def collect(
    model: AnthropicAssistantModel, step_request: StepRequest
) -> tuple[ModelStep, list[str]]:
    streamed: list[str] = []

    async def sink(text: str) -> None:
        streamed.append(text)

    return await model.step(step_request, sink), streamed


async def test_text_streams_and_the_step_is_returned() -> None:
    model, client, recorder = adapter(FakeStream(["Hel", "lo"], message(text_block("Hello"))))

    step, streamed = await collect(model, request())

    assert streamed == ["Hel", "lo"]
    assert (step.text, step.tool_uses, step.stop_reason) == ("Hello", (), "end_turn")
    kwargs = client.messages.stream.call_args.kwargs
    assert kwargs["system"][0] == {
        "type": "text",
        "text": "be Cooper",
        "cache_control": {"type": "ephemeral"},
    }
    assert kwargs["system"][1] == {"type": "text", "text": "it is Sunday"}
    assert kwargs["tools"] == [
        {"name": "echo", "description": "Echo.", "input_schema": {"type": "object"}}
    ]
    assert kwargs["output_config"] == {"effort": "medium"}
    record = recorder.records[0]
    assert (record.status, record.spec.operation, record.spec.context.origin) == (
        LlmCallStatus.SUCCEEDED,
        LlmOperation.CHAT,
        LlmCallOrigin.ASSISTANT,
    )
    assert (record.input_tokens, record.cache_read_input_tokens) == (50, 400)


async def test_tool_calls_are_returned_with_the_raw_content_for_the_next_step() -> None:
    final = message(text_block("Checking."), tool_block("echo", {"x": 1}), stop_reason="tool_use")
    model, _, _ = adapter(FakeStream(["Checking."], final))

    step, _ = await collect(model, request())

    assert [(use.name, dict(use.input)) for use in step.tool_uses] == [("echo", {"x": 1})]
    assert step.provider_content == tuple(final.content)


async def test_no_tools_are_sent_when_none_are_offered() -> None:
    model, client, _ = adapter(FakeStream([], message(text_block("ok"))))

    await collect(model, request(tools=[]))

    assert client.messages.stream.call_args.kwargs["tools"] is omit


async def test_a_refusal_is_an_error_but_its_call_is_still_logged() -> None:
    model, _, recorder = adapter(FakeStream([], message(stop_reason="refusal")))

    with pytest.raises(AssistantRefusedError):
        await collect(model, request())

    record = recorder.records[0]
    assert record.status is LlmCallStatus.FAILED
    assert record.input_tokens == 50


async def test_a_tool_call_cut_off_by_the_limit_never_runs() -> None:
    final = message(tool_block("echo", {}), stop_reason="max_tokens")
    model, _, _ = adapter(FakeStream([], final))

    with pytest.raises(AssistantTruncatedError):
        await collect(model, request())


async def test_an_exhausted_context_window_suggests_a_new_chat() -> None:
    model, _, _ = adapter(FakeStream([], message(stop_reason="model_context_window_exceeded")))

    with pytest.raises(AssistantTruncatedError, match="new side chat"):
        await collect(model, request())


@pytest.mark.parametrize(
    ("error", "expected", "retryable"),
    [
        (
            anthropic.InternalServerError(
                "overloaded", response=httpx2.Response(529, request=HTTP_REQUEST), body=None
            ),
            AssistantModelError,
            True,
        ),
        (
            anthropic.BadRequestError(
                "Your credit balance is too low to access the Anthropic API.",
                response=httpx2.Response(400, request=HTTP_REQUEST),
                body=None,
            ),
            AssistantBillingError,
            False,
        ),
        (
            anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=HTTP_REQUEST), body=None
            ),
            AssistantModelError,
            False,
        ),
    ],
    ids=["overloaded", "billing", "bad_key"],
)
async def test_provider_failures_become_domain_errors(
    error: Exception, expected: type[AssistantModelError], retryable: bool
) -> None:
    model, _, recorder = adapter(error)

    with pytest.raises(expected) as caught:
        await collect(model, request())

    assert caught.value.retryable is retryable
    assert recorder.records[0].status is LlmCallStatus.FAILED


def test_the_transcript_becomes_alternating_api_turns() -> None:
    step = ModelStep(
        text="",
        tool_uses=(),
        stop_reason="tool_use",
        provider_content=(tool_block("echo", {}),),
    )

    params = to_message_params(
        [
            UserText("hi"),
            AssistantText("hello"),
            UserText("echo this"),
            step,
            ToolResults((ToolResult(tool_use_id="toolu_1", content="done", is_error=False),)),
        ]
    )

    assert [param["role"] for param in params] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert params[3]["content"] == list(step.provider_content)
    assert params[4]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "done", "is_error": False}
    ]


class RealStream(FakeStream):
    """Like the SDK's stream: the final message is a real SDK object assembled from the
    stream, which carries no ``_request_id``; the id comes from the response headers."""

    request_id = "req_from_headers"


def real_message(text: str) -> anthropic.types.Message:
    return anthropic.types.Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 11, "output_tokens": 3},
        }
    )


async def test_a_streamed_reply_is_logged_with_the_request_id_from_the_stream() -> None:
    """Regression: the streamed final message has no ``_request_id``, which crashed every
    turn after its text had already streamed."""
    model, _, recorder = adapter(RealStream(["Hi"], real_message("Hi")))  # type: ignore[arg-type]

    step, streamed = await collect(model, request())

    assert (step.text, streamed) == ("Hi", ["Hi"])
    record = recorder.records[0]
    assert record.status is LlmCallStatus.SUCCEEDED
    assert record.request_id == "req_from_headers"
    assert (record.input_tokens, record.output_tokens) == (11, 3)
