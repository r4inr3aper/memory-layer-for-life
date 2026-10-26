"""Links the user saves for the assistant to share for them (ADR-050), such as their
resume on Google Drive, their portfolio, or their LinkedIn profile.

* A link is kept by its address, normalized (``app.domain.links``); the same address
  twice is the same link. A title and a kind are guessed when the user gives none.
* At most one link is the resume: marking one makes the previous resume link a plain
  link, as marking a document does.
* The assistant sees every link, with its address, in its context, and shares one when
  it helps: the resume link in a job application email. Nothing is fetched from a link.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.db.base import new_uuid
from app.db.session import transaction
from app.domain.enums import LinkKind
from app.domain.errors import InvalidLinkError, RecordNotFoundError
from app.domain.links import clean_link_title, default_title, guess_kind, normalize_url
from app.domain.principal import Principal
from app.models.saved_link import SavedLink
from app.repositories.link_repository import LinkRepository


@dataclass(frozen=True, slots=True)
class LinkView:
    id: uuid.UUID
    url: str
    title: str
    kind: LinkKind
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, link: SavedLink) -> "LinkView":
        return cls(
            id=link.id,
            url=link.url,
            title=link.title,
            kind=LinkKind(link.kind),
            created_at=link.created_at,
            updated_at=link.updated_at,
        )


@dataclass(frozen=True, slots=True)
class LinkSave:
    link: LinkView
    # False when the address was saved before; its title and kind were updated.
    created: bool


class LinkService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, clock: Clock = utc_now
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def list_links(self, principal: Principal) -> list[LinkView]:
        return await self.for_owner(principal.id)

    async def for_owner(self, owner_id: uuid.UUID) -> list[LinkView]:
        """The owner's links, the resume first: for the app and the assistant's context."""
        async with self._session_factory() as session:
            links = await LinkRepository(session).list_for(owner_id)
        return [LinkView.of(link) for link in links]

    async def save(
        self,
        principal: Principal,
        *,
        url: str,
        title: str | None = None,
        kind: LinkKind | None = None,
    ) -> LinkSave:
        """Save a link. An address saved before keeps its row and takes the new title and
        kind, when given."""
        address = normalize_url(url)
        chosen_title = clean_link_title(title) if title is not None and title.strip() else None
        chosen_kind = kind or guess_kind(address, chosen_title)
        now = self._clock()
        try:
            async with transaction(self._session_factory) as session:
                repository = LinkRepository(session)
                known = await repository.by_url(principal.id, address)
                if chosen_kind is LinkKind.RESUME:
                    await repository.unmark_resume(
                        principal.id, except_id=known.id if known is not None else None
                    )
                if known is not None:
                    if chosen_title is not None:
                        known.title = chosen_title
                    if kind is not None or chosen_kind is LinkKind.RESUME:
                        known.kind = chosen_kind.value
                    known.updated_at = now
                    await session.flush()
                    return LinkSave(LinkView.of(known), created=False)
                link = await repository.add(
                    SavedLink(
                        id=new_uuid(),
                        user_id=principal.id,
                        url=address,
                        title=chosen_title or default_title(address, chosen_kind),
                        kind=chosen_kind.value,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return LinkSave(LinkView.of(link), created=True)
        except IntegrityError as error:
            # The same address saved twice at once: the other request stored it.
            async with self._session_factory() as session:
                known = await LinkRepository(session).by_url(principal.id, address)
            if known is None:
                raise InvalidLinkError("The link could not be saved. Try again.") from error
            return LinkSave(LinkView.of(known), created=False)

    async def update(
        self,
        principal: Principal,
        link_id: uuid.UUID,
        *,
        url: str | None = None,
        title: str | None = None,
        kind: LinkKind | None = None,
    ) -> LinkView:
        """Change a link's address, title, or kind. Marking it the resume makes the previous
        resume link a plain link."""
        if url is None and title is None and kind is None:
            raise InvalidLinkError("Nothing to change.")
        address = normalize_url(url) if url is not None else None
        try:
            async with transaction(self._session_factory) as session:
                repository = LinkRepository(session)
                link = await _owned(repository, principal.id, link_id)
                if address is not None and address != link.url:
                    if await repository.by_url(principal.id, address) is not None:
                        raise InvalidLinkError("That link is already saved.")
                    link.url = address
                if title is not None:
                    link.title = clean_link_title(title)
                if kind is not None:
                    if kind is LinkKind.RESUME:
                        await repository.unmark_resume(principal.id, except_id=link.id)
                    link.kind = kind.value
                link.updated_at = self._clock()
                await session.flush()
                return LinkView.of(link)
        except IntegrityError as error:
            raise InvalidLinkError("That link is already saved.") from error

    async def delete(self, principal: Principal, link_id: uuid.UUID) -> None:
        async with transaction(self._session_factory) as session:
            repository = LinkRepository(session)
            await repository.delete(await _owned(repository, principal.id, link_id))


async def _owned(repository: LinkRepository, owner_id: uuid.UUID, link_id: uuid.UUID) -> SavedLink:
    link = await repository.get(owner_id, link_id, for_update=True)
    if link is None:
        raise RecordNotFoundError("Link", str(link_id))
    return link
