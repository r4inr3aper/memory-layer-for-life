"""Persistence of chat imports, and how far the pipeline got with one."""

import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import undefer

from app.domain.enums import MessageSource
from app.models.chat_import import ChatImport
from app.models.extraction_result import ExtractionResult
from app.models.memory import Memory
from app.models.processing_run import ProcessingRun
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository


def _messages_of(user_id: uuid.UUID, import_id: uuid.UUID) -> list[ColumnElement[bool]]:
    return [
        RawMessage.owner_id == user_id,
        RawMessage.source == MessageSource.WHATSAPP_IMPORT.value,
        RawMessage.metadata_["import_id"].astext == str(import_id),
    ]


class ImportRepository(BaseRepository):
    async def add(self, chat_import: ChatImport) -> ChatImport:
        self._session.add(chat_import)
        await self._session.flush()
        return chat_import

    async def get_owned(
        self,
        user_id: uuid.UUID,
        import_id: uuid.UUID,
        *,
        for_update: bool = False,
        with_content: bool = False,
    ) -> ChatImport | None:
        statement = select(ChatImport).where(
            ChatImport.id == import_id, ChatImport.user_id == user_id
        )
        if with_content:
            statement = statement.options(undefer(ChatImport.content))
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.scalars(statement.execution_options(populate_existing=True))
        return result.first()

    async def by_file(self, user_id: uuid.UUID, file_sha256: str) -> ChatImport | None:
        result = await self._session.scalars(
            select(ChatImport).where(
                ChatImport.user_id == user_id, ChatImport.file_sha256 == file_sha256
            )
        )
        return result.first()

    async def list_for_user(self, user_id: uuid.UUID) -> list[ChatImport]:
        rows = await self._session.scalars(
            select(ChatImport)
            .where(ChatImport.user_id == user_id)
            .order_by(ChatImport.created_at.desc(), ChatImport.id.desc())
        )
        return list(rows)

    async def run_counts(self, user_id: uuid.UUID, import_id: uuid.UUID) -> dict[str, int]:
        """The import's pipeline runs by status. A run is keyed by its unit's first message."""
        rows = await self._session.execute(
            select(ProcessingRun.status, func.count())
            .join(RawMessage, RawMessage.id == ProcessingRun.raw_message_id)
            .where(*_messages_of(user_id, import_id))
            .group_by(ProcessingRun.status)
        )
        return {status: int(count) for status, count in rows}

    async def memory_count(self, user_id: uuid.UUID, import_id: uuid.UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Memory)
            .join(ExtractionResult, ExtractionResult.id == Memory.origin_extraction_result_id)
            .join(ProcessingRun, ProcessingRun.id == ExtractionResult.processing_run_id)
            .join(RawMessage, RawMessage.id == ProcessingRun.raw_message_id)
            .where(*_messages_of(user_id, import_id))
        )
        return int(total or 0)
