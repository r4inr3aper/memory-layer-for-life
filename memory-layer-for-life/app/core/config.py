from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
# development: a developer's computer. staging and production: deployed, reached over the
# internet (see is_deployed). testing: the test suite.
Environment = Literal["development", "staging", "production", "testing"]

# A deployed API must reach its database over TLS.
_TLS_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_MIN_OPERATOR_KEY_LENGTH = 32

# The directory that holds ``app/``. Paths in the settings are relative to it, so they
# mean the same thing whatever directory a command is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def is_known_timezone(name: str) -> bool:
    """Whether ``name`` is an IANA timezone this machine knows."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # A settings error is printed at startup, into the platform's logs: it must name
        # the problem without echoing the values, which include the database password
        # and API keys.
        hide_input_in_errors=True,
    )

    # Application
    APP_NAME: str = "second-brain"
    ENVIRONMENT: Environment = "development"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://brain:brain_dev_password@localhost:5432/second_brain"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # Anthropic (optional - not required for DB-only operations)
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"
    ANTHROPIC_TIMEOUT: int = Field(default=60, gt=0)
    ANTHROPIC_MAX_RETRIES: int = Field(default=2, ge=0)
    # When the model's safety classifiers decline a note, let the API retry it on the
    # fallback model Anthropic recommends, instead of failing the run. The parameter
    # is only sent to models that have such a fallback (see app.domain.model_catalog).
    ANTHROPIC_REFUSAL_FALLBACK: bool = True

    # Extraction
    EXTRACTION_EFFORT: EffortLevel = "medium"
    EXTRACTION_MAX_TOKENS: int = Field(default=16000, gt=0)
    # IANA name of the timezone the user writes in. Message times are shown to the
    # extractor in this zone so that words like "tomorrow" can be read correctly.
    DEFAULT_TIMEZONE: str = "UTC"

    # Pipeline reliability. Provider-level retries (ANTHROPIC_MAX_RETRIES) happen inside
    # one attempt, so one run makes at most
    # PIPELINE_MAX_ATTEMPTS * (ANTHROPIC_MAX_RETRIES + 1) provider calls.
    PIPELINE_MAX_ATTEMPTS: int = Field(default=3, ge=1)
    PIPELINE_RETRY_BASE_SECONDS: float = Field(default=30.0, ge=0)
    PIPELINE_RETRY_MAX_SECONDS: float = Field(default=900.0, ge=0)
    PIPELINE_RUN_LEASE_SECONDS: float = Field(default=600.0, gt=0)
    # The API retries failed and interrupted runs itself while this is true: every
    # interval it releases runs whose worker vanished and processes due ones.
    PIPELINE_WORKER_ENABLED: bool = True
    PIPELINE_WORKER_INTERVAL_SECONDS: float = Field(default=30.0, gt=0)
    PIPELINE_WORKER_BATCH_SIZE: int = Field(default=10, ge=1)

    # Ingestion limits
    INGESTION_MAX_UNIT_MESSAGES: int = Field(default=20, ge=1)
    INGESTION_MAX_BATCH_UNITS: int = Field(default=100, ge=1)
    INGESTION_MAX_CONTENT_CHARS: int = Field(default=20000, ge=1)

    # Evaluation. The dataset path is relative to the project root unless absolute.
    EVALUATION_DATASET_PATH: str = "golden.jsonl"
    # A run that is still marked running but has scored no case for this long belongs
    # to a process that stopped, and is marked interrupted.
    EVALUATION_STALE_AFTER_SECONDS: float = Field(default=900.0, gt=0)

    # Console. The built web UI is served from this directory when it exists.
    CONSOLE_UI_DIR: str = "frontend/dist"
    # The operator routes (capture, processing, memories, console, call log, playground,
    # evaluations, reports) answer only requests from this computer. Requests from
    # elsewhere must send this key in the X-Operator-Key header; without it set, they are
    # refused. The app's own routes are unaffected: they need a signed-in user. A deployed
    # API (staging, production) never trusts "this computer": only the key opens them.
    OPERATOR_API_KEY: str | None = None
    # The interactive API documentation (/docs, /redoc, /openapi.json). Unset: on
    # everywhere except production, where the API's shape is nobody else's business.
    API_DOCS_ENABLED: bool | None = None

    # Supabase Auth. The mobile app signs users in with Supabase, and the API verifies
    # their access tokens against the project's published signing keys. Without
    # SUPABASE_URL every endpoint that needs a user answers 503.
    SUPABASE_URL: str | None = None
    # Defaults to the project's well-known JWKS address.
    SUPABASE_JWKS_URL: str | None = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    # Used only to delete a user's sign-in identity when they delete their account.
    # Without it, deleting an account removes all data but leaves the Supabase user.
    SUPABASE_SECRET_KEY: str | None = None
    SUPABASE_JWKS_CACHE_SECONDS: float = Field(default=600.0, gt=0)
    # Who may use the app. Anyone can create a Supabase sign-in with Google, and every
    # user can spend the daily prompt limit, so a private deployment lists its people
    # here (a JSON list of email addresses). Empty: everyone who signs in.
    ACCESS_ALLOWED_EMAILS: list[str] = Field(default_factory=list)

    # Assistant (Cooper). The model defaults to ANTHROPIC_MODEL.
    ASSISTANT_MODEL: str | None = None
    ASSISTANT_EFFORT: EffortLevel = "medium"
    ASSISTANT_MAX_TOKENS: int = Field(default=8000, gt=0)
    # Model calls one turn may make. Each tool result costs one more call.
    ASSISTANT_MAX_STEPS: int = Field(default=10, ge=1)
    # How many earlier messages of a thread the model sees.
    ASSISTANT_HISTORY_MESSAGES: int = Field(default=40, ge=1)
    CHAT_MAX_MESSAGE_CHARS: int = Field(default=8000, ge=1)
    # Files attached to one message, and the size of each after base64 decoding.
    CHAT_MAX_ATTACHMENTS: int = Field(default=3, ge=0)
    CHAT_MAX_ATTACHMENT_BYTES: int = Field(default=5 * 1024 * 1024, ge=1)
    # How long a thread stays reserved for a reply. Covers every process serving the API;
    # a reply that takes longer, or whose process died, frees the thread when it expires.
    CHAT_TURN_LEASE_SECONDS: float = Field(default=600.0, gt=0)

    # Prompts per user per UTC day. A prompt is a chat message the user sends or a
    # scheduled run. A user's own limit (app_users.daily_prompt_limit) overrides it.
    # 0 means unlimited.
    ASSISTANT_DAILY_PROMPT_LIMIT: int = Field(default=40, ge=0)
    # The currency the app shows costs in, and how many units of it one US dollar buys.
    # Model prices are in dollars; the rate is fixed here, so costs are estimates.
    USAGE_CURRENCY: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    USAGE_CURRENCY_PER_USD: Decimal = Field(default=Decimal("88"), gt=0)

    # Chats become memories: each message a user sends (of at least a few words) goes
    # through the memory pipeline in the background, owned by that user. Users can turn it
    # off for themselves; this turns it off for everyone.
    MEMORY_CAPTURE_ENABLED: bool = True

    # Memory retrieval. Words and names are always searched; meaning is searched with
    # embeddings from Voyage AI (Anthropic offers no embedding model) when a key is set.
    # The model and dimensions form the embedding space: changing either starts a new
    # space, which the indexer fills (scripts/index_memories.py). An optional reranker
    # reads the query with each top result to order them.
    VOYAGE_API_KEY: str | None = None
    VOYAGE_BASE_URL: str = "https://api.voyageai.com/v1"
    EMBEDDING_MODEL: str = "voyage-4"
    EMBEDDING_DIMENSIONS: Literal[256, 512, 1024, 2048] = 1024
    EMBEDDING_BATCH_SIZE: int = Field(default=64, ge=1, le=1000)
    RETRIEVAL_RERANK_MODEL: str | None = None
    # Below this cosine similarity a memory counts as unrelated. Measure before changing.
    RETRIEVAL_MIN_SEMANTIC_SIMILARITY: float = Field(default=0.3, ge=-1, le=1)
    # The API embeds new and changed memories in the background while this is on.
    RETRIEVAL_INDEXER_ENABLED: bool = True
    RETRIEVAL_INDEXER_INTERVAL_SECONDS: float = Field(default=15.0, gt=0)

    # Push notifications through Expo's push service, for finished scheduled runs. The
    # access token is optional; set it when the Expo project requires one.
    PUSH_NOTIFICATIONS_ENABLED: bool = True
    EXPO_PUSH_ACCESS_TOKEN: str | None = None

    # How the background loops below pace themselves. Unset: each polls at its own
    # interval, right for an always-on database. Set (e.g. 3600) for a database that
    # scales to zero and counts awake time, like Neon's free plan: loops keep their own
    # interval only while someone used the app in the last BACKGROUND_ACTIVE_WINDOW_SECONDS
    # or while work is queued; otherwise they all wake together at this interval, or
    # exactly when a schedule slot, reminder, brief, or retry is due. See
    # app/services/pacing.py.
    BACKGROUND_IDLE_INTERVAL_SECONDS: float | None = Field(default=None, gt=0)
    BACKGROUND_ACTIVE_WINDOW_SECONDS: float = Field(default=120.0, gt=0)

    # Scheduled tasks. The API runs a dispatcher loop when enabled. Several processes
    # may run it at once: a schedule slot is claimed in the database, so it runs once.
    # Connected apps as memory sources (calendar events). The API syncs enabled ones at
    # this interval while this is true.
    SOURCE_SYNC_ENABLED: bool = True
    SOURCE_SYNC_INTERVAL_SECONDS: float = Field(default=21600.0, gt=0)
    # Reminders and daily briefs. The API sends due ones itself while this is true.
    PROACTIVE_ENABLED: bool = True
    PROACTIVE_POLL_SECONDS: float = Field(default=60.0, gt=0)
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_POLL_SECONDS: float = Field(default=60.0, gt=0)
    SCHEDULER_BATCH_SIZE: int = Field(default=10, ge=1)
    # Due runs executed at the same time by one dispatcher pass.
    SCHEDULER_CONCURRENCY: int = Field(default=3, ge=1)
    # A run still marked running after this long belongs to a process that stopped.
    SCHEDULE_RUN_STALE_SECONDS: float = Field(default=1800.0, gt=0)
    # A slot found later than this (when the server was down, for example) is skipped, not
    # run late. Interval schedules use at most half their period.
    SCHEDULE_MISSED_GRACE_SECONDS: float = Field(default=3600.0, gt=0)

    # Connected apps through Composio. Without a key the app catalog is still listed,
    # but connecting and app tools are unavailable.
    COMPOSIO_API_KEY: str | None = None
    COMPOSIO_BASE_URL: str = "https://backend.composio.dev"
    # Optional per-toolkit auth config ids, for example {"gmail": "ac_..."}, such as one
    # with your own OAuth app. Without one, connecting uses the Composio project's auth
    # config for the toolkit, or creates one with Composio's managed sign-in.
    COMPOSIO_AUTH_CONFIGS: dict[str, str] = Field(default_factory=dict)

    # Browser tasks through Browserbase. Without a key the browser tool is not offered.
    BROWSERBASE_API_KEY: str | None = None
    BROWSERBASE_BASE_URL: str = "https://api.browserbase.com"
    BROWSERBASE_RUN_TIMEOUT_SECONDS: float = Field(default=240.0, gt=0)

    # The largest request body the API reads. The largest legitimate one is a chat
    # message with three 5 MB files in base64 (about 20 MB); a WhatsApp export is at most
    # 10 MB (about 13.4 MB). Anything larger is refused with 413 before it is buffered.
    MAX_REQUEST_BYTES: int = Field(default=25 * 1024 * 1024, ge=1024)

    # Timeout for one HTTP request to Supabase, Composio, or Browserbase.
    INTEGRATION_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_deployed(self) -> bool:
        """Served on the internet rather than from a developer's computer."""
        return self.ENVIRONMENT in ("staging", "production")

    @property
    def api_docs_enabled(self) -> bool:
        if self.API_DOCS_ENABLED is not None:
            return self.API_DOCS_ENABLED
        return not self.is_production

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "testing"

    @property
    def evaluation_dataset_path(self) -> Path:
        return resolve_project_path(self.EVALUATION_DATASET_PATH)

    @property
    def console_ui_dir(self) -> Path:
        return resolve_project_path(self.CONSOLE_UI_DIR)

    @property
    def assistant_model(self) -> str:
        return self.ASSISTANT_MODEL or self.ANTHROPIC_MODEL

    @property
    def supabase_issuer(self) -> str | None:
        """The ``iss`` claim Supabase Auth puts in this project's access tokens."""
        if self.SUPABASE_URL is None:
            return None
        return f"{self.SUPABASE_URL}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str | None:
        if self.SUPABASE_JWKS_URL is not None:
            return self.SUPABASE_JWKS_URL
        if self.SUPABASE_URL is None:
            return None
        return f"{self.SUPABASE_URL}/auth/v1/.well-known/jwks.json"

    @model_validator(mode="after")
    def deployed_settings_are_complete(self) -> "Settings":
        """A deployed API refuses to start half-configured, naming everything to fix.

        Without this, a missing key shows up later as 503s in the app, and a database
        reached without TLS or a short operator key is a quiet security hole.
        """
        if not self.is_deployed:
            return self
        problems: list[str] = []
        database = urlsplit(self.DATABASE_URL)
        if database.hostname in _LOCAL_HOSTS:
            problems.append("DATABASE_URL points at this machine, not the hosted database")
        query = parse_qs(database.query)
        ssl_modes = {*query.get("ssl", []), *query.get("sslmode", [])}
        if not ssl_modes & _TLS_SSL_MODES:
            problems.append("DATABASE_URL must require TLS (add ?ssl=require)")
        if self.SUPABASE_URL is None or not self.SUPABASE_URL.startswith("https://"):
            problems.append("SUPABASE_URL must be set to the project's https address")
        if self.ANTHROPIC_API_KEY is None:
            problems.append("ANTHROPIC_API_KEY must be set")
        if (
            self.OPERATOR_API_KEY is not None
            and len(self.OPERATOR_API_KEY) < _MIN_OPERATOR_KEY_LENGTH
        ):
            problems.append(
                f"OPERATOR_API_KEY must be at least {_MIN_OPERATOR_KEY_LENGTH} characters"
            )
        if "*" in self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must list origins, not '*'")
        if problems:
            raise ValueError(f"{self.ENVIRONMENT} settings are incomplete: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def usd_costs_are_not_converted(self) -> "Settings":
        if self.USAGE_CURRENCY == "USD" and self.USAGE_CURRENCY_PER_USD != 1:
            raise ValueError("USAGE_CURRENCY_PER_USD must be 1 when USAGE_CURRENCY is USD")
        return self

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql", "postgres")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return normalize_database_url(v)

    @field_validator(
        "ANTHROPIC_API_KEY",
        "ASSISTANT_MODEL",
        "SUPABASE_JWKS_URL",
        "COMPOSIO_API_KEY",
        "BROWSERBASE_API_KEY",
        "SUPABASE_SECRET_KEY",
        "EXPO_PUSH_ACCESS_TOKEN",
        "VOYAGE_API_KEY",
        "RETRIEVAL_RERANK_MODEL",
        "OPERATOR_API_KEY",
    )
    @classmethod
    def blank_api_key_means_unconfigured(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return v.strip()

    @field_validator("SUPABASE_URL")
    @classmethod
    def normalize_optional_base_url(cls, v: str | None) -> str | None:
        """Blank means unconfigured."""
        if v is None or not v.strip():
            return None
        return normalize_base_url(v)

    @field_validator("COMPOSIO_BASE_URL", "BROWSERBASE_BASE_URL")
    @classmethod
    def normalize_required_base_url(cls, v: str) -> str:
        return normalize_base_url(v)

    @field_validator("BACKGROUND_IDLE_INTERVAL_SECONDS", mode="before")
    @classmethod
    def blank_interval_means_unset(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("EMBEDDING_DIMENSIONS", mode="before")
    @classmethod
    def dimensions_from_text(cls, v: object) -> object:
        """Environment values arrive as text, and the allowed sizes are numbers."""
        if isinstance(v, str) and v.strip().isdigit():
            return int(v)
        return v

    @field_validator("ACCESS_ALLOWED_EMAILS")
    @classmethod
    def normalize_allowed_emails(cls, v: list[str]) -> list[str]:
        """Compared case-insensitively; blanks are dropped."""
        return [email.strip().lower() for email in v if email.strip()]

    @field_validator("DEFAULT_TIMEZONE")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if not is_known_timezone(v):
            raise ValueError(f"DEFAULT_TIMEZONE is not a known IANA timezone: {v}")
        return v


def normalize_database_url(value: str) -> str:
    """The URL the API's driver needs, from one copied from a provider's dashboard.

    Neon hands out ``postgresql://...?sslmode=require&channel_binding=require``. The API
    connects with asyncpg, which needs the ``postgresql+asyncpg`` scheme and takes ``ssl``
    where libpq takes ``sslmode``; it has no channel binding. SQLAlchemy passes query
    parameters to asyncpg as they are, so both would fail at the first connection.
    """
    parts = urlsplit(value.strip())
    scheme = "postgresql+asyncpg" if parts.scheme in ("postgres", "postgresql") else parts.scheme
    if scheme != "postgresql+asyncpg":
        return value
    query: dict[str, str] = {}
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        query.setdefault("ssl" if key == "sslmode" else key, item)
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_base_url(value: str) -> str:
    """Validate an http(s) base URL and drop a trailing slash, so paths join cleanly."""
    url = value.strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise ValueError("must be an http(s) URL")
    return url


def resolve_project_path(value: str) -> Path:
    """Turn a configured path into an absolute one, relative to the project root."""
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
