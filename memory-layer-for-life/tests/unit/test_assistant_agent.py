"""The assistant's tool-use loop, run against a scripted model."""

from collections.abc import Mapping

import pytest

from app.domain.enums import LlmCallOrigin, LlmOperation
from app.domain.errors import AssistantBillingError, IntegrationError
from app.integrations.assistant.base import (
    AssistantText,
    ModelStep,
    ToolDefinition,
    ToolResults,
    UserText,
)
from app.integrations.llm_calls import LlmCallContext
from app.services.assistant.agent import STEP_BUDGET_NOTE, AssistantAgent, merge_history
from app.services.assistant.context import ProgressEvent, TextDelta, ToolStarted, TurnContext
from app.services.assistant.prompts import ASSISTANT_PROMPT_VERSION
from app.services.assistant.tools import ToolOutput
from tests.support.assistant import ScriptedAssistantModel, call, new_principal, say


class EchoTool:
    label = "Echoing"
    definition = ToolDefinition(
        name="echo", description="Echo the input.", input_schema={"type": "object"}
    )

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[Mapping[str, object]] = []
        self._fail_with = fail_with

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        self.calls.append(arguments)
        if self._fail_with is not None:
            raise self._fail_with
        return ToolOutput(f"echo: {arguments.get('text')}")


class Recorder:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def __call__(self, event: ProgressEvent) -> None:
        self.events.append(event)

    @property
    def streamed(self) -> str:
        return "".join(event.text for event in self.events if isinstance(event, TextDelta))


async def run_agent(
    model: ScriptedAssistantModel,
    *tools: EchoTool,
    history: list[UserText | AssistantText] | None = None,
    max_steps: int = 5,
) -> tuple[str, bool, Recorder]:
    recorder = Recorder()
    turn = TurnContext(
        principal=new_principal(), timezone_name="UTC", original_prompt="hi", emit=recorder
    )
    result = await AssistantAgent(model, max_steps=max_steps).run(
        instructions="be helpful",
        context="now",
        history=history or [UserText("hi")],
        tools=list(tools),
        turn=turn,
        operation=LlmOperation.CHAT,
        call_context=LlmCallContext(origin=LlmCallOrigin.ASSISTANT),
    )
    return result.text, result.completed, recorder


async def test_a_plain_answer_takes_one_step_and_streams() -> None:
    model = ScriptedAssistantModel(say("Hello there.", "Hello", " there."))

    text, completed, recorder = await run_agent(model)

    assert (text, completed) == ("Hello there.", True)
    assert recorder.streamed == "Hello there."
    assert len(model.requests) == 1


async def test_a_tool_result_goes_back_to_the_model() -> None:
    tool = EchoTool()
    model = ScriptedAssistantModel(call("echo", {"text": "ping"}), say("The tool said ping."))

    text, _, recorder = await run_agent(model, tool)

    assert text == "The tool said ping."
    assert tool.calls == [{"text": "ping"}]
    assert ToolStarted(tool="echo", label="Echoing") in recorder.events
    second = model.requests[1].transcript
    assert isinstance(second[-2], ModelStep)
    results = second[-1]
    assert isinstance(results, ToolResults)
    assert results.results[0].content == "echo: ping"
    assert results.results[0].is_error is False


async def test_text_from_several_steps_is_joined_by_paragraphs() -> None:
    model = ScriptedAssistantModel(
        call("echo", {"text": "x"}, text="Let me check."), say("Found it.")
    )

    text, _, recorder = await run_agent(model, EchoTool())

    assert text == "Let me check.\n\nFound it."
    assert recorder.streamed == "Let me check.\n\nFound it."


async def test_an_unknown_tool_is_reported_to_the_model() -> None:
    model = ScriptedAssistantModel(call("teleport"), say("I cannot do that."))

    text, _, _ = await run_agent(model)

    results = model.requests[1].transcript[-1]
    assert isinstance(results, ToolResults)
    assert results.results[0].is_error
    assert "no tool named teleport" in results.results[0].content
    assert text == "I cannot do that."


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (IntegrationError("Composio", "could not be reached."), "Composio: could not be reached."),
        (RuntimeError("boom"), "The tool failed unexpectedly. Try another approach."),
    ],
)
async def test_a_failing_tool_becomes_an_error_result(failure: Exception, expected: str) -> None:
    model = ScriptedAssistantModel(call("echo"), say("Sorry."))

    await run_agent(model, EchoTool(fail_with=failure))

    results = model.requests[1].transcript[-1]
    assert isinstance(results, ToolResults)
    assert results.results[0].content == expected
    assert results.results[0].is_error


async def test_a_model_failure_ends_the_turn() -> None:
    model = ScriptedAssistantModel(AssistantBillingError("no credit"))

    with pytest.raises(AssistantBillingError):
        await run_agent(model)


async def test_the_step_budget_ends_a_runaway_turn_with_a_note() -> None:
    model = ScriptedAssistantModel(*(call("echo", {"text": str(n)}) for n in range(3)))

    text, completed, recorder = await run_agent(model, EchoTool(), max_steps=3)

    assert completed is False
    assert text == STEP_BUDGET_NOTE
    assert recorder.streamed == STEP_BUDGET_NOTE


async def test_requests_carry_the_instructions_context_and_tools() -> None:
    model = ScriptedAssistantModel(say("ok"))

    await run_agent(model, EchoTool())

    request = model.requests[0].request
    assert (request.instructions, request.context) == ("be helpful", "now")
    assert [tool.name for tool in request.tools] == ["echo"]
    assert request.operation is LlmOperation.CHAT
    assert request.prompt_version == ASSISTANT_PROMPT_VERSION


def test_history_opens_with_the_user_and_joins_repeated_sides() -> None:
    merged = merge_history(
        [
            AssistantText("Scheduled task complete."),
            UserText("first"),
            UserText("second"),
            AssistantText("answer"),
        ]
    )

    assert merged == [UserText("first\n\nsecond"), AssistantText("answer")]
