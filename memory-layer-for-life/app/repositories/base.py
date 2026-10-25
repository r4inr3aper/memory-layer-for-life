from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Base repository providing database session access.

    Repositories run queries and flush, so that ids and constraint violations surface
    where they are caused. They never commit or roll back: the transaction belongs to
    the service or request that created the session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
