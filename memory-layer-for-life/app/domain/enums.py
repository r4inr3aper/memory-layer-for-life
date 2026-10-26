"""Controlled vocabularies shared by the persistence, service, and API layers.

Every value stored in a status-like or type-like column comes from one of these
enums. Database CHECK constraints mirror them (see ``app.db.constraints``), so a
value added here needs a migration before it can be persisted.
"""

from enum import StrEnum


class MessageSource(StrEnum):
    WHATSAPP_IMPORT = "whatsapp_import"
    MANUAL_CAPTURE = "manual_capture"
    API_INPUT = "api_input"
    APP_CHAT = "app_chat"
    # The text read out of a photo or PDF the user gave to remember.
    FILE_UPLOAD = "file_upload"


class ProcessingStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class PipelineStage(StrEnum):
    """Stages of one processing run, in execution order."""

    NORMALIZE = "normalize"
    EXTRACT = "extract"
    RESOLVE = "resolve"
    CONSTRUCT = "construct"
    PERSIST = "persist"


class RunEventType(StrEnum):
    """Entries of the append-only processing run audit log."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    EXTRACTION_STORED = "extraction_stored"
    EXTRACTION_REUSED = "extraction_reused"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    REQUEUED = "requeued"
    LEASE_EXPIRED = "lease_expired"
    # The owner looked at a run held back for review: saved a memory from it, or dismissed it.
    REVIEWED = "reviewed"


class ReplayAction(StrEnum):
    """What a replay request did for one processing unit."""

    CREATED = "created"
    REQUEUED = "requeued"
    UNCHANGED = "unchanged"


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ExtractionDisposition(StrEnum):
    """What the extractor decided to do with a processing unit.

    ``EXTRACT`` and ``CONTEXT`` both produce memories. ``CONTEXT`` marks material kept
    for reference only. ``ABSTAIN`` means the unit does not carry enough information to
    form a reliable memory, so nothing is invented and the run is sent to review.
    """

    EXTRACT = "extract"
    CONTEXT = "context"
    ABSTAIN = "abstain"


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    CONCEPT = "concept"
    PLACE = "place"
    EVENT = "event"
    TECHNOLOGY = "technology"
    TOPIC = "topic"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    ARCHIVED = "archived"


class MentionResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


class MemoryType(StrEnum):
    SEMANTIC_FACT = "semantic_fact"
    EPISODIC_EVENT = "episodic_event"
    PREFERENCE = "preference"
    INTENTION = "intention"
    TASK = "task"
    COMMITMENT = "commitment"
    GOAL = "goal"
    PROJECT = "project"
    DECISION = "decision"
    IDEA = "idea"
    OPEN_LOOP = "open_loop"
    PLAN = "plan"
    NOTE = "note"
    REFLECTION = "reflection"
    RESOURCE = "resource"
    FINANCIAL_NOTE = "financial_note"


class MemoryStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class MemoryOrigin(StrEnum):
    """Who wrote a memory: the pipeline, from messages; the user, by hand or by correcting
    one; or the assistant, when the user asked it to (a reminder)."""

    PIPELINE = "pipeline"
    USER = "user"
    ASSISTANT = "assistant"
    # A connected app, such as an event of the user's calendar.
    APP = "app"


class MemoryEventAction(StrEnum):
    """Entries of a memory's change history (``memory_events``).

    A memory the pipeline made has no ``created`` entry: its sources say where it came
    from. A correction makes a new memory (``corrected``) and retires the old one
    (``superseded``), so each version keeps its own history.
    """

    CREATED = "created"
    ACCEPTED = "accepted"
    RETRACTED = "retracted"
    RESTORED = "restored"
    EDITED = "edited"
    CORRECTED = "corrected"
    SUPERSEDED = "superseded"
    MERGED = "merged"
    REPLACED = "replaced"
    SUGGESTION_DISMISSED = "suggestion_dismissed"
    # Life state: an open item done, given up, opened again, or (re)scheduled; a reminder
    # sent.
    COMPLETED = "completed"
    DROPPED = "dropped"
    REOPENED = "reopened"
    SCHEDULED = "scheduled"
    REMINDED = "reminded"
    # The pipeline met the same memory again and gave it the new evidence instead of
    # saving a duplicate (ADR-048).
    MENTIONED_AGAIN = "mentioned_again"


class SuggestionKind(StrEnum):
    """Why two memories are shown together for review."""

    # They say the same thing; one can be merged into the other.
    DUPLICATE = "duplicate"
    # They are about the same thing and differ; one may be out of date.
    CONFLICT = "conflict"


class CloseReason(StrEnum):
    """Why an open item (a task, plan, goal, ...) is no longer open."""

    DONE = "done"
    DROPPED = "dropped"


class LifeBucket(StrEnum):
    """Where an open item sits in the user's life state, by when it is due."""

    OVERDUE = "overdue"
    TODAY = "today"
    # Due within the next seven days.
    UPCOMING = "upcoming"
    LATER = "later"
    # No due date.
    SOMEDAY = "someday"


class MemoryState(StrEnum):
    """Whether the thing a memory describes is stated as pending or completed.

    This is separate from ``MemoryStatus``, which is the lifecycle of the record itself.
    ``DONE`` is only valid when the source explicitly says so: an intention or a plan is
    never evidence of completion.
    """

    NOT_APPLICABLE = "not_applicable"
    OPEN = "open"
    PLANNED = "planned"
    DONE = "done"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class SourceRole(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    CONTEXTUAL = "contextual"


class MemoryEntityRelation(StrEnum):
    MENTIONS = "mentions"


class RelationType(StrEnum):
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    SUPPORTS = "supports"
    ELABORATES = "elaborates"
    RELATED_TO = "related_to"


class LlmOperation(StrEnum):
    """What a model call was made for."""

    EXTRACTION = "extraction"
    JUDGE = "judge"
    CONNECTION_CHECK = "connection_check"
    # One step of the assistant's tool-use loop.
    CHAT = "chat"
    # One step of the assistant executing a saved schedule.
    SCHEDULED_TASK = "scheduled_task"
    # Turning text into vectors, for memory retrieval.
    EMBEDDING = "embedding"
    # Ordering retrieved memories by relevance to a query.
    RERANK = "rerank"
    # Reading the text out of a photo or PDF.
    TRANSCRIPTION = "transcription"


class LlmCallOrigin(StrEnum):
    """Which part of the system made a model call.

    ``OTHER`` covers calls that belong to no run, such as a connection check.
    """

    PIPELINE = "pipeline"
    PLAYGROUND = "playground"
    EVALUATION = "evaluation"
    OTHER = "other"
    ASSISTANT = "assistant"
    SCHEDULER = "scheduler"
    # Embedding memories so they can be found by meaning.
    INDEXING = "indexing"
    # Embedding or reranking for a memory search.
    RETRIEVAL = "retrieval"
    # Turning a file the user gave into memory evidence.
    CAPTURE = "capture"


class LlmCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PlaygroundRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvaluationRunStatus(StrEnum):
    """Lifecycle of one evaluation run.

    ``COMPLETED`` means the run reached its end, not that every case passed or even that
    every case could be evaluated. ``INTERRUPTED`` marks a run whose process stopped.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class EvaluationTrigger(StrEnum):
    """How an evaluation run came to exist."""

    CONSOLE = "console"
    CLI = "cli"
    IMPORT = "import"


class EvaluationCaseOutcome(StrEnum):
    """Result of one case. ``NOT_EVALUATED`` neither passes nor fails."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


# --- Assistant app ------------------------------------------------------------------


class ThreadKind(StrEnum):
    """A user has exactly one main thread and any number of side threads."""

    MAIN = "main"
    SIDE = "side"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ScheduleFrequency(StrEnum):
    """How a schedule repeats. Every rule has a wall-clock time in its timezone.

    ``ONCE`` runs on one date. ``WEEKLY`` runs on one or more weekdays (Monday to Friday is
    "weekdays"). ``MONTHLY`` runs on a day of the month, or the month's last day when it is
    shorter. ``INTERVAL`` runs every so many hours from a first run.
    """

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL = "interval"


class Weekday(StrEnum):
    """Declared in ``datetime.weekday()`` order, so a member's position is its number."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class ScheduleDelivery(StrEnum):
    """Where the result of a scheduled run goes.

    ``CHAT`` posts it into the thread the schedule came from. Every other destination is
    reached through the user's connected app for it.
    """

    CHAT = "chat"
    SLACK = "slack"
    EMAIL = "email"
    CALENDAR = "calendar"
    NOTION = "notion"
    TEAMS = "teams"
    DISCORD = "discord"


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    # A one-time schedule whose slot has come: it has no more runs. Editing its date makes
    # it active again.
    COMPLETED = "completed"


class ScheduleRunTrigger(StrEnum):
    SCHEDULE = "schedule"
    MANUAL = "manual"


class ScheduleRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # A slot that was not run: it came due while nothing was dispatching and too much time
    # had passed when dispatching resumed, or an earlier run of the task was still going.
    SKIPPED = "skipped"


class ProposalStatus(StrEnum):
    """A schedule the assistant proposed in chat. Nothing is created until confirmed."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class ToolConnectionStatus(StrEnum):
    """Stored state of a user's connection to an app.

    ``NOT_CONNECTED`` is never stored: it is what the API reports when no row exists.
    """

    NOT_CONNECTED = "not_connected"
    PENDING = "pending"
    CONNECTED = "connected"
    FAILED = "failed"
    REVOKED = "revoked"


class DevicePlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class RetrievalLeg(StrEnum):
    """An independent way retrieval finds memories; each ranks its own candidates."""

    # The query's words in the memory's text (PostgreSQL full-text search).
    LEXICAL = "lexical"
    # The query's meaning near the memory's embedding (pgvector).
    SEMANTIC = "semantic"
    # A person, place, or thing the query names, linked to the memory.
    ENTITY = "entity"


class ImportStatus(StrEnum):
    """A chat import: read and waiting for the user's choices, or handed to the pipeline."""

    PREVIEWED = "previewed"
    QUEUED = "queued"


class InsightKind(StrEnum):
    """What an insight is about (``app.domain.insights``)."""

    MONEY = "money"
    PEOPLE_TOP = "people.top"
    PEOPLE_QUIET = "people.quiet"
    FOLLOW_THROUGH = "follow_through"
    GOAL_QUIET = "goal.quiet"
    THEME = "theme"


class InsightTarget(StrEnum):
    """Where the app goes when an insight is opened."""

    PERSON = "person"
    MEMORY = "memory"
    TODO = "todo"
    MEMORIES = "memories"


class UsageGranularity(StrEnum):
    """The period a usage history is grouped by. Periods are UTC, like the daily limit;
    weeks start on Monday."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class DocumentExtraction(StrEnum):
    """How the text of a document the user uploaded was read (ADR-049)."""

    # The PDF's own text layer, read without a model.
    TEXT_LAYER = "text_layer"
    # The paragraphs of a Word document.
    DOCX = "docx"
    # A plain-text or Markdown file, as it is.
    PLAIN_TEXT = "plain_text"
    # A scanned PDF read by the model, when the operator allows it.
    VISION = "vision"


class LinkKind(StrEnum):
    """What a link the user saved is (ADR-050). The assistant uses the resume link in job
    applications; at most one link is the resume."""

    RESUME = "resume"
    PORTFOLIO = "portfolio"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    WEBSITE = "website"
    OTHER = "other"
