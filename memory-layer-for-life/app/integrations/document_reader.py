"""Reading a photo or a PDF into text, so it can become memory evidence (ADR-047).

The model transcribes the text it sees, in reading order, and adds a short description of
what is not text (what a photo shows). It is told to add nothing else: what it writes is
stored as the user's evidence, and memories quote it.
"""

from typing import Final, Protocol

import anthropic

from app.domain.enums import LlmOperation
from app.domain.errors import FileReadError
from app.integrations.anthropic_calls import PROVIDER_NAME, AnthropicCallObserver
from app.integrations.anthropic_errors import describe_provider_failure
from app.integrations.assistant.anthropic_model import attachment_block
from app.integrations.assistant.base import Attachment
from app.integrations.llm_calls import LlmCallContext, LlmCallSpec

READER_PROMPT_VERSION: Final = "1.0"
DEFAULT_MAX_TOKENS: Final = 4_000

_INSTRUCTIONS: Final = (
    "You turn a file a person wants to remember into plain text. Write every piece of text "
    "in the file exactly as written, in reading order, keeping numbers, dates, names, and "
    "amounts as they are. Then, on a new line starting with 'Description:', describe in "
    "one or two sentences anything important that is not text, such as what a photo shows. "
    "Do not summarize, interpret, or add anything else. If the file holds nothing readable, "
    "write only 'Description:' and what it shows."
)


class DocumentReader(Protocol):
    async def read(self, file: Attachment, *, context: LlmCallContext) -> str:
        """The file's text and a description; raises ``FileReadError``."""
        ...


class AnthropicDocumentReader:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        observer: AnthropicCallObserver,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._observer = observer
        self._max_tokens = max_tokens

    async def read(self, file: Attachment, *, context: LlmCallContext) -> str:
        spec = LlmCallSpec(
            provider=PROVIDER_NAME,
            operation=LlmOperation.TRANSCRIPTION,
            requested_model=self._model,
            prompt_version=READER_PROMPT_VERSION,
            max_tokens=self._max_tokens,
            context=context,
        )
        async with self._observer.observe(spec) as call:
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=_INSTRUCTIONS,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                attachment_block(file),
                                {"type": "text", "text": "Transcribe this file."},
                            ],
                        }
                    ],
                )
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
                failure = describe_provider_failure(error, model=self._model)
                raise FileReadError(failure.message) from error
            call.answered(message)
            if message.stop_reason == "refusal":
                raise FileReadError("This file could not be read.")
            text = "".join(block.text for block in message.content if block.type == "text")
            if not text.strip():
                raise FileReadError("Nothing could be read from this file.")
            return text.strip()
