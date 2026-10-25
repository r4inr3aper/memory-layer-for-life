from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/db"
# What a staging or production API must have (see deployed_settings_are_complete).
DEPLOYED: dict[str, Any] = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@ep-x.us-east-2.aws.neon.tech/neondb?ssl=require",
    "SUPABASE_URL": "https://abc.supabase.co",
    "ANTHROPIC_API_KEY": "sk-ant-test",
}


def make_settings(**overrides: Any) -> Settings:
    """Settings built only from the given values, never from a developer's ``.env``."""
    values = {"DATABASE_URL": DATABASE_URL, **overrides}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_default_settings_valid() -> None:
    settings = make_settings()

    assert settings.APP_NAME == "second-brain"
    assert settings.ANTHROPIC_MODEL == "claude-sonnet-5-5"
    assert settings.ANTHROPIC_REFUSAL_FALLBACK is True
    assert settings.EXTRACTION_EFFORT == "medium"
    assert settings.PIPELINE_MAX_ATTEMPTS == 3


def test_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL must be one of"):
        make_settings(LOG_LEVEL="INVALID")


def test_log_level_is_normalized() -> None:
    assert make_settings(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"


def test_invalid_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL must be a PostgreSQL connection string"):
        make_settings(DATABASE_URL="mysql://user:pass@localhost:3306/db")


def test_is_production_flag() -> None:
    settings = make_settings(ENVIRONMENT="production", **DEPLOYED)

    assert settings.is_production is True
    assert settings.is_deployed is True
    assert settings.is_testing is False


def test_is_testing_flag() -> None:
    settings = make_settings(ENVIRONMENT="testing")

    assert settings.is_testing is True
    assert settings.is_production is False


def test_anthropic_api_key_is_optional() -> None:
    assert make_settings().ANTHROPIC_API_KEY is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_api_key_means_not_configured(blank: str) -> None:
    assert make_settings(ANTHROPIC_API_KEY=blank).ANTHROPIC_API_KEY is None


def test_api_key_is_trimmed() -> None:
    assert make_settings(ANTHROPIC_API_KEY="  sk-ant-test  ").ANTHROPIC_API_KEY == "sk-ant-test"


def test_timezone_must_be_a_known_zone() -> None:
    assert make_settings(DEFAULT_TIMEZONE="Asia/Kolkata").DEFAULT_TIMEZONE == "Asia/Kolkata"
    with pytest.raises(ValidationError, match="DEFAULT_TIMEZONE"):
        make_settings(DEFAULT_TIMEZONE="Mars/Olympus_Mons")


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"EXTRACTION_EFFORT": "extreme"}, id="unknown effort"),
        pytest.param({"PIPELINE_MAX_ATTEMPTS": 0}, id="no attempts"),
        pytest.param({"PIPELINE_RUN_LEASE_SECONDS": 0}, id="no lease"),
        pytest.param({"PIPELINE_RETRY_BASE_SECONDS": -1}, id="negative backoff"),
        pytest.param({"ANTHROPIC_TIMEOUT": 0}, id="no timeout"),
        pytest.param({"ANTHROPIC_MAX_RETRIES": -1}, id="negative retries"),
        pytest.param({"INGESTION_MAX_UNIT_MESSAGES": 0}, id="empty units only"),
        pytest.param({"EXTRACTION_MAX_TOKENS": 0}, id="no output tokens"),
    ],
)
def test_out_of_range_values_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


# --- Assistant app ---------------------------------------------------------------------


def test_the_assistant_app_is_unconfigured_by_default() -> None:
    settings = make_settings()

    assert settings.SUPABASE_URL is None
    assert settings.supabase_issuer is None
    assert settings.supabase_jwks_url is None
    assert settings.COMPOSIO_API_KEY is None
    assert settings.BROWSERBASE_API_KEY is None
    assert settings.assistant_model == settings.ANTHROPIC_MODEL
    # The test environment turns the scheduler off, so the declared default is checked.
    assert Settings.model_fields["SCHEDULER_ENABLED"].default is True


def test_retrieval_searches_by_meaning_only_with_a_voyage_key() -> None:
    settings = make_settings(VOYAGE_API_KEY="  ", RETRIEVAL_RERANK_MODEL="")

    assert settings.VOYAGE_API_KEY is None
    assert settings.RETRIEVAL_RERANK_MODEL is None
    assert (settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS) == ("voyage-4", 1024)
    assert Settings.model_fields["RETRIEVAL_INDEXER_ENABLED"].default is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"EMBEDDING_DIMENSIONS": 768},
        {"EMBEDDING_BATCH_SIZE": 0},
        {"RETRIEVAL_MIN_SEMANTIC_SIMILARITY": 1.5},
        {"RETRIEVAL_INDEXER_INTERVAL_SECONDS": 0},
    ],
)
def test_invalid_retrieval_settings_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_supabase_addresses_follow_from_the_project_url() -> None:
    settings = make_settings(SUPABASE_URL="https://abc.supabase.co/")

    assert settings.SUPABASE_URL == "https://abc.supabase.co"
    assert settings.supabase_issuer == "https://abc.supabase.co/auth/v1"
    assert settings.supabase_jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"


def test_an_explicit_jwks_address_wins() -> None:
    settings = make_settings(
        SUPABASE_URL="https://abc.supabase.co", SUPABASE_JWKS_URL="https://keys.example/jwks"
    )

    assert settings.supabase_jwks_url == "https://keys.example/jwks"


@pytest.mark.parametrize(
    "name", ["SUPABASE_URL", "SUPABASE_JWKS_URL", "COMPOSIO_API_KEY", "BROWSERBASE_API_KEY"]
)
def test_blank_integration_settings_mean_unconfigured(name: str) -> None:
    assert getattr(make_settings(**{name: "  "}), name) is None


def test_costs_are_shown_in_rupees_by_default() -> None:
    settings = make_settings()

    assert (settings.USAGE_CURRENCY, settings.USAGE_CURRENCY_PER_USD) == ("INR", 88)


@pytest.mark.parametrize(
    "overrides",
    [
        {"USAGE_CURRENCY": "inr"},
        {"USAGE_CURRENCY": "RUPEES"},
        {"USAGE_CURRENCY_PER_USD": 0},
        {"USAGE_CURRENCY": "USD", "USAGE_CURRENCY_PER_USD": 88},
    ],
)
def test_an_invalid_display_currency_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_service_addresses_must_be_web_urls() -> None:
    with pytest.raises(ValidationError):
        make_settings(SUPABASE_URL="abc.supabase.co")


def test_the_assistant_model_can_differ_from_the_extraction_model() -> None:
    settings = make_settings(ASSISTANT_MODEL="claude-haiku-5-5")

    assert settings.assistant_model == "claude-haiku-5-5"


# --- Environments ----------------------------------------------------------------------


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError):
        make_settings(ENVIRONMENT="prod")


@pytest.mark.parametrize(
    ("environment", "deployed"),
    [("development", False), ("testing", False), ("staging", True), ("production", True)],
)
def test_staging_and_production_are_deployed(environment: str, deployed: bool) -> None:
    assert make_settings(ENVIRONMENT=environment, **DEPLOYED).is_deployed is deployed


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_a_complete_deployed_configuration_is_accepted(environment: str) -> None:
    settings = make_settings(ENVIRONMENT=environment, OPERATOR_API_KEY="k" * 32, **DEPLOYED)

    assert settings.is_deployed is True


def test_a_deployed_api_names_everything_to_fix() -> None:
    with pytest.raises(ValidationError) as caught:
        make_settings(ENVIRONMENT="production", OPERATOR_API_KEY="short", CORS_ORIGINS=["*"])

    message = str(caught.value)
    for problem in (
        "points at this machine",
        "must require TLS",
        "SUPABASE_URL must be set",
        "ANTHROPIC_API_KEY must be set",
        "OPERATOR_API_KEY must be at least 32 characters",
        "CORS_ORIGINS must list origins",
    ):
        assert problem in message


@pytest.mark.parametrize("query", ["ssl=require", "sslmode=require", "sslmode=verify-full"])
def test_either_tls_parameter_satisfies_a_deployed_api(query: str) -> None:
    url = f"postgresql+asyncpg://user:pass@db.example.com/app?{query}"

    assert make_settings(ENVIRONMENT="staging", **{**DEPLOYED, "DATABASE_URL": url})


def test_a_plain_http_supabase_address_is_refused_when_deployed() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_URL must be set"):
        make_settings(
            ENVIRONMENT="staging", **{**DEPLOYED, "SUPABASE_URL": "http://abc.supabase.co"}
        )


def test_a_developer_computer_needs_none_of_it() -> None:
    assert make_settings(ENVIRONMENT="development").is_deployed is False


@pytest.mark.parametrize(
    ("environment", "explicit", "enabled"),
    [
        ("development", None, True),
        ("staging", None, True),
        ("production", None, False),
        ("production", True, True),
        ("development", False, False),
    ],
)
def test_api_docs_are_off_in_production_unless_asked_for(
    environment: str, explicit: bool | None, enabled: bool
) -> None:
    settings = make_settings(ENVIRONMENT=environment, API_DOCS_ENABLED=explicit, **DEPLOYED)

    assert settings.api_docs_enabled is enabled


def test_allowed_emails_are_compared_without_case_or_blanks() -> None:
    settings = make_settings(ACCESS_ALLOWED_EMAILS=[" Ada@Example.com ", "", "grace@example.com"])

    assert settings.ACCESS_ALLOWED_EMAILS == ["ada@example.com", "grace@example.com"]


def test_everyone_may_sign_in_without_an_access_list() -> None:
    assert make_settings().ACCESS_ALLOWED_EMAILS == []


def test_a_settings_error_never_echoes_secrets() -> None:
    """Startup errors land in the platform's logs."""
    with pytest.raises(ValidationError) as caught:
        make_settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql+asyncpg://user:hunter2-password@localhost/db",
            ANTHROPIC_API_KEY="sk-ant-very-secret",
        )

    message = str(caught.value)
    assert "SUPABASE_URL must be set" in message
    assert "hunter2-password" not in message
    assert "sk-ant-very-secret" not in message


def test_embedding_dimensions_can_come_from_the_environment() -> None:
    """Environment values are text; "512" must mean 512, not an error at startup."""
    assert make_settings(EMBEDDING_DIMENSIONS="512").EMBEDDING_DIMENSIONS == 512


def test_an_unsupported_embedding_size_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        make_settings(EMBEDDING_DIMENSIONS="768")


def test_the_env_template_loads() -> None:
    """Copying .env.example to .env must give a working configuration."""
    from app.core.config import PROJECT_ROOT

    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")  # type: ignore[call-arg]

    assert settings.EMBEDDING_DIMENSIONS == 1024


@pytest.mark.parametrize(
    ("copied", "used"),
    [
        (
            "postgresql://u:p@ep-x.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.us-east-2.aws.neon.tech/neondb?ssl=require",
        ),
        ("postgres://u:p@db.example.com/app", "postgresql+asyncpg://u:p@db.example.com/app"),
        (
            "postgresql+asyncpg://u:p@db.example.com/app?ssl=require",
            "postgresql+asyncpg://u:p@db.example.com/app?ssl=require",
        ),
    ],
)
def test_a_database_url_copied_from_neon_works_as_it_is(copied: str, used: str) -> None:
    """asyncpg takes ``ssl``, not ``sslmode``, and has no channel binding."""
    settings = make_settings(DATABASE_URL=copied)

    assert used == settings.DATABASE_URL


def test_a_neon_url_satisfies_a_deployed_api() -> None:
    copied = "postgresql://u:p@ep-x.us-east-2.aws.neon.tech/neondb?sslmode=require"

    assert make_settings(ENVIRONMENT="production", **{**DEPLOYED, "DATABASE_URL": copied})
