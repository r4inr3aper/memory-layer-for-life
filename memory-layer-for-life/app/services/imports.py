"""Chat exports brought in to become memories (ADR-047).

Two steps, so nothing costs anything until the user has seen what it will be:

1. ``preview``: the file is read and parsed (``app.domain.whatsapp``), and its text kept
   with the participants, how many messages and conversations each has, and the price
   of one extraction. The same file twice gives the same import.
2. ``start``: the user says which participant they are, from when, and at most how many
   conversations (the most recent are kept). Each conversation is ingested as one unit of
   the user's evidence and queued; the pipeline loop extracts them in the background,
   retrying failures. The text is dropped from the import: the raw messages hold it.

Every extraction is a model call, so the user decides the number, and the response says
what one costs.
"""

import base64
import binascii
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import ImportStatus, MessageSource, ProcessingStatus
from app.domain.errors import InvalidImportError, RecordNotFoundError
from app.domain.model_catalog import estimate_cost_usd
from app.domain.principal import Principal
from app.domain.whatsapp import (
    ChatMessage,
    ParsedChat,
    conversations,
    line_for,
    parse_export,
    read_export,
)
from app.models.chat_import import ChatImport
from app.repositories.import_repository import ImportRepository
from app.repositories.user_repository import UserRepository
from app.schemas.raw_message import RawMessageCreate
from app.services.ingestion import IngestionService
from app.services.life_state import user_timezone
from app.services.processing.extraction import UNIT_TIMEZONE_KEY

MAX_FILE_BYTES: Final = 10 * 1024 * 1024
MAX_CONVERSATIONS: Final = 300
# Units per ingestion call; within the ingestion service's batch limit.
_BATCH: Final = 50
# What one extraction of a conversation typically reads and writes, for the estimate.
_TYPICAL_INPUT_TOKENS: Final = 4_000
_TYPICAL_OUTPUT_TOKENS: Final = 700


@dataclass(frozen=True, slots=True)
class _Typical:
    input_tokens: int = _TYPICAL_INPUT_TOKENS
    output_tokens: int = _TYPICAL_OUTPUT_TOKENS
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Participant:
    name: str
    messages: int
    # Conversations this person took part in.
    conversations: int


@dataclass(frozen=True, slots=True)
class ImportProgress:
    done: int
    failed: int
    waiting: int
    memories: int


@dataclass(frozen=True, slots=True)
class ImportView:
    id: uuid.UUID
    file_name: str
    status: ImportStatus
    participants: tuple[Participant, ...]
    message_count: int
    all_conversations: int
    first_message_at: datetime | None
    last_message_at: datetime | None
    owner_name: str | None
    since: date | None
    unit_count: int | None
    # One extraction's estimated cost, in the app's currency; None when unknown.
    cost_per_conversation: Decimal | None
    currency: str
    progress: ImportProgress | None
    created_at: datetime


class ImportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ingestion: IngestionService,
        *,
        default_timezone: str,
        extraction_model: str,
        currency: str,
        currency_per_usd: Decimal,
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._ingestion = ingestion
        self._default_timezone = default_timezone
        self._model = extraction_model
        self._currency = currency
        self._per_usd = currency_per_usd
        self._clock = clock

    async def preview(self, principal: Principal, file_name: str, data_base64: str) -> ImportView:
        data = _decode(data_base64)
        sha256 = hashlib.sha256(data).hexdigest()
        text = read_export(file_name, data)
        chat = parse_export(text)
        now = self._clock()
        async with transaction(self._session_factory) as session:
            imports = ImportRepository(session)
            known = await imports.by_file(principal.id, sha256)
            if known is not None:
                if known.status == ImportStatus.QUEUED.value:
                    raise InvalidImportError("You already imported this chat.")
                return await self._view(session, principal, known)
            zone = await self._zone(session, principal)
            chat_import = await imports.add(
                ChatImport(
                    id=new_uuid(),
                    user_id=principal.id,
                    source="whatsapp",
                    file_name=file_name[:255],
                    file_sha256=sha256,
                    status=ImportStatus.PREVIEWED.value,
                    participants=[
                        [participant.name, participant.messages, participant.conversations]
                        for participant in _participants(chat)
                    ],
                    message_count=len(chat.messages),
                    conversation_count=len(conversations(chat.messages, me="", only_mine=False)),
                    first_message_at=chat.messages[0].sent_at.replace(tzinfo=zone),
                    last_message_at=chat.messages[-1].sent_at.replace(tzinfo=zone),
                    content=text,
                    created_at=now,
                    updated_at=now,
                )
            )
            return await self._view(session, principal, chat_import)

    async def start(
        self,
        principal: Principal,
        import_id: uuid.UUID,
        *,
        me: str,
        since: date | None,
        only_mine: bool,
        max_conversations: int,
    ) -> ImportView:
        if not 1 <= max_conversations <= MAX_CONVERSATIONS:
            raise InvalidImportError(f"Import 1 to {MAX_CONVERSATIONS} conversations at a time.")
        now = self._clock()
        async with transaction(self._session_factory) as session:
            imports = ImportRepository(session)
            chat_import = await imports.get_owned(
                principal.id, import_id, for_update=True, with_content=True
            )
            if chat_import is None:
                raise RecordNotFoundError("Import", str(import_id))
            if chat_import.status != ImportStatus.PREVIEWED.value or chat_import.content is None:
                raise InvalidImportError("This import has already started.")
            names = {row[0] for row in chat_import.participants}
            if me not in names:
                raise InvalidImportError("Choose which person in the chat you are.")
            chat = parse_export(chat_import.content)
            units = conversations(chat.messages, me=me, since=since, only_mine=only_mine)
            if not units:
                raise InvalidImportError("Nothing to import with these choices.")
            # The most recent conversations matter most.
            units = units[-max_conversations:]
            zone = await self._zone(session, principal)
            batches = _raw_units(chat_import.id, units, me=me, zone=zone)
        # Ingestion is idempotent per message (``source_message_id``), so an import that
        # fails half-way stays previewed and starting it again completes it.
        for first in range(0, len(batches), _BATCH):
            await self._ingestion.ingest(batches[first : first + _BATCH], owner_id=principal.id)
        async with transaction(self._session_factory) as session:
            chat_import = await ImportRepository(session).get_owned(
                principal.id, import_id, for_update=True
            )
            if chat_import is not None and chat_import.status == ImportStatus.PREVIEWED.value:
                chat_import.owner_name = me
                chat_import.since = since
                chat_import.unit_count = len(units)
                chat_import.status = ImportStatus.QUEUED.value
                chat_import.content = None
                chat_import.updated_at = now
        return await self.get(principal, import_id)

    async def list_imports(self, principal: Principal) -> list[ImportView]:
        async with self._session_factory() as session:
            rows = await ImportRepository(session).list_for_user(principal.id)
            return [await self._view(session, principal, row) for row in rows]

    async def get(self, principal: Principal, import_id: uuid.UUID) -> ImportView:
        async with self._session_factory() as session:
            chat_import = await ImportRepository(session).get_owned(principal.id, import_id)
            if chat_import is None:
                raise RecordNotFoundError("Import", str(import_id))
            return await self._view(session, principal, chat_import)

    async def _zone(self, session: AsyncSession, principal: Principal) -> ZoneInfo:
        return user_timezone(
            await UserRepository(session).get(principal.id), self._default_timezone
        )

    async def _view(
        self, session: AsyncSession, principal: Principal, chat_import: ChatImport
    ) -> ImportView:
        progress = None
        if chat_import.status == ImportStatus.QUEUED.value:
            imports = ImportRepository(session)
            counts = await imports.run_counts(principal.id, chat_import.id)
            done = counts.get(ProcessingStatus.SUCCEEDED.value, 0) + counts.get(
                ProcessingStatus.NEEDS_REVIEW.value, 0
            )
            failed = counts.get(ProcessingStatus.FAILED.value, 0)
            progress = ImportProgress(
                done=done,
                failed=failed,
                waiting=sum(counts.values()) - done - failed,
                memories=await imports.memory_count(principal.id, chat_import.id),
            )
        participants = tuple(
            Participant(name=str(row[0]), messages=int(row[1]), conversations=int(row[2]))
            for row in chat_import.participants
        )
        usd = estimate_cost_usd(self._model, _Typical(), aggregate=True)
        return ImportView(
            id=chat_import.id,
            file_name=chat_import.file_name,
            status=ImportStatus(chat_import.status),
            participants=participants,
            message_count=chat_import.message_count,
            all_conversations=chat_import.conversation_count,
            first_message_at=chat_import.first_message_at,
            last_message_at=chat_import.last_message_at,
            owner_name=chat_import.owner_name,
            since=chat_import.since,
            unit_count=chat_import.unit_count,
            cost_per_conversation=(
                (usd * self._per_usd).quantize(Decimal("0.0001")) if usd is not None else None
            ),
            currency=self._currency,
            progress=progress,
            created_at=chat_import.created_at,
        )


def _decode(data_base64: str) -> bytes:
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidImportError("The file could not be read.") from error
    if not data:
        raise InvalidImportError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise InvalidImportError("The file is too large; export the chat without media.")
    return data


def _participants(chat: ParsedChat) -> list[Participant]:
    return [
        Participant(
            name=name,
            messages=count,
            conversations=len(conversations(chat.messages, me=name)),
        )
        for name, count in chat.participants
    ]


def _raw_units(
    import_id: uuid.UUID, units: Sequence[Sequence[ChatMessage]], *, me: str, zone: ZoneInfo
) -> list[list[RawMessageCreate]]:
    batches: list[list[RawMessageCreate]] = []
    index = 0
    for unit in units:
        batch: list[RawMessageCreate] = []
        for message in unit:
            batch.append(
                RawMessageCreate(
                    source=MessageSource.WHATSAPP_IMPORT,
                    content=line_for(message, me=me),
                    source_message_id=f"{import_id}:{index}",
                    source_created_at=message.sent_at.replace(tzinfo=zone),
                    metadata={
                        "import_id": str(import_id),
                        "sender": message.sender,
                        "from_me": message.sender == me,
                        UNIT_TIMEZONE_KEY: zone.key,
                    },
                )
            )
            index += 1
        batches.append(batch)
    return batches
