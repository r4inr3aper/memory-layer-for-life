# Roadmap and Phase Gates

This is the intended dependency order, not a claim that any phase has been implemented.

## Phase 0 — Backend foundation and data architecture

**Goal:** create a runnable, tested backend repository.

Deliver:
- FastAPI app and versioned API router.
- Pydantic v2 settings and schemas.
- PostgreSQL, SQLAlchemy 2.0 async, Alembic.
- Application lifespan.
- One async engine/session factory per process; fresh session per unit of work.
- One reusable AsyncOpenAI client per process, closed on shutdown.
- Core relational schema and migration.
- Health/live and health/ready endpoints.
- Docker Compose, Dockerfile, `.env.example`, README, Makefile.
- Unit/integration/contract/lifecycle tests, lint and type checking.

Exit gate:
- Clean DB migrates successfully.
- API runs and health endpoints behave correctly.
- Tests pass against PostgreSQL.
- Secrets are not committed/logged.
- No pipeline business logic is prematurely embedded in routers/models.

## Phase 1 — Memory ingestion pipeline

**Goal:** source message → extraction → entity resolution → structured memory → persistence, with replay and idempotency.

Deliver:
- Raw message intake/import boundary.
- Versioned Pydantic extraction contract.
- Provider-independent extraction service.
- Entity resolution with unresolved/ambiguous states.
- Memory construction and many-to-many provenance.
- Processing runs, stage status, sanitized errors.
- Database-enforced idempotency and concurrency handling.
- Single-message and batch replay.
- Retry/recovery behavior.
- Golden-dataset and deterministic regression tests.

Exit gate:
- Reprocessing the same logical version creates no duplicate effects.
- Reprocessing with a new version preserves history.
- Every memory can be traced to evidence.
- Failed processing never loses raw input.
- Ambiguity/conflicts are represented, not silently guessed.

## Phase 2 — Retrieval foundation

**Goal:** reliably find relevant memories and original context.

Deliver:
- pgvector extension and migrations.
- Embedding generation boundary and versioning.
- Memory embeddings.
- Document chunks if needed for long sources.
- Semantic retrieval, keyword retrieval, SQL filters.
- Hybrid retrieval and source-grounded results.
- Retrieval evaluation set and metrics.

Exit gate:
- Representative queries retrieve relevant source-backed records.
- Embeddings can be rebuilt.
- Model changes are traceable.
- Retrieval never treats similarity as proof.

## Phase 3 — Memory management and corrections

**Goal:** keep memory coherent over time.

Deliver:
- Proposed/active/superseded/retracted lifecycle.
- Conflict detection and explicit supersession.
- User corrections and entity merge/re-resolution.
- Deduplication/consolidation with provenance.
- Temporal validity handling.
- Review queue for uncertain outputs.

Exit gate:
- Corrections do not destroy evidence.
- Contradictions remain inspectable.
- Memory changes are auditable and tested.

## Phase 4 — Domain state and life-state engine

**Goal:** derive what is true/relevant now from memory and operational records.

Deliver as justified:
- Dedicated task model and lifecycle.
- Goals/projects and milestones.
- Open loops, follow-ups, waiting-on states.
- Timezone-aware scheduling and recurring items.
- Temporal queries and stale-item detection.
- Current context and active-state projection.

Do not model every task as an unstructured generic memory. Do not infer completion from silence.

## Phase 5 — API and product integration

**Goal:** expose reliable backend behavior to the UI.

Deliver:
- Capture API and inbox/review APIs.
- Search and memory detail with source evidence.
- Task/project/goal endpoints as those models exist.
- Pagination, filtering, validation, and stable error contracts.
- Authentication/authorization before exposing personal data beyond a trusted local environment.
- End-to-end tests for critical workflows.

## Phase 6 — Planning, accountability, and notifications

**Goal:** support follow-through without being intrusive.

Deliver:
- Daily brief.
- Contextual reminders and follow-ups.
- Planner with deadlines and conflicts.
- Accountability checks based on explicit commitments.
- Notification preferences, schedules, delivery attempts, and dismissal state.
- User approval for consequential actions.

Use a reliable job mechanism only when scheduled/async workflows require it. Define retry and idempotency semantics for notifications and external actions.

## Phase 7 — Proactive insights and feedback

**Goal:** learn from corrections and actual outcomes.

Deliver:
- Pattern detection and grounded suggestions.
- Feedback records (accepted/rejected/corrected).
- Observe planned vs actual outcomes.
- Quality and usefulness metrics.
- Rate limits, user controls, and anti-spam safeguards.
- Explain why each insight is surfaced and which evidence supports it.

## Phase 8 — Integrations and scale, only when justified

Possible integrations: messaging, calendar, email, files, browser, OCR/STT, object storage, external tools. Add Redis, a queue, separate vector/graph infrastructure, or services only when measured requirements warrant them.

## Phase management rules

- Finish exit gates before building dependent capabilities.
- Do not implement all architecture-diagram boxes in the MVP.
- Update `docs/STATUS.md` after meaningful work.
- Record architectural changes in `docs/DECISIONS.md`.
- A phase is complete only when behavior is implemented and verified, not when files merely exist.
