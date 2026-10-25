"""What every assistant tool shares: the protocol, its output, and strict input parsing.

Tool input is model output and therefore untrusted: each tool validates it with a strict
model and reports problems back to the model as an error result rather than raising.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from app.integrations.assistant.base import ToolDefinition
from app.services.assistant.context import TurnContext


@dataclass(frozen=True, slots=True)
class ToolOutput:
    content: str
    is_error: bool = False


class AssistantTool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...

    @property
    def label(self) -> str:
        """What the app shows while the tool runs."""
        ...

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput: ...


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def invalid_input(error: ValidationError) -> ToolOutput:
    details = "; ".join(
        f"{'.'.join(str(part) for part in item['loc']) or 'input'}: {item['msg']}"
        for item in error.errors(include_input=False, include_url=False)[:5]
    )
    return ToolOutput(f"The tool input is not valid: {details}", is_error=True)
