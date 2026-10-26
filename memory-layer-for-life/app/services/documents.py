"""Documents the user uploads for the assistant to read when it is relevant, such as a
resume (ADR-049).

* Uploading reads the text without a model (``app.integrations.document_text``) and keeps
  it in passages. The same file twice is the same document. A scanned PDF has no text to
  read: it is refused, unless the operator lets the model read scans
  (``DOCUMENT_VISION_FALLBACK``), which costs one of the day's prompts.
* The original file is kept too (ADR-050), within a per-user allowance, so the assistant
  can attach it to an email: a resume to a job application. Documents uploaded before
  that kept only their text; uploading the same file again keeps it.
* A document is reference material, not memories: nothing is extracted from it. Deleting
  it deletes its passages, so the assistant can no longer read anything of it.
* The assistant lists the user's documents by title in its context, reads a whole
  document (``read``) when the request needs it (a job application needs the resume),
  searches passages by words (``search``) in long ones, and attaches kept files by
  reference (``attachable``, ``attachment``; see ``app.services.attachments``).
* The first document that looks like a resume is marked as the user's resume; the user
  can mark another. There is at most one.
"""

import asyncio
import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.documents import (
    DOCUMENT_TYPES,
    PDF,
    TITLE_MAX_CHARS,
    clean_text,
    looks_like_resume,
    passages,
    title_from_file_name,
)
from app.domain.enums import DocumentExtraction, LlmCallOrigin
from app.domain.errors import (
    AttachmentUnavailableError,
    DocumentStorageFullError,
    InvalidDocumentError,
    InvalidMemoryChangeError,
    RecordNotFoundError,
)
from app.domain.memory_policy import clean_title
from app.domain.principal import Principal
from app.domain.retrieval import any_term_tsquery, lexical_terms, normalize_query
from app.integrations.assistant.base import Attachment
from app.integrations.document_reader import DocumentReader
from app.integrations.document_text import DocumentText, has_text_layer, read_document_text
from app.integrations.llm_calls import LlmCallContext
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_file import DocumentFile
from app.repositories.document_repository import DocumentRepository
from app.repositories.user_repository import UserRepository
from app.services.life_state import user_timezone
from app.services.usage import UsageService

RESUME: Final = "resume"
_MEGABYTE: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class DocumentView:
    id: uuid.UUID
    title: str
    file_name: str
    media_type: str
    size_bytes: int
    is_resume: bool
    extraction: DocumentExtraction
    text_chars: int
    page_count: int | None
    # Whether the original file is kept, so it can be attached and downloaded.
    has_file: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, document: Document) -> "DocumentView":
        return cls(
            id=document.id,
            title=document.title,
            file_name=document.file_name,
            media_type=document.media_type,
            size_bytes=document.size_bytes,
            is_resume=document.is_resume,
            extraction=DocumentExtraction(document.extraction),
            text_chars=document.text_chars,
            page_count=document.page_count,
            has_file=document.has_file,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    document: DocumentView
    # False when the same file was uploaded before; nothing was read again.
    created: bool


@dataclass(frozen=True, slots=True)
class DocumentDetail:
    document: DocumentView
    text: str


@dataclass(frozen=True, slots=True)
class StoredFile:
    """A document's original file."""

    document: DocumentView
    data: bytes


@dataclass(frozen=True, slots=True)
class DocumentRead:
    document: DocumentView
    text: str
    # Whether the text was cut to fit what the assistant reads at once.
    truncated: bool


@dataclass(frozen=True, slots=True)
class DocumentPassage:
    document_id: uuid.UUID
    document_title: str
    page: int | None
    # The best part of the passage; matches are wrapped in << and >>.
    snippet: str


class DocumentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        usage: UsageService,
        reader: DocumentReader | None,
        max_bytes: int,
        max_stored_bytes: int,
        max_text_chars: int,
        vision_fallback: bool,
        default_timezone: str,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._usage = usage
        self._reader = reader
        self._max_bytes = max_bytes
        self._max_stored_bytes = max_stored_bytes
        self._max_text_chars = max_text_chars
        self._vision_fallback = vision_fallback
        self._default_timezone = default_timezone
        self._clock = clock

    # --- The user's files ------------------------------------------------------------

    async def upload(
        self, principal: Principal, *, file_name: str, media_type: str, data_base64: str
    ) -> DocumentUpload:
        if media_type not in DOCUMENT_TYPES:
            raise InvalidDocumentError("Upload a PDF, a Word document (.docx), or a text file.")
        data = self._decode(data_base64)
        digest = hashlib.sha256(data).hexdigest()
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            known = await repository.by_hash(principal.id, digest)
            stored = await repository.stored_bytes(principal.id)
        if known is not None:
            if not known.has_file:
                kept = await self._keep_file(principal, known.id, data)
                return DocumentUpload(kept, created=False)
            return DocumentUpload(DocumentView.of(known), created=False)
        self._check_room(stored, len(data))

        text = await asyncio.to_thread(read_document_text, data, media_type)
        if media_type == PDF and not has_text_layer(text):
            text = await self._read_scan(principal, file_name, data, text.page_count)
        pages = self._capped(text.pages)
        chunks = passages(pages)
        if not chunks:
            raise InvalidDocumentError("No text could be found in this file.")
        full_text = "\n\n".join(page for page in pages if page)
        now = self._clock()
        try:
            async with transaction(self._session_factory) as session:
                repository = DocumentRepository(session)
                is_resume = (
                    looks_like_resume(file_name, full_text)
                    and await repository.resume(principal.id) is None
                )
                document_id = new_uuid()
                document = await repository.add(
                    Document(
                        id=document_id,
                        user_id=principal.id,
                        title=title_from_file_name(file_name),
                        file_name=file_name[:255],
                        media_type=media_type,
                        size_bytes=len(data),
                        file_sha256=digest,
                        is_resume=is_resume,
                        extraction=text.extraction.value,
                        text_chars=sum(len(chunk.content) for chunk in chunks),
                        page_count=text.page_count,
                        created_at=now,
                        updated_at=now,
                    ),
                    [
                        DocumentChunk(
                            id=new_uuid(),
                            document_id=document_id,
                            ordinal=chunk.ordinal,
                            page=chunk.page,
                            content=chunk.content,
                            created_at=now,
                        )
                        for chunk in chunks
                    ],
                )
                await repository.add_file(
                    document, DocumentFile(document_id=document_id, data=data, created_at=now)
                )
                view = DocumentView.of(document)
        except IntegrityError:
            # The same file arrived twice at once: the other upload stored it.
            async with self._session_factory() as session:
                known = await DocumentRepository(session).by_hash(principal.id, digest)
            if known is None:
                raise
            return DocumentUpload(DocumentView.of(known), created=False)
        return DocumentUpload(view, created=True)

    async def list_documents(self, principal: Principal) -> list[DocumentView]:
        async with self._session_factory() as session:
            documents = await DocumentRepository(session).list_for(principal.id)
        return [DocumentView.of(document) for document in documents]

    async def detail(self, principal: Principal, document_id: uuid.UUID) -> DocumentDetail:
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            document = await _owned(repository, principal.id, document_id)
            chunks = await repository.chunks(document.id)
        return DocumentDetail(DocumentView.of(document), _joined(chunks))

    async def update(
        self,
        principal: Principal,
        document_id: uuid.UUID,
        *,
        title: str | None = None,
        is_resume: bool | None = None,
    ) -> DocumentView:
        """Rename a document, or mark it as (or no longer as) the user's resume. Marking one
        unmarks the previous resume."""
        if title is None and is_resume is None:
            raise InvalidMemoryChangeError("Nothing to change.")
        async with transaction(self._session_factory) as session:
            repository = DocumentRepository(session)
            document = await _owned(repository, principal.id, document_id, for_update=True)
            if title is not None:
                cleaned = clean_title(title, max_chars=TITLE_MAX_CHARS)
                if not cleaned:
                    raise InvalidDocumentError("Enter a title.")
                document.title = cleaned
            if is_resume is not None:
                if is_resume:
                    await repository.unmark_resume(principal.id, except_id=document.id)
                document.is_resume = is_resume
            document.updated_at = self._clock()
            await session.flush()
            return DocumentView.of(document)

    async def stored_file(self, principal: Principal, document_id: uuid.UUID) -> StoredFile:
        """A document's original file, to open or share. Not found when only its text was
        kept."""
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            document = await _owned(repository, principal.id, document_id)
            data = await repository.file_data(document.id) if document.has_file else None
        if data is None:
            raise RecordNotFoundError("Document file", str(document_id))
        return StoredFile(DocumentView.of(document), data)

    async def delete(self, principal: Principal, document_id: uuid.UUID) -> None:
        """Delete a document, its passages, and its file. The assistant can read or attach
        nothing of it after."""
        async with transaction(self._session_factory) as session:
            repository = DocumentRepository(session)
            document = await _owned(repository, principal.id, document_id, for_update=True)
            await repository.delete(document)

    # --- For the assistant -------------------------------------------------------------

    async def for_owner(self, owner_id: uuid.UUID) -> list[DocumentView]:
        """The owner's documents, for the assistant's context: titles only, no text."""
        async with self._session_factory() as session:
            documents = await DocumentRepository(session).list_for(owner_id)
        return [DocumentView.of(document) for document in documents]

    async def read(
        self, owner_id: uuid.UUID, reference: str, *, max_chars: int
    ) -> DocumentRead | None:
        """A document's text, found by ``resume``, by id, or by its title, cut to
        ``max_chars``. None when nothing matches."""
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            document = await self._find(repository, owner_id, reference)
            if document is None:
                return None
            chunks = await repository.chunks(document.id)
        text = _joined(chunks)
        truncated = len(text) > max_chars
        return DocumentRead(DocumentView.of(document), text[:max_chars], truncated)

    async def search(self, owner_id: uuid.UUID, query: str, *, limit: int) -> list[DocumentPassage]:
        """Passages of the owner's documents containing the query's words, best first."""
        terms = lexical_terms(normalize_query(query))
        if not terms:
            return []
        async with self._session_factory() as session:
            rows = await DocumentRepository(session).search(
                owner_id, any_term_tsquery(terms), limit=limit
            )
        return [
            DocumentPassage(
                document_id=document.id,
                document_title=document.title,
                page=chunk.page,
                snippet=snippet,
            )
            for chunk, document, snippet in rows
        ]

    async def attachable(self, owner_id: uuid.UUID, reference: str) -> DocumentView:
        """The document a reference names (``resume``, an id, or a title) when its file is
        kept and can be attached. Raises AttachmentUnavailableError otherwise, saying why."""
        async with self._session_factory() as session:
            document = await self._find(DocumentRepository(session), owner_id, reference)
        if document is None:
            raise AttachmentUnavailableError(
                f"No file in My files matches '{reference.strip()}'. Upload it in Files & links."
            )
        if not document.has_file:
            raise AttachmentUnavailableError(
                f"Only the text of '{document.title}' was kept, so it cannot be attached. "
                "Upload the file again in Files & links to attach it."
            )
        return DocumentView.of(document)

    async def attachment(self, owner_id: uuid.UUID, document_id: uuid.UUID) -> StoredFile:
        """A document's file, to attach. Raises AttachmentUnavailableError when the
        document was deleted since it was chosen."""
        async with self._session_factory() as session:
            repository = DocumentRepository(session)
            document = await repository.get(owner_id, document_id)
            data = (
                await repository.file_data(document.id)
                if document is not None and document.has_file
                else None
            )
        if document is None or data is None:
            raise AttachmentUnavailableError(
                "A file chosen to attach was deleted. Ask for a new draft to attach another."
            )
        return StoredFile(DocumentView.of(document), data)

    # --- Helpers ---------------------------------------------------------------------

    async def _keep_file(
        self, principal: Principal, document_id: uuid.UUID, data: bytes
    ) -> DocumentView:
        """Keep the file of a document of which only the text was kept (uploaded before
        ADR-050), now that the same file arrived again."""
        async with transaction(self._session_factory) as session:
            repository = DocumentRepository(session)
            document = await _owned(repository, principal.id, document_id, for_update=True)
            if not document.has_file:
                self._check_room(await repository.stored_bytes(principal.id), len(data))
                await repository.add_file(
                    document,
                    DocumentFile(document_id=document.id, data=data, created_at=self._clock()),
                )
            return DocumentView.of(document)

    def _check_room(self, stored: int, size: int) -> None:
        if stored + size > self._max_stored_bytes:
            raise DocumentStorageFullError(
                f"Your files take {stored / _MEGABYTE:.1f} MB of "
                f"{self._max_stored_bytes / _MEGABYTE:.0f} MB. Delete a file to make room."
            )

    async def _find(
        self, repository: DocumentRepository, owner_id: uuid.UUID, reference: str
    ) -> Document | None:
        wanted = reference.strip()
        if wanted.lower() in (RESUME, "cv", "my resume"):
            resume = await repository.resume(owner_id)
            if resume is not None:
                return resume
        try:
            by_id = await repository.get(owner_id, uuid.UUID(wanted))
        except ValueError:
            by_id = None
        if by_id is not None:
            return by_id
        lowered = wanted.lower()
        documents = await repository.list_for(owner_id)
        for document in documents:
            if document.title.lower() == lowered or document.file_name.lower() == lowered:
                return document
        for document in documents:
            if lowered and (
                lowered in document.title.lower() or lowered in document.file_name.lower()
            ):
                return document
        return None

    async def _read_scan(
        self, principal: Principal, file_name: str, data: bytes, page_count: int | None
    ) -> DocumentText:
        """A scanned PDF, read by the model when the operator allows it."""
        if not self._vision_fallback or self._reader is None:
            raise InvalidDocumentError(
                "This PDF has no text to read; it looks like a scan. Upload the original PDF "
                "or a Word document instead."
            )
        async with transaction(self._session_factory) as session:
            zone = user_timezone(
                await UserRepository(session).get(principal.id), self._default_timezone
            )
            # A model call made for the user: one of today's prompts.
            await self._usage.count_chat_message(session, principal.id, timezone_name=zone.key)
        text = await self._reader.read(
            Attachment(name=file_name, media_type=PDF, data=data),
            context=LlmCallContext(origin=LlmCallOrigin.CAPTURE, user_id=principal.id),
        )
        return DocumentText((clean_text(text),), DocumentExtraction.VISION, page_count)

    def _capped(self, pages: tuple[str, ...]) -> tuple[str, ...]:
        """The pages, cut once their text reaches the configured maximum."""
        kept: list[str] = []
        room = self._max_text_chars
        for page in pages:
            if room <= 0:
                break
            kept.append(page[:room])
            room -= len(page)
        return tuple(kept)

    def _decode(self, data_base64: str) -> bytes:
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidDocumentError("The file could not be read.") from error
        if not data:
            raise InvalidDocumentError("The file is empty.")
        if len(data) > self._max_bytes:
            raise InvalidDocumentError(
                f"Files can be at most {self._max_bytes // (1024 * 1024)} MB."
            )
        return data


async def _owned(
    repository: DocumentRepository,
    owner_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Document:
    document = await repository.get(owner_id, document_id, for_update=for_update)
    if document is None:
        raise RecordNotFoundError("Document", str(document_id))
    return document


def _joined(chunks: list[DocumentChunk]) -> str:
    return "\n\n".join(chunk.content for chunk in chunks)
