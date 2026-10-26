"""The assistant's tools for the user's documents (ADR-049): reading one whole, such as the
resume for a job application, and finding passages in all of them.

Documents are the user's own files, given to the assistant to read; deleting one makes it
unreadable at once, because these tools read the stored text on every call.
"""

from collections.abc import Mapping
from typing import Final

from pydantic import Field, ValidationError

from app.integrations.assistant.base import ToolDefinition
from app.services.assistant.context import TurnContext
from app.services.assistant.tool_base import ToolInput, ToolOutput, invalid_input
from app.services.documents import RESUME, DocumentService

# About ten thousand tokens: a resume or a long letter whole, a book never.
_MAX_READ_CHARS: Final = 40_000
_MAX_PASSAGES: Final = 8


class ReadDocumentInput(ToolInput):
    document: str = Field(min_length=1, max_length=300)


class ReadDocumentTool:
    label = "Reading your files"
    definition = ToolDefinition(
        name="read_document",
        description=(
            "Read the full text of one of the user's uploaded documents, listed by title in "
            "the context. Use 'resume' for the user's resume. Read it whenever a request "
            "depends on it: a job application, a cover letter, or a question about their "
            "work, skills, or education."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "document": {
                    "type": "string",
                    "description": "'resume', or the document's title as listed.",
                },
            },
            "required": ["document"],
        },
    )

    def __init__(self, documents: DocumentService) -> None:
        self._documents = documents

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            parsed = ReadDocumentInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        found = await self._documents.read(
            turn.principal.id, parsed.document, max_chars=_MAX_READ_CHARS
        )
        if found is None:
            titles = [view.title for view in await self._documents.for_owner(turn.principal.id)]
            if not titles:
                return ToolOutput(
                    "The user has not uploaded any documents. If you need their resume, ask "
                    "them to add it in Settings, My files."
                )
            if parsed.document.strip().lower() == RESUME:
                return ToolOutput(
                    "None of the user's documents is marked as their resume. Their documents: "
                    + "; ".join(titles)
                    + ". Read one by title, or ask the user which is their resume."
                )
            return ToolOutput(
                "No document matches that. The user's documents: " + "; ".join(titles) + ".",
                is_error=True,
            )
        document = found.document
        header = f"Document: {document.title}" + (
            " (the user's resume)" if document.is_resume else ""
        )
        note = (
            "\n\n[The document is longer; this is its beginning. Use search_documents for "
            "other parts.]"
            if found.truncated
            else ""
        )
        return ToolOutput(f"{header}\n\n{found.text}{note}")


class SearchDocumentsInput(ToolInput):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=_MAX_PASSAGES)


class SearchDocumentsTool:
    label = "Searching your files"
    definition = ToolDefinition(
        name="search_documents",
        description=(
            "Find passages in the user's uploaded documents that contain the given words. "
            "Use it for a detail in a long document; read short ones whole with "
            "read_document."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The words to look for, such as 'notice period' or 'GPA'.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_PASSAGES,
                    "description": "How many passages to return; 5 unless you need more.",
                },
            },
            "required": ["query"],
        },
    )

    def __init__(self, documents: DocumentService) -> None:
        self._documents = documents

    async def run(self, arguments: Mapping[str, object], turn: TurnContext) -> ToolOutput:
        try:
            parsed = SearchDocumentsInput.model_validate(arguments)
        except ValidationError as error:
            return invalid_input(error)
        passages = await self._documents.search(turn.principal.id, parsed.query, limit=parsed.limit)
        if not passages:
            return ToolOutput(
                "No passage of the user's documents contains those words. Try other words, or "
                "read the document whole."
            )
        lines = ["Passages from the user's documents, best first (matches in << >>):"]
        for number, passage in enumerate(passages, start=1):
            where = f", page {passage.page}" if passage.page is not None else ""
            lines.append(f"{number}. [{passage.document_title}{where}] {passage.snippet}")
        return ToolOutput("\n".join(lines))
