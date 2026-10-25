import uuid

from sqlalchemy import func, select

from app.models.playground_run import PlaygroundRun
from app.repositories.base import BaseRepository


class PlaygroundRepository(BaseRepository):
    """Persistence of single test calls."""

    async def add(self, run: PlaygroundRun) -> PlaygroundRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def get(self, run_id: uuid.UUID) -> PlaygroundRun | None:
        return await self._session.get(PlaygroundRun, run_id)

    async def list_runs(self, *, limit: int, offset: int) -> tuple[list[PlaygroundRun], int]:
        """Page through test calls, newest first. Returns the page and the total count."""
        total = await self._session.scalar(select(func.count()).select_from(PlaygroundRun))
        rows = await self._session.scalars(
            select(PlaygroundRun)
            .order_by(PlaygroundRun.created_at.desc(), PlaygroundRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)
