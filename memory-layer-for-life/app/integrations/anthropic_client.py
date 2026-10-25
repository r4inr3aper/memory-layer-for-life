import structlog
from anthropic import AsyncAnthropic

from app.core.config import Settings

logger = structlog.get_logger(__name__)


class AnthropicClientManager:
    """Manages the lifecycle of a single AsyncAnthropic client per application process."""

    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None
        self._model: str = "claude-sonnet-5-5"

    def initialize(self, settings: Settings) -> None:
        """Initialize the Anthropic client. Does NOT make any API calls."""
        if settings.ANTHROPIC_API_KEY is None:
            logger.info("anthropic_client_skipped", reason="No API key configured")
            return

        self._client = AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=float(settings.ANTHROPIC_TIMEOUT),
            max_retries=settings.ANTHROPIC_MAX_RETRIES,
        )
        self._model = settings.ANTHROPIC_MODEL
        logger.info("anthropic_client_initialized", model=self._model)

    @property
    def client(self) -> AsyncAnthropic | None:
        return self._client

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            logger.info("anthropic_client_closed")
            self._client = None
