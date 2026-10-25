"""Shared test configuration.

The environment is fixed here, before any application module is imported:

* The database is always the dedicated test database. ``DATABASE_URL`` from a
  developer's ``.env`` is never used, so tests cannot touch real data.
* The Anthropic key is blanked. No test can reach the real API, even when the
  developer's ``.env`` contains a working key.
* Supabase, Composio, Browserbase, Expo push, and Voyage AI are blanked for the same
  reason, and the scheduler and index loops are off. Tests that need them inject doubles
  into ``build_container``.
"""

import os

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://brain:brain_dev_password@localhost:5432/second_brain_test"
)

os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
os.environ["ENVIRONMENT"] = "testing"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["DEFAULT_TIMEZONE"] = "UTC"
for _name in (
    "SUPABASE_URL",
    "SUPABASE_JWKS_URL",
    "SUPABASE_SECRET_KEY",
    "COMPOSIO_API_KEY",
    "BROWSERBASE_API_KEY",
    "EXPO_PUSH_ACCESS_TOKEN",
    "VOYAGE_API_KEY",
    "RETRIEVAL_RERANK_MODEL",
):
    os.environ[_name] = ""
os.environ["SCHEDULER_ENABLED"] = "false"
# Chat capture runs the memory pipeline in the background; tests that cover it turn it on.
os.environ["MEMORY_CAPTURE_ENABLED"] = "false"
# No embedding provider is reachable from tests; they inject a deterministic one.
os.environ["RETRIEVAL_INDEXER_ENABLED"] = "false"
# Failed memory saves are retried by tests that cover it, never in the background.
os.environ["PIPELINE_WORKER_ENABLED"] = "false"
os.environ["PROACTIVE_ENABLED"] = "false"
os.environ["SOURCE_SYNC_ENABLED"] = "false"
os.environ["PUSH_NOTIFICATIONS_ENABLED"] = "false"

import pytest  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
