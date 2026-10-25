# System Architecture

## Architectural direction

Use a modular monolith initially. Keep clear internal boundaries without prematurely deploying microservices. PostgreSQL is the canonical source of truth. External providers and future retrieval indexes are replaceable components.

## Logical layers

1. **Input layer** — manual capture and later imports/integrations (WhatsApp first; possible Telegram, voice/STT, OCR/images, email, calendar, browser, files, APIs).
2. **Ingestion and processing** — capture, normalize, optional transcription/OCR, extraction, classification, enrichment, validation.
3. **Memory kernel** — immutable event/source store, typed memories, entity mentions, canonical entities, source provenance, versioning, conflict handling, state transitions.
4. **Storage** — PostgreSQL for structured state/relationships; pgvector initially for embeddings; object storage for binary artifacts when needed; Redis/queue only when justified; separate graph DB optional and deferred.
5. **Knowledge graph** — entity and memory relationships represented first in PostgreSQL tables.
6. **Temporal engine** — historical, current, and future state; deadlines, recurrence, stale detection, context awareness, timeline queries.
7. **Life-state engine** — derived view of current context, active goals, open loops, commitments, neglected areas, patterns, and insights.
8. **Agents/intelligence** — future planner, accountability, proactive, and tool-using components. Begin with deterministic services and constrained LLM calls; avoid multi-agent complexity early.
9. **Notification/action layer** — daily brief, reminders, nudges, follow-ups, insights, and user-approved actions.
10. **Feedback loop** — observe actual outcomes, record corrections, update memories/state, and evaluate whether suggestions helped.

The diagram is a north star. Implement each layer only when prior layers provide reliable data and interfaces.

## Initial backend stack

- Python 3.12+.
- FastAPI.
- Pydantic v2 and pydantic-settings.
- SQLAlchemy 2.0 async.
- PostgreSQL.
- Alembic.
- Official OpenAI Python SDK (`AsyncOpenAI`) behind an integration boundary.
- pytest, pytest-asyncio, HTTPX, Ruff, and type checking.
- Docker Compose for local PostgreSQL.

Use pgvector in PostgreSQL for the first semantic retrieval implementation. Avoid separate vector/graph databases until there is evidence to justify them.

## Resource lifecycle

- One async SQLAlchemy engine per application process.
- One async session factory per engine/process.
- One fresh `AsyncSession` per request or unit of work; never share live sessions across concurrent tasks.
- One reusable `AsyncOpenAI` client per process, initialized/closed through FastAPI lifespan.
- No network calls during module import or application startup.
- No OpenAI dependency for basic liveness or database readiness.

## Main data flow

1. Receive source input.
2. Persist raw source before expensive processing.
3. Create a processing run with stable identity/version.
4. Normalize input without destroying the original.
5. Extract a schema-validated candidate representation.
6. Resolve entity mentions with explicit uncertainty.
7. Construct proposed/active memory records with provenance.
8. Persist logically related writes transactionally where possible.
9. Record stage status and errors.
10. Make output available for review and retrieval.
11. Allow safe replay using preserved evidence and explicit versions.

A failed stage must not destroy raw input. Completed stages should be reusable where safe; retries must not duplicate side effects.

## Separation of concerns

- API routers: HTTP only; thin handlers and dependencies.
- Pydantic schemas: request/response and validated internal contracts.
- Services: application use cases and orchestration.
- Repositories: persistence/query boundaries.
- SQLAlchemy models: persistence representation only.
- Domain: enums and rules independent of HTTP.
- Integrations: OpenAI and future external providers.
- Migrations: all schema changes.
- Evaluation: golden examples, deterministic tests, model-quality tests.

Avoid generic abstraction layers without concrete value. Repositories must not depend on FastAPI request objects; ORM models must not call LLMs; Pydantic API schemas must not be ORM models.

## Reliability properties

- Source identity and processing identity are distinct.
- Database constraints enforce idempotency.
- Extraction outputs are versioned.
- Provenance is many-to-many.
- Entity matching is conservative and correctable.
- Historical records are not destructively overwritten.
- Errors are structured and sanitized.
- Retries are bounded and target transient failures.
- Replay is an explicit operation, not a new capture.
- Vector indexes and derived state are rebuildable from canonical records.

## Deferred infrastructure

Do not add these in the initial foundation without demonstrated need:
- Redis or a distributed queue.
- Kafka/event streaming.
- Separate vector DB.
- Separate graph DB.
- Microservices.
- Multi-agent orchestration framework.
- Large workflow engine.
- Full authentication/multi-tenancy/billing.
- Object storage before binary artifacts require it.

A simple PostgreSQL-backed job mechanism may be enough initially; select it when the ingestion phase is implemented based on actual reliability needs.
