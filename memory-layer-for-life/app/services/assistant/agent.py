"""The assistant's tool-use loop.

Each step sends the conversation and the tools to the model. When the model asks for
tools, they run one after another and their results go back in the next step; when it
answers without tools, the turn is done. A turn makes at most ``max_steps`` model calls.

A tool that fails reports the failure to the model as a result, so the model can recover
or explain. Only a failure of the model call itself ends the turn with an error.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog

from app.domain.enums import LlmOperation
from app.domain.errors import DomainError
from app.integrations.assistant.base import (
    AssistantModel,
    AssistantText,
    StepRequest,
    ToolResult,
    ToolResults,
    TranscriptItem,
    UserText,
)
from app.integrations.llm_calls import LlmCallContext
from app.services.assistant.context import TextDelta, ToolStarted, TurnContext
from app.services.assistant.prompts import ASSISTANT_PROMPT_VERSION
from app.services.assistant.tool_base import AssistantTool, ToolOutput

logger = structlog.get_logger(__name__)

STEP_BUDGET_NOTE: Final = (
    "I stopped before finishing because this needed more steps than I am allowed in one "
    "reply. Ask me to continue and I will pick up from here."
)
_UNEXPECTED_TOOL_FAILURE: Final = "The tool failed unexpectedly. Try another approach."
_PARAGRAPH: Final = "\n\n"


@dataclass(frozen=True, slots=True)
class AgentResult:
    text: str
    steps: int
    completed: bool


def merge_history(messages: Sequence[UserText | AssistantText]) -> list[TranscriptItem]:
    """Prepare stored messages for the model.

    The conversation must open with the user, and two messages in a row from the same
    side, as left behind by a failed turn, are joined into one.
    """
    merged: list[UserText | AssistantText] = []
    for message in messages:
        if not merged and isinstance(message, AssistantText):
            continue
        previous = merged[-1] if merged else None
        if isinstance(previous, UserText) and isinstance(message, UserText):
            merged[-1] = UserText(
                f"{previous.text}{_PARAGRAPH}{message.text}",
                attachments=previous.attachments + message.attachments,
            )
        elif isinstance(previous, AssistantText) and isinstance(message, AssistantText):
            merged[-1] = AssistantText(f"{previous.text}{_PARAGRAPH}{message.text}")
        else:
            merged.append(message)
    return list(merged)


class AssistantAgent:
    def __init__(self, model: AssistantModel, *, max_steps: int) -> None:
        self._model = model
        self._max_steps = max_steps

    @property
    def model(self) -> str:
        return self._model.model

    async def run(
        self,
        *,
        instructions: str,
        context: str,
        history: Sequence[UserText | AssistantText],
        tools: Sequence[AssistantTool],
        turn: TurnContext,
        operation: LlmOperation,
        call_context: LlmCallContext,
    ) -> AgentResult:
        transcript = merge_history(history)
        by_name = {tool.definition.name: tool for tool in tools}
        definitions = [tool.definition for tool in tools]
        visible: list[str] = []
        streamed_any = False

        async def stream_text(text: str) -> None:
            # Text of a later step starts a new paragraph after what was already shown.
            nonlocal streamed_any
            if not streamed_any and visible:
                await turn.emit(TextDelta(_PARAGRAPH))
            streamed_any = True
            await turn.emit(TextDelta(text))

        for step_number in range(1, self._max_steps + 1):
            streamed_any = False
            step = await self._model.step(
                StepRequest(
                    instructions=instructions,
                    context=context,
                    transcript=transcript,
                    tools=definitions,
                    operation=operation,
                    call_context=call_context,
                    prompt_version=ASSISTANT_PROMPT_VERSION,
                ),
                on_text=stream_text,
            )
            transcript.append(step)
            if step.text.strip():
                visible.append(step.text.strip())
            if not step.tool_uses:
                return AgentResult(text=_PARAGRAPH.join(visible), steps=step_number, completed=True)

            results = []
            for tool_use in step.tool_uses:
                tool = by_name.get(tool_use.name)
                if tool is None:
                    output = ToolOutput(f"There is no tool named {tool_use.name}.", is_error=True)
                else:
                    await turn.emit(ToolStarted(tool=tool.definition.name, label=tool.label))
                    output = await self._run_tool(tool, tool_use.input, turn)
                results.append(
                    ToolResult(
                        tool_use_id=tool_use.id, content=output.content, is_error=output.is_error
                    )
                )
            transcript.append(ToolResults(tuple(results)))

        visible.append(STEP_BUDGET_NOTE)
        await stream_note(turn, visible)
        return AgentResult(text=_PARAGRAPH.join(visible), steps=self._max_steps, completed=False)

    @staticmethod
    async def _run_tool(
        tool: AssistantTool, arguments: Mapping[str, object], turn: TurnContext
    ) -> ToolOutput:
        name = tool.definition.name
        try:
            return await tool.run(arguments, turn)
        except DomainError as error:
            logger.warning("assistant_tool_failed", tool=name, error_code=error.code)
            return ToolOutput(error.message, is_error=True)
        except Exception:
            logger.exception("assistant_tool_crashed", tool=name)
            return ToolOutput(_UNEXPECTED_TOOL_FAILURE, is_error=True)


async def stream_note(turn: TurnContext, visible: list[str]) -> None:
    """Show the closing note the same way streamed text is shown."""
    if len(visible) > 1:
        await turn.emit(TextDelta(_PARAGRAPH))
    await turn.emit(TextDelta(visible[-1]))
