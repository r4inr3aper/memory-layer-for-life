# Architecture Decision Records (ADRs)

Record important decisions here. Add dated ADRs as choices are made; do not rewrite history without noting supersession.

## ADR-001 — Modular monolith first

**Decision:** Start with one FastAPI application with clear internal modules.

**Reason:** The project is greenfield and the initial workload does not justify distributed services. Internal boundaries keep the code maintainable without operational overhead.

**Revisit when:** independently scaling/deploying a component or team ownership creates a demonstrated need.

## ADR-002 — PostgreSQL is canonical source of truth

**Decision:** Store source records, extraction results, canonical entities, memories, provenance, and initial relationships in PostgreSQL.

**Reason:** Strong constraints, transactions, relational queries, JSONB, mature migrations, and broad operational support.

**Consequence:** Vector indexes, caches, and derived life-state projections are rebuildable; they do not replace canonical records.

## ADR-003 — pgvector before a separate vector DB

**Decision:** Prefer pgvector in PostgreSQL for the first semantic retrieval version.

**Reason:** Avoid operational duplication and keep metadata filtering/provenance close to canonical data.

**Revisit when:** measured scale, latency, isolation, or retrieval requirements justify separate infrastructure.

## ADR-004 — Async SQLAlchemy lifecycle

**Decision:** One async engine and session factory per application process; a fresh session per request or unit of work.

**Reason:** Reuse connection infrastructure safely while isolating transaction/session state across concurrent operations.

## ADR-005 — One OpenAI client per process

**Status:** Superseded by ADR-010 on 2026-10-11. The lifecycle rule stands; the provider changed.

**Decision:** Reuse one `AsyncOpenAI` client per application process, created/closed via application lifespan and accessed through a replaceable integration boundary.

**Reason:** Efficient connection reuse, consistent configuration, and testability. No module-import network effects.

## ADR-006 — Preserve raw evidence and version interpretations

**Decision:** Raw messages remain immutable; extraction outputs are versioned; memories preserve many-to-many provenance and explicit lifecycle.

**Reason:** Enables replay, auditing, corrections, model/prompt improvements, and conflict handling without losing the original input.

## ADR-007 — Pydantic validation at boundaries

**Decision:** Validate API input and LLM outputs with explicit Pydantic v2 contracts before business logic/persistence.

**Reason:** LLM output and external input are untrusted. Typed contracts reduce silent data corruption.

## ADR-008 — Separate generic memory from operational domain models

**Decision:** A common `memories` table supports typed knowledge, but complex tasks, projects, transactions, notifications, and feedback may receive dedicated tables.

**Reason:** Shared provenance and retrieval are useful, while lifecycle-heavy domains need proper constraints and queryable fields.

## ADR-009 — Defer infrastructure until justified

**Decision:** No Redis, Kafka, microservices, separate graph DB, or agent framework in the initial foundation.

**Reason:** Reduce complexity until measured workload or product behavior requires it.

## ADR-010 — Anthropic is the model provider (supersedes ADR-005)

**Status:** The default model named below was changed by ADR-023 on 2026-10-12. Everything else stands.

**Date:** 2026-10-11

**Decision:** Use the official Anthropic Python SDK. One `AsyncAnthropic` client per application process, created and closed through the application lifespan. The default model is `claude-haiku-5-5`, set by `ANTHROPIC_MODEL`. The pipeline never imports the SDK: it depends on the `Extractor` interface in `app/integrations/extraction/base.py`, and `AnthropicExtractor` is the only adapter.

**Reason:** The project owner chose Anthropic and Haiku. The lifecycle reasoning of ADR-005 is unchanged: connection reuse, consistent configuration, no network effect at import or startup.

**Consequence:** The `openai` dependency is removed. A provider change now means writing one adapter and changing the fingerprint, nothing else.

## ADR-011 — A processing run covers an ordered unit of messages

**Date:** 2026-10-12

**Decision:** The pipeline processes a *unit*: one or more raw messages read together, in order. `processing_runs.raw_message_id` is the unit's first message and `processing_run_messages` holds the whole unit. In Phase 1 the caller decides what a unit is. The API accepts units; nothing groups messages automatically.

**Reason:** The real data needs it. People send one thought as several messages ("229" then "Ice cream"), and 19 of the 124 golden cases only make sense read together. Grouping by guesswork would silently invent relationships, so grouping is an explicit input.

**Consequence:** The same message can belong to several units, and each unit is processed independently. A WhatsApp importer will need a versioned, tested segmentation rule before it can form units by itself.

**Revisit when:** the WhatsApp export importer is built.

## ADR-012 — Three identities, each enforced by the database

**Date:** 2026-10-12

**Decision:**
- *Source identity* is `(source, source_message_id)`, unique when the source supplies an id. Redelivery with the same content returns the stored message. Redelivery with different content is refused with a conflict and never overwrites.
- *Processing identity* is `processing_runs.idempotency_key`: a SHA-256 over the pipeline fingerprint and the unit's ordered message ids.
- *Output identity* is `extraction_results.processing_run_id` (one result per run), `memories (origin_extraction_result_id, origin_ordinal)`, and `entity_mentions (extraction_result_id, ordinal)`.

All three are unique constraints, and writes use `INSERT ... ON CONFLICT DO NOTHING`, so concurrent callers cannot create duplicates.

**Reason:** Idempotency has to survive retries, concurrent requests, and application bugs. An in-memory check survives none of them.

**Consequence:** A content hash is stored for diagnostics only. It is never an identity, because identical text can be two real messages.

## ADR-013 — A pipeline fingerprint decides what counts as "the same version"

**Date:** 2026-10-12

**Decision:** `PipelineFingerprint` lists everything that can change output: pipeline label, normalizer, extraction schema, extractor provider, model, prompt version, resolver, memory builder. Its digest is part of the processing identity and the full fingerprint is stored in the run's metadata. Each component has a version constant that must be bumped when its behavior changes.

**Reason:** Replay must do nothing for an unchanged configuration and must produce a new, separate result for a changed one. Tying the identity to an explicit fingerprint makes both true by construction, including when only the model name in the environment changes.

**Consequence:** Replaying a unit under a new fingerprint creates a new run and new proposed memories. Runs and memories of older fingerprints are never modified.

## ADR-014 — PostgreSQL is the job queue; runs are a state machine

**Date:** 2026-10-12

**Decision:** No queue infrastructure. A run is a row that moves from queued to running, and from running to succeeded, needs_review, or failed, with a return to queued for bounded retries. Workers claim rows atomically with a conditional UPDATE, and pick the next one with `FOR UPDATE SKIP LOCKED`. Transient failures retry with exponential backoff up to `PIPELINE_MAX_ATTEMPTS`. A run left running longer than `PIPELINE_RUN_LEASE_SECONDS` is released. Every attempt is recorded in the append-only `processing_run_events` table. The API processes a unit in a background task right after capture; `python -m scripts.process_pending` is the recovery worker.

**Reason:** ADR-009 defers extra infrastructure, and the workload is one person's notes. PostgreSQL gives atomic claims, durability, and inspection with what is already there.

**Consequence:** Abstention and rejected model output end in needs_review, not in an error. Permanent provider failures end in failed without retry. A succeeded run is never executed again.

**Revisit when:** throughput or scheduling needs exceed what polling one table can do.

## ADR-015 — Three short transactions per run, with ownership checks

**Date:** 2026-10-12

**Decision:** A run executes as claim, extract, materialize. The model call happens with no transaction open. The validated extraction result is stored before anything is derived from it, so a retry reuses it and does not call the model again. Entities, mentions, memories, provenance, and the final status are written in one transaction. Every write after the claim locks the run row and verifies the worker still owns that attempt.

**Reason:** Holding a transaction across a slow network call ties up a connection and widens every failure window. All-or-nothing materialization means a crash never leaves half a memory. The ownership check stops a slow worker whose lease expired from writing over the worker that replaced it.

## ADR-016 — Extraction contract 1.0

**Date:** 2026-10-12

**Decision:** The extractor returns a disposition (`extract`, `context`, `abstain`), memories, and entity mentions, validated by `app/schemas/extraction.py`. Each memory carries a type, a statement, a `state`, a confidence, evidence quotes with message indexes, an ambiguity note, and optional time and money details. The model is never asked for ids, timestamps, character offsets, or normalized names: the system computes those. The Phase 0 placeholder contract, which never stored data, is replaced under the same version number.

**Reason:** Model output is untrusted (ADR-007). Structured outputs constrain generation, Pydantic validates the result, and a grounding step rejects references to messages that do not exist. Keeping system facts out of the contract removes a whole class of invented values.

**Consequence:** `state` records whether something is pending or stated as done and is separate from the lifecycle `status` of the memory record. `currency` and `resolved_date` are null unless the source supports them. A quote is stored as evidence only if it really occurs in the cited message.

## ADR-017 — Entity resolution is exact, deterministic, and conservative

**Date:** 2026-10-12

**Decision:** A mention matches an entity only on equal type and equal normalized name. One active candidate resolves it, following merges to the surviving entity. Several candidates leave it `ambiguous` with no link. No candidate creates a new entity. Text that cannot be a name stays `unresolved`. Find-or-create runs under a transaction-scoped advisory lock on the name.

**Reason:** A false merge corrupts memory quietly and is hard to undo; a missed merge is visible and cheap to fix later. Names are not unique by design, so a lock, not a constraint, has to close the race between two runs meeting the same new name.

**Revisit when:** Phase 3 adds corrections and merges, or when fuzzy matching can be evaluated against labelled data.

## ADR-018 — The pipeline only proposes

**Date:** 2026-10-12

**Decision:** Every memory the pipeline writes has status `proposed`. The pipeline never activates, supersedes, deduplicates, or retracts a memory, and never derives a validity period. Reprocessing under a new version adds new proposed memories next to the old ones.

**Reason:** Activation and reconciliation are product decisions that need the review and correction flows of Phase 3. Doing them implicitly inside ingestion would overwrite history without an audit trail.

**Consequence:** Until Phase 3 exists, consumers must treat memories as candidates and may see one memory per pipeline version for the same unit.

## ADR-019 — Memory types extended for real content

**Date:** 2026-10-12

**Decision:** `MemoryType` gains `plan`, `note`, `reflection`, `resource`, and `financial_note`. All memory types, statuses, and other vocabularies are enforced by CHECK constraints generated from the domain enums.

**Reason:** The original eleven types could not represent a large share of real notes: expenses, saved links and titles, schedules, working notes, and reflections. The project vision already lists these kinds of memory.

**Consequence:** Adding a type needs a migration. Financial notes keep their amounts in validated metadata until a dedicated transactions model is justified (ADR-008).

## ADR-020 — Evidence is immutable in the database, and models must match migrations

**Date:** 2026-10-12

**Decision:** A trigger rejects every UPDATE on `raw_messages`. Migrations are the only source of schema. A test builds the models into a scratch schema and compares columns, defaults, constraints, and indexes with the migrated schema. Integration tests run against a database built by the real migrations.

**Reason:** ADR-006 promised immutable evidence but nothing enforced it, and the old ingestion code overwrote content on redelivery. The first revision also drifted from the models in several CHECK constraints and created constraints under doubled names, and no test could notice because tests used `create_all`.

**Consequence:** Revision 002 repairs the names and aligns both sides. Any future drift fails the suite.

## ADR-021 — Evaluation has three layers and explicit pass criteria

**Date:** 2026-10-12

**Decision:**
1. Deterministic tests never call a model.
2. Every golden case runs through the real pipeline on PostgreSQL with a fixture extractor that answers what the dataset expects.
3. A live evaluation calls the configured model and scores each case.

A live case passes when all of these hold: valid output; abstention exactly when expected; the expected memory is conveyed; its type is one the label mapping accepts; no invented completion; amounts, currency, and dates agree with the label; no `must_not` rule is broken; nothing unsupported is stated. Coverage, rules, and groundedness are judged by a model, with explanations kept for audit. Exact wording and exact memory count are not required.

Two comparisons are reported without gating: `extract` versus `context`, and the pending-or-done state. The extraction prompt must never contain dataset cases.

**Reason:** The dataset is unreviewed and its free-form labels are not fully consistent: inputs of the same shape carry different `extract` and `context` labels. Gating on a field the labels do not define consistently would reward memorizing the dataset. `evaluation/label_mapping.py` records how each label is read, per label and never per case.

**Consequence:** "All cases pass" is a statement about these criteria and these draft labels. It is not a claim of ground truth.

**Revisit when:** the dataset is reviewed and its labels are made consistent, at which point disposition can become a gating check.

## ADR-022 — Deliberately not built in Phase 1

**Date:** 2026-10-12

**Decision:** These are deferred and documented as open:
- A WhatsApp export parser and automatic segmentation. The export file itself was not available, only the dataset derived from it, and its exact format must be inspected first.
- Authentication and authorization. The API is for a trusted local environment only.
- Embeddings, retrieval, deduplication, supersession, and review actions, which belong to Phases 2 and 3.

## ADR-023 — Sonnet 5.5 is the default model, and the model stays a setting

**Date:** 2026-10-12

**Decision:** The default of `ANTHROPIC_MODEL` is `claude-sonnet-5-5`. Any deployment may choose another model in `.env`, and `claude-haiku-5-5` stays supported. Known models, their list prices, and whether they offer a refusal fallback live in one catalog, `app/domain/model_catalog.py`. The refusal fallback is requested only from models that have one.

**Reason:** In the Phase 1 evaluation Haiku levelled off at 119 to 120 of 124 cases across four prompt revisions and two effort levels, and kept stating a guess as certain in 1 to 3 notes per run. Sonnet reached 121 to 122 with no confirmed unsupported statement. The project owner had asked to switch when Haiku stopped improving. A second price table in the evaluation code had drifted from the list prices and overstated the cost by about 11 percent, which is why prices now have one home.

**Consequence:** Sonnet costs about ten times as much per note as Haiku. The model name is part of the pipeline fingerprint (ADR-013), so a change of model never rewrites existing memories. This supersedes the default named in ADR-010. The evidence is in `PHASE1_REPORT.md`.

## ADR-024 — Every model call is logged as facts, never as content

**Date:** 2026-10-12

**Decision:** Each call to a model provider writes exactly one row to `llm_calls`: what was asked for, who asked (pipeline, playground, evaluation, or other, with a link to its run), how it ended, the tokens it used, its estimated cost, and how long it took. An observer that wraps the call reports the row through a recorder port, and the row is written in its own transaction. It never holds the prompt, the messages, or the output. The cost is computed from the catalog when the row is written and is never recomputed.

**Reason:** Cost and reliability have to be answerable from the database, also for calls that fail, return something unusable, or are cancelled. Content already has one home per origin, each with its own rules, and copying it into a log would create a second place where private notes live. A cost that changed whenever prices change would make past totals unstable.

**Consequence:** The log is append-only and safe to show in the console. A cost is an estimate from list prices, and it is empty for a model the catalog does not know. Calls made before migration 003 are not in the log.

## ADR-025 — Evaluations are stored, and the console is served by the API

**Date:** 2026-10-12

**Decision:** An evaluation run and the result of each case are rows, written while the run executes, with a heartbeat. One evaluation runs at a time per process. A case the provider could not answer is `not_evaluated`, which neither passes nor fails. Older report files are imported idempotently. A built web console in `frontend/dist` is served at the root of the API when that folder exists. It uses hash routing, so it needs no server-side route, and it talks only to the public API.

**Reason:** Results kept only in files could not be compared or shown. In run 12 of Phase 1 an account without credit made 48 cases count as failures, which was a wrong statement about quality. One process and one address keep local use simple and need no second server.

**Consequence:** Stored case results contain the text of the dataset's notes, so the database is as private as the dataset. The console has no login and is for a trusted local environment only (ADR-022). The limit of one evaluation is per process, so several API processes could each run one.

## ADR-026 — This API is the mobile app's backend; Supabase only signs users in

**Date:** 2026-10-18

**Decision:** The Muse mobile app keeps no server code. Its chat, history, schedules, and app connections move from Expo API routes, direct Supabase table queries, and a Supabase Edge Function into this modular monolith, as new tables (revision 004), services, and `/me`, `/threads`, `/schedules`, and `/tools` routes. The application database stays the hosted PostgreSQL on Neon, reached through `DATABASE_URL` with SQLAlchemy and Alembic; the owner chose it over the Supabase project's database on 2026-10-18. The app talks to Supabase only to sign in.

**Reason:** The owner asked for one backend, with Supabase for identity, and chose to keep the data on Neon. Business logic scattered across a mobile client, edge functions, and table policies could not be tested together; here it gets the same layering, migrations, and tests as the memory layer. Keeping SQLAlchemy instead of Supabase's Data API keeps the transactions, constraints, and concurrency guarantees the rest of the system relies on.

**Consequence:** The memory-layer tables and the app's tables live in one database. The app's previous Supabase tables are not migrated; the new project started empty. Moving the database to Supabase later is a change of `DATABASE_URL` plus `alembic upgrade head`. ADR-001 stands: the app is one more module, not a service.

## ADR-027 — Users are Supabase Auth users, verified locally

**Date:** 2026-10-18

**Decision:** App routes require `Authorization: Bearer <Supabase access token>`. The API verifies it against the project's JWKS (`SUPABASE_JWKS_URL`), accepting only asymmetric algorithms (ES256, RS256, EdDSA), the project's issuer, the `authenticated` audience and role, and a UUID subject. Keys are fetched on first use, cached, and refreshed when an unknown key id appears, at most every 30 seconds. The first request of a user writes `app_users` with the Supabase id. Every lookup of a user's record is scoped to them, so another user's record reads as missing (404), not forbidden.

**Reason:** Local verification needs no call to Supabase per request and no shared secret: the API is never given the JWT secret or the Supabase secret key, so it cannot mint tokens and a leak of its configuration cannot either. Rate-limited refresh picks up key rotation without letting forged key ids make the API hammer Supabase.

**Consequence:** Tokens signed with a legacy HS256 secret are refused. Revoked sessions stay valid until their token expires, which Supabase keeps short. The memory-layer and console routes still have no sign-in (ADR-022); that remains open.

## ADR-028 — Cooper runs on Claude in a provider-independent tool-use loop

**Date:** 2026-10-18

**Status:** Replaces the app's OpenAI Agents runtime.

**Decision:** The assistant is a loop in `app/services/assistant/` over a step interface (`app/integrations/assistant/base.py`); `AnthropicAssistantModel` is the only module that imports the SDK, streams text, and reports each call to the call log (operation `chat` or `scheduled_task`, origin `assistant` or `scheduler`). Tools validate their input as untrusted. A reply streams to the app as newline-delimited JSON while the turn runs as background work, and both messages are stored by the server, so a reply survives a client that disconnects. Scheduling is a tool, `propose_schedule`, that only attaches a proposal to the reply; the schedule is created from the stored proposal when the user confirms it. Stable instructions and tools are prompt-cached; the time and connected apps go in a separate uncached block.

**Reason:** One model provider, one client per process, and one call log (ADR-010, ADR-024). The previous design called the model twice per message (an intent parser, then the agent) and trusted the client to save the assistant's words. Creating schedules from server-stored proposals means a client cannot schedule something the user was not shown.

**Consequence:** Browser work uses Browserbase's hosted agent runs instead of step-by-step Stagehand control, which has no Python equivalent; the user still watches it live. One turn runs per thread per process.

## ADR-029 — Scheduled runs are claimed in PostgreSQL and run at most once

**Date:** 2026-10-18

**Decision:** The dispatcher locks due schedules with `FOR UPDATE SKIP LOCKED`, inserts a run for the slot, and moves `next_run_at` to the first slot after now, in one transaction. A unique index allows one run per slot and a second one running run per schedule. A run is never retried; one still running after `SCHEDULE_RUN_STALE_SECONDS` is marked interrupted. Slots missed while nothing dispatched are skipped. Times are computed in the schedule's IANA timezone. A scheduled run may change data only in the app it delivers to, and delivery to an app counts only when a data-changing action in that app succeeded.

**Reason:** A run may send a message; sending it twice is worse than reporting a failure. ADR-014 already makes PostgreSQL the job queue, and the same pattern is safe with several API processes. The previous dispatcher added a day in UTC, which drifted across daylight-saving changes.

**Consequence:** The API runs the dispatcher in its lifespan while `SCHEDULER_ENABLED` is true; `scripts/run_schedules.py` runs it alone. pg_cron and the Edge Function are no longer used.

## ADR-030 — Every table has row level security

**Date:** 2026-10-18

**Decision:** Revision 005 enables row level security on every table, with no policies. A test fails for any table without it.

**Reason:** Defense in depth. Supabase publishes the public schema through its Data API to anyone holding the publishable key, which ships inside the mobile app, and Neon offers an optional Data API too. If the database is ever served that way, row level security keeps every table closed. Without policies, only the tables' owner, the role the API connects as, can use them.

**Consequence:** The API must keep connecting as the owner. Access for any other role is a deliberate future decision, made with policies.

## ADR-031 — Usage is limited per user, counted from the database

**Date:** 2026-10-19

**Status:** Superseded by ADR-036 (a daily prompt limit).

**Decision:** A turn is a chat message the user sends or a scheduled run. Turns are limited per UTC calendar month (`ASSISTANT_MONTHLY_TURN_LIMIT`, default 500) and chat messages per minute (`CHAT_RATE_LIMIT_PER_MINUTE`, default 10); 0 means unlimited. Both are counted from the stored messages and runs, not from counters. A refused message answers 429 (`QUOTA_EXCEEDED`, or `RATE_LIMITED` with `Retry-After`) and stores nothing. A scheduled run over the limit fails with `QUOTA_EXCEEDED` without calling the model and is not counted. `GET /me/usage` reports the same numbers, plus tokens and estimated cost from `llm_calls`, which now records the user (`llm_calls.user_id`). There is no billing: the limit is a cost guard, set by the operator.

**Reason:** Counting from the rows the API already writes needs no new state, holds across every process serving the API, and cannot drift from what happened. Turns, not tokens, are what a user understands and what the app can show.

**Consequence:** Concurrent requests can pass the check together, so a limit can be exceeded by at most the requests in flight. Plans or per-user limits would need a column on `app_users` and, for payment, a billing provider.

## ADR-032 — One reply per thread, held by a lease in the database

**Date:** 2026-10-19

**Decision:** Storing the user's message sets `chat_threads.turn_lease_until` in the same transaction, under a row lock. Storing the reply clears it in the reply's transaction; a failed or cancelled reply clears it before the error event is sent. A lease left by a process that died expires after `CHAT_TURN_LEASE_SECONDS`. Clearing a thread's messages is refused while a lease is held.

**Reason:** The previous in-process lock allowed two API processes to interleave replies in one thread. A lease works across processes, and its expiry recovers from crashes without an operator.

**Consequence:** After a crash, the thread is locked for up to the lease time (10 minutes by default).

## ADR-033 — Attached files are passed to the model, not stored

**Date:** 2026-10-19

**Decision:** A chat message can carry up to `CHAT_MAX_ATTACHMENTS` images or PDFs of up to `CHAT_MAX_ATTACHMENT_BYTES` each, as base64 in the JSON request. They go to Claude with that turn only. The stored message keeps their names, types, and sizes (`metadata.attachments`); later turns tell the model only that they were attached.

**Reason:** Storing user files needs object storage, retention rules, and deletion paths that the app does not need yet. Sending a file once keeps every later turn's cost flat.

**Consequence:** The model cannot look at an earlier file again; the user re-attaches it. Storing files is a later, deliberate decision.

## ADR-034 — Deleting an account revokes access first and the sign-in last

**Date:** 2026-10-19

**Decision:** `DELETE /me` revokes the user's Composio accounts, deletes their row (schema cascades remove threads, messages, schedules, runs, connections, push tokens, and feedback; the cost log keeps its rows with the user cleared), and then deletes their Supabase identity through the admin API when `SUPABASE_SECRET_KEY` is set. Apps that cannot be revoked and whether the identity was deleted are reported in the response.

**Reason:** Third-party access must not outlive the account, so it goes first. The identity goes last, because if it fails the user can sign in again and repeat the request; the reverse order could leave data with no way for the user to reach it.

**Consequence:** The API holds the Supabase secret key, which can act on every user, and uses it for nothing else.

## ADR-035 — Push notifications through Expo's push service

**Date:** 2026-10-19

**Decision:** The app registers each device's Expo push token (`POST /me/push-tokens`). When a scheduled run ends, its owner is notified on every device unless they turned notifications off; the notification carries the thread id so the app can open the result. Tokens Expo reports as `DeviceNotRegistered` are deleted. A failed notification is logged and never affects the run.

**Reason:** One HTTP API covers iOS and Android with no Apple or Google credentials in this service; Expo holds them for the app's builds.

**Consequence:** Push needs an installed build of the app tied to an Expo project (`eas init`); Expo Go on Android cannot receive it. Push receipts (delivery confirmations) are not checked yet.

## ADR-036 — A daily prompt limit, counted in its own table

**Date:** 2026-10-24

**Decision:** Supersedes the limits in ADR-031. Each user gets `ASSISTANT_DAILY_PROMPT_LIMIT` prompts (default 40) per UTC day; a prompt is a chat message sent or a scheduled run. The per-minute rate limit is removed. Each prompt is counted in `daily_usage` (one row per user and day, chat messages and scheduled runs counted separately) by a single `INSERT ... ON CONFLICT DO UPDATE ... WHERE used < limit`, inside the transaction that stores the message. `app_users.daily_prompt_limit` overrides the limit for one user; 0 means unlimited. A scheduled run is counted only once its delivery checks pass, just before the model is called. The 429 message says when more prompts are available, in the user's timezone.

**Reason:** The owner chose a small daily allowance. A counter row makes the check and the count one atomic statement, so concurrent requests cannot exceed the limit (ADR-031's counting from messages could, by the requests in flight), and it keeps usage even after a thread is cleared or deleted. With 40 a day, a per-minute limit adds nothing.

**Consequence:** Usage before revision 007 is not counted. A turn that fails after its message was stored still uses its prompt. The day is UTC, so users east or west of UTC see the reset at a local time other than midnight; the app shows that time.

## ADR-037 — App users' chats become their own memories

**Date:** 2026-10-24

**Decision:** Each message an app user sends is captured as memory evidence (`raw_messages`, source `app_chat`, the chat message id as its source id) and processed by the existing pipeline in the background. `raw_messages`, `entities`, and `memories` gain `owner_id` (revision 008); empty means the operator's own store, so existing data keeps its meaning. A unit never mixes owners; entity resolution only matches entities of the same owner; new entities and memories take the unit's owner; the extraction call is attributed to the user in the cost log. Only the user's own words are captured, never the assistant's replies, and messages under three words are skipped. Capture can be turned off per user (`app_users.memory_capture_enabled`, in the app) and for everyone (`MEMORY_CAPTURE_ENABLED`). Users read their memories through `GET /me/memories`; the unauthenticated console routes show only the operator's data. The user's timezone travels with the evidence (`metadata.timezone`), so relative dates resolve in it. Deleting an account deletes the user's memory data in dependency order, the one exception to evidence never being deleted.

**Reason:** Memories are personal data, and a shared entity table would merge different people's "Mom". Ownership on the three roots (evidence, entities, memories) scopes everything derived from them without touching the pipeline's guarantees: evidence stays immutable while it exists, runs stay idempotent, resolution stays deterministic. Capturing only the user's words keeps assistant guesses from becoming "facts".

**Consequence:** Memories are not yet used by the assistant (recall needs retrieval, Phase 2) and are not reviewed (Phase 3); they stay `proposed`. Each captured message costs one extraction call. Runs that fail are retried by `scripts/process_pending.py`, which nothing runs automatically yet.

## ADR-038 — Memory retrieval: three legs fused by rank, embeddings as a derived index

**Date:** 2026-10-24

**Decision:** A memory search runs three independent legs, each restricted to the owner and the query's filters inside its own SQL, then fuses their rankings with reciprocal rank fusion (k = 60, equal weights) and loads the winners from the source of truth with their evidence and entities.

- *Words:* PostgreSQL full-text search over a generated `memories.search_document` column (English stems weighted above exact words, GIN index). A query becomes an OR of its terms, without stopwords and question filler such as "remember", ranked by `ts_rank_cd`.
- *Names:* memories linked to an entity whose normalized name appears in the query as a phrase (score 1), or, for names of four or more characters, whose name is within pg_trgm `strict_word_similarity` 0.5 of a query word.
- *Meaning:* cosine similarity over pgvector embeddings of a memory document ("Fact: …" plus an "About: names" line), an exact scan, at least 0.3.
- *Optional reranking:* a cross-encoder reads the top 30 fused candidates when `RETRIEVAL_RERANK_MODEL` is set.

Embeddings live in `memory_embeddings` (revision 009), one row per memory and embedding space (`provider/model/dimensions`), with the hash and version of the document embedded. An embedding counts only while it is at least as new as its memory. An indexer loop in the API (every 15 seconds) embeds new and changed memories in one call per owner, attributed to that owner in the call log (origin `indexing`); a document whose hash still matches is marked current without a call. `scripts/index_memories.py` runs a pass, a full check (`verify`), a `rebuild`, or prunes other spaces. The provider is Voyage AI, `voyage-4` at 1024 dimensions, called over HTTP like the other integrations and logged in `llm_calls` with its cost (operations `embedding` and `rerank`, origin `retrieval` for searches). Without `VOYAGE_API_KEY` the search uses words and names and reports meaning as not used; when the provider fails, the search continues and says so (`degraded`); a failing database fails the search. Search is served at `POST /me/memories/search` (the signed-in user's store), at `POST /memories/search` (the console, the operator's store), and to Cooper as the `search_memories` tool in chats and scheduled runs, which returns each memory with its kind, date, review status, and the user's own words, and tells the model to say it does not know rather than guess. Retrieval is measured on 47 questions over the golden dataset (`retrieval_queries.jsonl`; recall, precision and hit at k, MRR, nDCG) by `scripts/run_retrieval_eval.py`.

**Reason:** Each leg finds what the others miss. Names, amounts, and rare tokens ("Context7", "2980") are where embeddings are weakest, and paraphrases are where words fail. Rank fusion combines legs whose scores are not comparable, without calibrating them. Filtering inside each leg means a filter never empties the top of a list and no leg can ever see another owner's memories; loading checks the owner again. An exact scan is exact, needs no tuning, and is fast at one person's scale (thousands of memories); an approximate index with filters can return fewer than k. The space key keeps vectors of different models or dimensions from ever being compared: changing the model means indexing the new space, then pruning the old. Requiring four characters for fuzzy names lets "priyaa" find Priya while "tom" never matches "tomorrow". An OR of terms, unlike `plainto_tsquery`, still finds a memory for a question in plain language. Anthropic offers no embedding model; Voyage is the provider its documentation points to.

**Consequence:** Every database needs pgvector and pg_trgm (revision 009 creates both). Neon provides them; a local Windows PostgreSQL needs `scripts/install_pgvector_windows.ps1`. Semantic search costs one embedding call per search and per changed memory (`voyage-4`: $0.06 per million tokens). The similarity floor and the fusion weights are defaults until the evaluation has run with the real model. `DOCUMENT_VERSION` must be raised whenever the memory document changes; a `verify` pass then re-embeds. Only memories are embedded: details the extractor left out of a memory are not searchable yet (raw-message chunks are future work). Relations and contradictions between memories do not affect ranking yet. Add an HNSW index per space only when measured latency calls for it.

## ADR-039 — Composio auth configs are found or created at connect time, never kept in code

**Date:** 2026-10-24

**Decision:** The app catalog holds no Composio auth config ids. To connect an app, the backend uses the operator's `COMPOSIO_AUTH_CONFIGS` entry for the toolkit, else an auth config the Composio project already has for it, else it creates one with Composio's managed sign-in (`use_composio_managed_auth`). The result is remembered per toolkit for the life of the process, behind one lock per toolkit, so concurrent first connects create one auth config. If Composio says a remembered auth config no longer exists, it is looked up (or created) again once; a missing operator entry is reported by name. When Composio cannot set up managed sign-in for a toolkit, the user sees why and what to do.

**Reason:** Auth config ids belong to one Composio project. The ids ported from the app's earlier TypeScript code belonged to a project whose key is gone, and in the new project all seven returned 404, so every connect would have failed. Resolving at runtime makes any project key work without code changes or dashboard setup, while still letting the operator pin a specific auth config, for example one with their own OAuth app.

**Consequence:** Consent screens of managed sign-in show Composio's name, not the app's; pin an auth config with your own OAuth credentials in `COMPOSIO_AUTH_CONFIGS` to change that. The first connect of each app creates an auth config in the Composio project. Two API processes may each create one at the same moment; both work, and later lookups use whichever Composio lists first.

## ADR-040 — Operator routes answer only the computer running the API

**Date:** 2026-10-24

**Decision:** The memory layer's and console's routes (capture, processing, memories, console, call log, playground, evaluations, reports) accept a request only when it comes from the computer running the API (a loopback address), or carries `OPERATOR_API_KEY` in the `X-Operator-Key` header; anything else gets 403 `OPERATOR_ACCESS_DENIED`. The health checks stay open, and the app's routes keep needing a signed-in user. Replay selects only the operator's own units, even when given app users' run or message ids.

**Reason:** The API listens on the network so the phone can reach the app's routes, and the operator routes have no sign-in (ADR-022). Anyone on the same Wi-Fi could read the operator's memories and evidence, read every user's call records, and replay every unit, including app users', spending model calls on their data and giving them memories nobody asked for. A sign-in for the console would need its frontend rebuilt, which this machine cannot do yet; the loopback rule protects the same routes now, with no change to the console, which runs on the same computer. Behind a reverse proxy on the same machine, Uvicorn takes the client address from the forwarded header, so the rule still sees the real client; a hosted deployment sets the key.

**Consequence:** Open the console at `http://localhost:8000`; the computer's own network address is refused like any other. Aggregate pipeline counts and the call log still cover every owner (no message content); only the operator can now reach them. A real operator sign-in remains the long-term answer once the console can be rebuilt.

## ADR-041 — Scheduled runs never browse, and know the user's connected apps

**Date:** 2026-10-24

**Decision:** Scheduled runs get memory search and the app tools, never the browser. A run that delivers to chat is told the apps the user connected (as last seen, like chat turns), so it can read them; a run that delivers to an app checks that app live with Composio, as before. Scheduled runs get their own app instructions: no Connect links, and no waiting for a confirmation nobody can give.

**Reason:** ADR-029 limits a scheduled run to changing data in the app it delivers to. App actions are classified, but a browser task is free-form instructions to a browser agent, so nothing can tell reading a page from submitting a form or booking: the rule could not hold for it. Separately, chat-delivered runs were told "Connected apps: none", so the most common schedule ("summarize my unread email every morning") would answer that it cannot reach the user's email.

**Consequence:** "Check this page every day" cannot be scheduled until a browser mode exists that is read-only by construction. Assistant prompt version 1.3.

## ADR-042 — Push registration follows the signed-in user

**Date:** 2026-10-24

**Decision:** After every sign-in, and at launch with a saved session, the app registers the device's push token for that user: silently when notification permission exists, and with one permission prompt when the user has notifications on and was never asked. Signing out unregisters the token first (best effort, five seconds); deleting the account only forgets it locally, since the backend already removed it. The app remembers its token to unregister it.

**Reason:** Registration used to happen only when the user switched notifications from off to on, and the setting starts on, so no device was ever registered. Tokens were also never unregistered: a shared phone kept receiving the previous user's results, and the backend gives a token to whoever registered it last, so registering on every sign-in also takes it over.

**Consequence:** Push still needs an EAS project id (`eas init`) and a development build; until then the code does nothing in Expo Go. A sign-out the server forces (a rejected session) cannot unregister; the next sign-in on the phone takes the token over.

## ADR-043 — Scheduling v2: more rules, editing, deleting, and skipping late slots

**Date:** 2026-10-24

**Decision:**
- A schedule's rule is a wall-clock time in its timezone with one of five frequencies:
  - `once` on a date;
  - `daily`;
  - `weekly` on one or more weekdays (Monday to Friday is "weekdays");
  - `monthly` on a day of the month, where a shorter month runs on its last day;
  - `interval`, every 1 to 24 hours from a first run on a start date. This counts real elapsed time, so it shifts on the clock at a daylight-saving change.
- Columns (revision 010): `weekdays` (an array, replacing `weekday`), `day_of_month`, `start_date`, and `interval_hours`. Check constraints keep each frequency's fields present and the others empty.
- A one-time schedule becomes `completed` once its slot is claimed.
- `PATCH /schedules/{id}` edits title, task, rule, timezone, delivery, and status. Only the fields sent change; when the frequency changes, fields the new one doesn't use are dropped. A changed rule moves the next run to its first slot after now. Editing a completed one-time schedule to a future time makes it active again.
- `DELETE /schedules/{id}` removes a schedule and its run history, refused while a run is going. Results already posted stay in chat.
- A slot more than `SCHEDULE_MISSED_GRACE_SECONDS` late (an hour; at most half an interval's period) is skipped, not run. So is a slot due while an earlier run of the task is still going. Each skip is recorded as a run with status `skipped` and the reason; skips are not counted as runs and don't appear in the Feed.
- Results can go only to chat or to an app the user has connected (as last seen). This is checked when a schedule is created, edited, proposed by Cooper, or confirmed, and again live when a run starts.
- Responses carry `next_run_local` (the next run in the schedule's timezone), so the app never converts between zones.
- Cooper is told which frequencies exist (assistant prompt version 1.4).

**Reason:** Daily and single-day weekly could not express reminders, weekdays, or monthly tasks, so Cooper would turn them into the wrong daily schedule. A schedule that can't be edited has to be cancelled and proposed again. A run four days late is useless, but running it silently was worse than saying it was missed. A slot dropped during a manual run left no trace. Offering apps that aren't connected only produced runs that failed later.

**Consequence:**
- Proposals stored before this revision name a single `weekday`; they are still read and confirmed.
- Interval schedules spend one daily prompt per run, so every hour uses 24 of the 40.
- Skipped slots are visible only in a schedule's history.
- There are still no end dates, run counts, yearly or sub-hour rules, or per-run retries.

## ADR-044 — Memories the user manages: review, correction, history, privacy, export

**Date:** 2026-10-24

**Decision:**
- Every change a user makes to a memory is recorded in its history (`memory_events`, revision 011) in the same transaction: created, accepted, retracted, restored, edited, corrected, superseded, merged, replaced, suggestion dismissed. History is deleted with its memory.
- `memories.created_by` says who wrote the text: `pipeline` or `user`.
- Lifecycle: the pipeline saves `proposed`; the user accepts (`active`), retracts as wrong (`retracted`, kept, never used), or restores (back to `active`). Superseded memories are history and can only be deleted.
- Correcting the text never rewrites a memory. It creates a new `active` version written by the user that supersedes the old one (`supersedes_memory_id`) and keeps its evidence and entities. Amounts and dates read from the old text are dropped because they described it. Kind and sensitivity change in place.
- Merging a duplicate gives the kept memory the duplicate's evidence; replacing an out-of-date memory does not. In both cases the other memory becomes `superseded`, a `supersedes` relation records which memory replaced it, and the kept one becomes `active`.
- Deleting a memory deletes it with everything it replaced (older versions, merged and replaced memories), their history and their embeddings. The source messages stay: they belong to the chat.
- Deleting a chat keeps its memories (the owner's choice). A source links to its chat only while the chat exists.
- Suggestions come without any model. Text similarity is pg_trgm (`%` with a trigram index on `normalized_content`). Meaning is cosine similarity between current embeddings: the 200 newest memories against their 3 nearest neighbours.
  - A duplicate is one kind of memory with near-identical text or meaning (trigram ≥ 0.8 or cosine ≥ 0.93) and the same numbers.
  - A conflict is related memories (trigram ≥ 0.35 or cosine ≥ 0.80) that share an entity, or near-identical memories with different numbers ("owes me 500" and "owes me 700").
  - Dismissed pairs are recorded in history and not suggested again.
- Held-back runs (`needs_review`: the extractor abstained or its answer was unusable) appear in the owner's review inbox. Saving a memory from one creates a user-written memory resting on the run's messages. Its `memory_sources.extraction_result_id` is empty: the user, not an extraction, made the link. A partial unique index keeps those sources unique. Saving or dismissing marks the run `reviewed` (a new run event); the run itself is unchanged.
- People: renaming keeps the old name as a merged alias entity, so later messages that use it still resolve to the same entity. Merging moves memory links, mentions and earlier aliases to the kept entity. Both mark the memories that mention the entity as changed, so their embeddings are rebuilt.
- Sensitive memories (`metadata.sensitivity`) are shown to their owner with a lock and never given to a model. Cooper's search and scheduled runs leave them out (`RetrievalFilters.include_sensitive` defaults to false). The indexer never embeds them, marking a memory sensitive deletes its embeddings at once, the reranker never sees them, and revision 011 deleted the existing ones. The owner's own search includes them.
- Search returns the same text only once.
- The API retries failed and interrupted memory saves itself (`PipelineLoop`, every `PIPELINE_WORKER_INTERVAL_SECONDS`, when an extractor is configured).
- `GET /me/export` returns everything held for the user as one JSON attachment: account, memories with evidence and history (sensitive ones included and marked), people, chats, schedules with runs, connected apps without credentials, and usage.

**Reason:** Phase 3 and the privacy gaps. Memories nobody could correct, merge, or delete made the store untrustworthy. Deleting a memory or getting a copy of one's data were basic rights the app lacked. Sensitive content had no special treatment, even though the extractor already labelled it. Failed saves waited for a script nobody ran.

**Consequence:**
- A correction changes a memory's id; the app follows `id` in the response.
- Suggestions are heuristics: they miss contradictions phrased differently ("moved to Mumbai" against "lives in Pune" with no shared entity) and need embeddings to see paraphrases. A model-based contradiction check is possible later.
- Sensitive memories cannot be found by meaning, even by their owner, since they have no embedding.
- Retention (automatic deletion after a period) is not decided.

## ADR-045 — Life state, reminders, the daily brief, and searching chats

**Date:** 2026-10-25

**Decision:**
- An *open item* is a live memory of an actionable kind that has not been closed:
  - a task, commitment, open loop, plan, or intention with state open or planned;
  - or a goal or project not done.
- Revision 012 adds to memories `due_on` (the extractor's resolved date at build time, or the user's choice), `remind_at`, and `closed_at` with `close_reason` (`done` or `dropped`). Open items that already had a resolved date were backfilled.
- `GET /me/life` groups open items by when they are due, in the user's timezone: overdue, today, the next seven days, later, and no date. Goals and projects are listed apart. It also returns items gone quiet (untouched for 14 days and not due in the future), pending reminders, and what was done in the last seven days.
- Items are completed, dropped, reopened, or rescheduled from the app, from chat cards, or by Cooper. Each change is recorded in the memory's history (new actions `completed`, `dropped`, `reopened`, `scheduled`, `reminded`). Completing a proposed memory accepts it.
- `app_users` stores the user's timezone (the app reports it after each sign-in), brief preferences, a reminders switch, and quiet hours.
- A proactive loop in the API (`PROACTIVE_ENABLED`, every `PROACTIVE_POLL_SECONDS`) does two jobs:
  - It sends due reminders, each claimed with `FOR UPDATE SKIP LOCKED`, recorded, and posted to the main chat with a Done/Snooze card, then pushed.
  - It sends daily briefs. Each local day is claimed by a conditional update of `last_brief_on`, so one brief goes per day whatever the number of processes. The brief is posted with a card offering Done and Not yet for items that were due yesterday, then pushed.
- The brief is composed from the life state without any model, so it costs nothing and does not count against the prompt limit. A slot found more than three hours late is skipped, and a day with nothing to say is claimed but not sent.
- Privacy: anything posted to chat (the brief, a reminder) leaves out sensitive memories or their text, because chat history is sent to Cooper on the next turn. A sensitive reminder says only that a private reminder is due.
- Quiet hours silence only the brief's push; the message still appears in chat. Reminders the user set always push, unless reminders or notifications are switched off.
- Cooper gets three tools (prompt version 1.5):
  - `create_reminder`: a task memory written by the assistant (`created_by = assistant`) with a reminder and no confirmation card;
  - `list_open_items`: never lists sensitive items, and is also available in scheduled runs;
  - `update_open_item`: done, drop, reopen, or snooze.
- `POST /me/messages/search` searches the user's own chats with full-text search. `chat_messages.search_document` is a generated `tsvector` with a GIN index. Snippets come from `ts_headline`, with matches between `<<` and `>>`.

**Reason:** Phases 4 and 6 of the roadmap. Memories held tasks and dates but nothing acted on them: nobody was reminded, and nothing asked whether a task was done. A brief written by a model would cost a prompt every day for text a template writes as well, and a model could be wrong about what is due.

**Consequence:**
- A reminder created by Cooper and the task the extractor makes from the same message can both appear. The duplicate suggestion offers to merge them.
- Reminders run at most `PROACTIVE_POLL_SECONDS` late (60 s by default).
- Snoozing a done item reopens it.
- There are no recurring to-dos (schedules cover recurring work) and no per-item notification choices.

## ADR-046 — Insights from memories, without a model, and feedback on them

**Date:** 2026-10-25

**Decision:**
- `GET /me/insights` computes insights on request from the user's own memories (`app.domain.insights`), with no model call and nothing stored. There are six kinds:
  - `money`: amounts noted this month by category against last month, per currency;
  - `people.top`: most mentioned in the last 30 days;
  - `people.quiet`: mentioned at least three times before, not in 30 days;
  - `follow_through`: done, dropped, and overdue over 30 days, with the run of days on which something was finished;
  - `goal.quiet`: an open goal or project untouched for 30 days;
  - `theme`: a topic, project, or concept mentioned at least three times this week.
- Every insight names the memories it rests on and what opening it shows (a person, a memory, the to-do list). Its key includes its period (`money:2026-10:INR`, `people.quiet:<id>:2026-10`).
- `POST /me/insights/feedback` records useful or not useful per user and key (`insight_feedback`, revision 013, deleted with the user). A later answer replaces an earlier one. *Not useful* hides that insight for its period only.
- `GET /console/insights/usefulness` (operator only) counts the answers per kind: the usefulness metric of Phase 7.
- On Mondays the daily brief adds how many items were done in the past seven days.
- Insights are shown only to their owner, in the Feed, which never reaches Cooper, so sensitive memories count like any other.

**Reason:** Phase 7 asks for grounded suggestions and a way to learn which ones help. Each of these needs only a count over the user's own records, which a query does exactly and for free. A model would cost money, could state a total wrongly, and could not show its evidence any better.

**Consequence:**
- The insights are simple: there are no causal claims and no predictions.
- Money totals add up whatever the extractor read as amounts. They do not say who paid or owes whom, because the extraction contract does not record a direction.
- A model-written weekly reflection is possible later as an opt-in. It would use a prompt and should report its sources the same way.

## ADR-047 — New memory sources: WhatsApp imports, photos and PDFs, the calendar

**Date:** 2026-10-25

**Decision:**
- **WhatsApp imports** happen in two steps, so nothing is spent before the user has seen the cost.
  1. `POST /me/imports/whatsapp` reads an export: the `.txt`, or the `.zip` WhatsApp makes, up to 10 MB. Parsing is in `app.domain.whatsapp`:
     - Android and iOS line formats, including continued lines;
     - day/month order inferred from the dates, with day first when every date is ambiguous;
     - media placeholders and system lines skipped.

     The text is kept with the participants (messages and conversations each) and the price of one extraction. Revision 014 adds `chat_imports`; the same file gives the same import.
  2. `POST /me/imports/{id}/start` takes which participant is the user, an optional start date, whether to keep only the conversations they took part in, and a cap (default 200, at most 300, most recent kept). Each conversation becomes one unit of the user's evidence:
     - a conversation is messages less than 30 minutes apart, at most 20 per unit;
     - each message is written `Me: …` or `Priya: …` so the extractor knows who spoke;
     - the source is `whatsapp_import`, with idempotent message ids.

     The pipeline loop extracts the units in the background. Ingestion runs before the import is marked queued, so a failure halfway can be started again. The export's text is then dropped; the raw messages hold it.
- **Photos and PDFs:** `POST /me/memories/from-file` (JPEG, PNG, GIF, WebP, or PDF up to 5 MB) works like this:
  - Claude transcribes the file (operation `transcription`, origin `capture`, counted as one of the day's prompts). It writes the text and a short description of anything else, and is told to add nothing.
  - The result is stored as evidence (`file_upload`) and extracted in the background. The file itself is not kept.
  - The same file again (by hash) is not read again.
- **The calendar as a source:**
  - Turning it on (`PATCH /me/sources/googlecalendar`, from the Google Calendar sheet in Tools) syncs at once. After that `SourceSyncLoop` syncs every `SOURCE_SYNC_INTERVAL_SECONDS` (6 h).
  - A sync reads the next 14 days of events through Composio (`GOOGLECALENDAR_EVENTS_LIST`, parsed tolerantly).
  - Each event becomes an accepted plan memory, `created_by = app`, due on its local day, with no model involved. A changed event updates its memory in place and records it in the history.
  - `synced_items` maps each event to its memory. A memory the user deleted is not brought back.
  - A failed sync is recorded on the connection (`sync_error`) and shown to the user.

**Reason:** Phase 8 of the roadmap. Chat history and documents hold most of what a person would want remembered. A two-step import keeps the cost a deliberate choice, because every conversation is a model call. Calendar events are already structured, so mapping them needs no model.

**Consequence:**
- An import of 200 conversations is about 200 extractions. They take a while (10 per pipeline pass every 30 s) and cost what the estimate says.
- Messages from others are evidence only, as context for what the user said.
- Only the primary calendar, and only Google Calendar, is a source. Gmail is not: it is too high-volume and private for automatic memories.
- Recurring events appear once per occurrence in the window. Events deleted in the calendar are not removed from memories.
