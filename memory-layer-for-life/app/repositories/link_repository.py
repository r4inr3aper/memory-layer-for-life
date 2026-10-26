import uuid

from sqlalchemy import delete, select, update

from app.domain.enums import LinkKind
from app.models.saved_link import SavedLink
from app.repositories.base import BaseRepository


class LinkRepository(BaseRepository):
    """Persistence of the links a user saved (ADR-050). Every lookup is scoped to the
    owner, so another user's link reads as missing."""

    async def add(self, link: SavedLink) -> SavedLink:
        self._session.add(link)
        await self._session.flush()
        return link

    async def get(
        self, user_id: uuid.UUID, link_id: uuid.UUID, *, for_update: bool = False
    ) -> SavedLink | None:
        statement = select(SavedLink).where(SavedLink.id == link_id, SavedLink.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        result: SavedLink | None = await self._session.scalar(statement)
        return result

    async def by_url(self, user_id: uuid.UUID, url: str) -> SavedLink | None:
        result: SavedLink | None = await self._session.scalar(
            select(SavedLink).where(SavedLink.user_id == user_id, SavedLink.url == url)
        )
        return result

    async def list_for(self, user_id: uuid.UUID) -> list[SavedLink]:
        """The user's links, the resume first, then most recently changed."""
        rows = await self._session.scalars(
            select(SavedLink)
            .where(SavedLink.user_id == user_id)
            .order_by(
                (SavedLink.kind == LinkKind.RESUME.value).desc(),
                SavedLink.updated_at.desc(),
                SavedLink.id,
            )
        )
        return list(rows)

    async def unmark_resume(self, user_id: uuid.UUID, *, except_id: uuid.UUID | None) -> None:
        """No link of the user is their resume any more, except ``except_id``: the previous
        resume link becomes a plain link."""
        conditions = [SavedLink.user_id == user_id, SavedLink.kind == LinkKind.RESUME.value]
        if except_id is not None:
            conditions.append(SavedLink.id != except_id)
        await self._session.execute(
            update(SavedLink)
            .where(*conditions)
            .values(kind=LinkKind.OTHER.value)
            .execution_options(synchronize_session=False)
        )

    async def delete(self, link: SavedLink) -> None:
        await self._session.execute(delete(SavedLink).where(SavedLink.id == link.id))
