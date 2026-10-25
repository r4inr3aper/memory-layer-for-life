import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import Settings
from app.integrations.anthropic_client import AnthropicClientManager

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/db"


def make_settings(**overrides: Any) -> Settings:
    values = {"DATABASE_URL": DATABASE_URL, **overrides}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_initialize_without_api_key() -> None:
    manager = AnthropicClientManager()

    manager.initialize(make_settings(ANTHROPIC_API_KEY=None))

    assert manager.client is None
    assert manager.is_configured is False


@patch("app.integrations.anthropic_client.AsyncAnthropic")
def test_initialize_with_api_key(mock_async_anthropic: MagicMock) -> None:
    settings = make_settings(
        ANTHROPIC_API_KEY="test-key", ANTHROPIC_TIMEOUT=45, ANTHROPIC_MAX_RETRIES=1
    )
    manager = AnthropicClientManager()

    manager.initialize(settings)

    assert manager.client is not None
    assert manager.is_configured is True
    mock_async_anthropic.assert_called_once_with(api_key="test-key", timeout=45.0, max_retries=1)


def test_initializing_makes_no_request() -> None:
    """Building the client must not touch the network: startup never calls a provider."""
    with patch("app.integrations.anthropic_client.AsyncAnthropic") as mock_async_anthropic:
        AnthropicClientManager().initialize(make_settings(ANTHROPIC_API_KEY="test-key"))

    client = mock_async_anthropic.return_value
    assert client.method_calls == []


def test_model_name_from_settings() -> None:
    settings = make_settings(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-test-model")
    manager = AnthropicClientManager()

    with patch("app.integrations.anthropic_client.AsyncAnthropic"):
        manager.initialize(settings)

    assert manager.model == "claude-test-model"


async def test_close_without_client() -> None:
    await AnthropicClientManager().close()  # must not raise


async def test_close_with_client() -> None:
    manager = AnthropicClientManager()
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    manager._client = mock_client

    await manager.close()

    mock_client.close.assert_called_once()
    assert manager.client is None


def test_client_not_created_at_import() -> None:
    sys.modules.pop("app.integrations.anthropic_client", None)
    from app.integrations.anthropic_client import AnthropicClientManager as Reloaded

    assert Reloaded().client is None
