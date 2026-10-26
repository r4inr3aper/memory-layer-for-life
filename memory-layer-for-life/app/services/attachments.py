"""The user's files attached to app actions, such as a resume to a job application email
(ADR-050).

The assistant never handles file contents. Where an action takes a file (Gmail's
``attachment``), it writes a reference instead: ``{"document": "resume"}``, or a
document's title. Just before the action runs, each reference is resolved here: the
user's kept file is staged with Composio for that action and the reference replaced with
what the action expects. A reference that cannot be resolved stops the action, so
nothing goes out without the file the user expects.

A job application draft pins its references to document ids when it is prepared
(``pin``): the card shows exactly what will be attached, and sending attaches those
files, not whatever is the resume by then.
"""

import uuid
from collections.abc import Mapping
from typing import Final

from app.integrations.composio import ComposioClient
from app.services.documents import DocumentService, DocumentView, StoredFile

REFERENCE_KEY: Final = "document"


def references(arguments: object) -> list[str]:
    """The file references in an action's arguments, each once, in order."""
    found: list[str] = []

    def walk(value: object) -> None:
        reference = _reference(value)
        if reference is not None:
            if reference not in found:
                found.append(reference)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(arguments)
    return found


class AppAttachments:
    def __init__(self, documents: DocumentService, composio: ComposioClient) -> None:
        self._documents = documents
        self._composio = composio

    async def pin(
        self, owner_id: uuid.UUID, arguments: Mapping[str, object]
    ) -> tuple[dict[str, object], list[DocumentView]]:
        """Each reference resolved to the document it names, written as that document's
        id, and the documents. Raises AttachmentUnavailableError for one that cannot be
        attached."""
        pinned: dict[str, object] = {}
        attached: dict[uuid.UUID, DocumentView] = {}
        for reference in references(arguments):
            document = await self._documents.attachable(owner_id, reference)
            pinned[reference] = {REFERENCE_KEY: str(document.id)}
            attached.setdefault(document.id, document)
        return _substituted(arguments, pinned), list(attached.values())

    async def stage(
        self,
        owner_id: uuid.UUID,
        arguments: Mapping[str, object],
        *,
        toolkit: str,
        tool_slug: str,
    ) -> dict[str, object]:
        """The arguments with each reference replaced by the file, staged with Composio
        for this action. Arguments without references come back unchanged."""
        found = references(arguments)
        if not found:
            return dict(arguments)
        staged: dict[str, object] = {}
        for reference in found:
            file = await self._file(owner_id, reference)
            uploaded = await self._composio.upload_file(
                toolkit.lower(),
                tool_slug,
                filename=file.document.file_name,
                mimetype=file.document.media_type,
                data=file.data,
            )
            staged[reference] = uploaded.as_argument()
        return _substituted(arguments, staged)

    async def _file(self, owner_id: uuid.UUID, reference: str) -> StoredFile:
        try:
            # Pinned by a draft: exactly that document, or nothing if it was deleted.
            document_id = uuid.UUID(reference)
        except ValueError:
            document_id = (await self._documents.attachable(owner_id, reference)).id
        return await self._documents.attachment(owner_id, document_id)


def _reference(value: object) -> str | None:
    """The reference a value is, when it is one: a mapping with only ``document``."""
    if isinstance(value, Mapping) and len(value) == 1:
        reference = value.get(REFERENCE_KEY)
        if isinstance(reference, str) and reference.strip():
            return reference.strip()
    return None


def _substituted(
    arguments: Mapping[str, object], replacements: Mapping[str, object]
) -> dict[str, object]:
    def replace(value: object) -> object:
        reference = _reference(value)
        if reference is not None:
            return replacements.get(reference, value)
        if isinstance(value, Mapping):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    return {key: replace(item) for key, item in arguments.items()}
