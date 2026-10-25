"""Photos and PDFs the user gives to remember (ADR-047).

The file is read into text by the model (one call, counted against the user's daily
prompts like a chat message), and that text is stored as the user's evidence, as one unit
for the memory pipeline, which extracts memories from it in the background. The file
itself is not kept. The same file twice is recognized by its hash and read once.
"""

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.session import transaction
from app.domain.attachments import ATTACHMENT_TYPES
from app.domain.enums import LlmCallOrigin, MessageSource
from app.domain.errors import (
    IntegrationNotConfiguredError,
    InvalidAttachmentError,
)
from app.domain.principal import Principal
from app.integrations.assistant.base import Attachment
from app.integrations.document_reader import DocumentReader
from app.integrations.llm_calls import LlmCallContext
from app.repositories.message_repository import MessageRepository
from app.repositories.user_repository import UserRepository
from app.schemas.raw_message import RawMessageCreate
from app.services.background import BackgroundWork
from app.services.ingestion import IngestionService
from app.services.life_state import user_timezone
from app.services.processing.extraction import UNIT_TIMEZONE_KEY
from app.services.processing.runner import PipelineRunner
from app.services.usage import UsageService

logger = structlog.get_logger(__name__)

# The ingestion limit on one message's text, with room for the header.
_MAX_TEXT_CHARS: Final = 19_000


@dataclass(frozen=True, slots=True)
class FileCaptureResult:
    raw_message_id: uuid.UUID
    processing_run_id: uuid.UUID
    text: str
    # False when the same file was given before; nothing was read again.
    created: bool


class FileCapture:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reader: DocumentReader | None,
        *,
        ingestion: IngestionService,
        runner: PipelineRunner,
        background: BackgroundWork,
        usage: UsageService,
        max_bytes: int,
        default_timezone: str,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._reader = reader
        self._ingestion = ingestion
        self._runner = runner
        self._background = background
        self._usage = usage
        self._max_bytes = max_bytes
        self._default_timezone = default_timezone
        self._clock = clock

    @property
    def available(self) -> bool:
        return self._reader is not None

    async def capture(
        self, principal: Principal, *, file_name: str, media_type: str, data_base64: str
    ) -> FileCaptureResult:
        if self._reader is None:
            raise IntegrationNotConfiguredError("Reading files", "ANTHROPIC_API_KEY")
        if media_type not in ATTACHMENT_TYPES:
            raise InvalidAttachmentError("Choose a photo (JPEG, PNG, GIF, WebP) or a PDF.")
        data = self._decode(data_base64)
        source_id = f"file:{principal.id}:{hashlib.sha256(data).hexdigest()}"

        async with transaction(self._session_factory) as session:
            known = await MessageRepository(session).get_by_source_identity(
                MessageSource.FILE_UPLOAD.value, source_id
            )
            zone = user_timezone(
                await UserRepository(session).get(principal.id), self._default_timezone
            )
            if known is None:
                # A model call made for the user: one of today's prompts.
                await self._usage.count_chat_message(session, principal.id, timezone_name=zone.key)
        if known is not None and known.owner_id == principal.id:
            [unit] = await self._ingestion.ingest(
                [
                    [
                        _message(
                            file_name, media_type, known.content, source_id, zone.key, self._clock
                        )
                    ]
                ],
                owner_id=principal.id,
            )
            return FileCaptureResult(
                raw_message_id=known.id,
                processing_run_id=unit.run.id,
                text=known.content,
                created=False,
            )

        text = await self._reader.read(
            Attachment(name=file_name, media_type=media_type, data=data),
            context=LlmCallContext(origin=LlmCallOrigin.CAPTURE, user_id=principal.id),
        )
        content = f"From the file {file_name}:\n\n{text}"[:_MAX_TEXT_CHARS]
        [unit] = await self._ingestion.ingest(
            [[_message(file_name, media_type, content, source_id, zone.key, self._clock)]],
            owner_id=principal.id,
        )
        if unit.run.created and self._runner.can_process:
            self._background.spawn(self._process(unit.run.id), name=f"file-capture-{unit.run.id}")
        return FileCaptureResult(
            raw_message_id=unit.messages[0].id,
            processing_run_id=unit.run.id,
            text=content,
            created=True,
        )

    async def _process(self, run_id: uuid.UUID) -> None:
        try:
            await self._runner.process_runs([run_id])
        except Exception:
            # The pipeline loop retries the run; the evidence is stored either way.
            logger.exception("file_capture_processing_failed", run_id=str(run_id))

    def _decode(self, data_base64: str) -> bytes:
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidAttachmentError("The file could not be read.") from error
        if not data:
            raise InvalidAttachmentError("The file is empty.")
        if len(data) > self._max_bytes:
            raise InvalidAttachmentError(
                f"Files can be at most {self._max_bytes // (1024 * 1024)} MB."
            )
        return data


def _message(
    file_name: str,
    media_type: str,
    content: str,
    source_id: str,
    timezone_name: str,
    clock: Clock,
) -> RawMessageCreate:
    return RawMessageCreate(
        source=MessageSource.FILE_UPLOAD,
        content=content,
        source_message_id=source_id,
        source_created_at=clock(),
        metadata={
            "file_name": file_name[:255],
            "media_type": media_type,
            UNIT_TIMEZONE_KEY: timezone_name,
        },
    )
