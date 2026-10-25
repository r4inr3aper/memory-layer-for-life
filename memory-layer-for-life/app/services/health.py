import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_database(self) -> tuple[bool, str]:
        """Check database connectivity. Returns (is_healthy, detail)."""
        try:
            await self._session.execute(text("SELECT 1"))
            return True, "connected"
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False, f"connection failed: {type(e).__name__}"
