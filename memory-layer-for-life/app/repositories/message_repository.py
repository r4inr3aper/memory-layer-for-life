import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.base import new_uuid
from app.models.raw_message import RawMessage
from app.repositories.base import BaseRepository

_SOURCE_IDENTITY_CONSTRAINT = "uq_raw_messages_source_source_message_id"


@dataclass(frozen=True, slots=True)
class NewRawMessage:
    """Values of a raw message that is about to be stored."""

    source: str
    content: str
    content_sha256: str
    source_message_id: str | None = None
    source_created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    owner_id: uuid.UUID | None = None


class MessageRepository(BaseRepository):
    """Persistence of raw messages. There is no update or delete: evidence is immutable."""

    async def get_by_source_identity(
        self, source: str, source_message_id: str
    ) -> RawMessage | None:
        result = await self._session.scalars(
            select(RawMessage).where(
                RawMessage.source == source,
                RawMessage.source_message_id == source_message_id,
            )
        )
        return result.first()

    async def add(self, new: NewRawMessage, *, now: datetime) -> RawMessage:
        """Insert a message. Every call creates a row, whatever the content."""
        message = RawMessage(
            id=new_uuid(),
            source=new.source,
            source_message_id=new.source_message_id,
            content=new.content,
            content_sha256=new.content_sha256,
            source_created_at=new.source_created_at,
            ingested_at=now,
            metadata_=dict(new.metadata),
            owner_id=new.owner_id,
            created_at=now,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def add_if_absent(self, new: NewRawMessage, *, now: datetime) -> tuple[RawMessage, bool]:
        """Insert a message unless its source identity is already stored.

        Returns the stored message and whether this call created it. An existing row is
        returned untouched, whatever its content: the caller decides what a content
        mismatch means. The statement relies on the unique constraint, so two concurrent
        deliveries of the same identity cannot both insert.
        """
        if new.source_message_id is None:
            raise ValueError("add_if_absent needs a source_message_id; use add() otherwise.")

        statement = (
            insert(RawMessage)
            .values(
                id=new_uuid(),
                source=new.source,
                source_message_id=new.source_message_id,
                content=new.content,
                content_sha256=new.content_sha256,
                source_created_at=new.source_created_at,
                ingested_at=now,
                metadata_=dict(new.metadata),
                owner_id=new.owner_id,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint=_SOURCE_IDENTITY_CONSTRAINT)
            .returning(RawMessage.id)
        )
        inserted_id = (await self._session.execute(statement)).scalar_one_or_none()
        if inserted_id is not None:
            stored = await self._session.get(RawMessage, inserted_id)
            if stored is None:  # pragma: no cover - the row was inserted in this transaction
                raise RuntimeError("Inserted raw message could not be loaded.")
            return stored, True

        existing = await self.get_by_source_identity(new.source, new.source_message_id)
        if existing is None:  # pragma: no cover - guarded by the unique constraint
            raise RuntimeError("Raw message conflict reported, but no stored row was found.")
        return existing, False
