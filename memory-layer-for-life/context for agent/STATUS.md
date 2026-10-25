# Implementation Status

> Keep this file factual. Update it after meaningful work. Documentation of an intended feature is not evidence that it is implemented.

Last updated: 2026-10-24.

## Phase status

| Phase | Status | Evidence / notes |
|---|---|---|
| Phase 0: Backend foundation | Done, verified | FastAPI app, settings, database lifecycle, one Anthropic client per process, schema, migrations, health endpoints. Its defects were found and fixed during Phase 1 (`PHASE1_REPORT.md`, section 11.1). |
| Phase 1: Ingestion pipeline | Done, verified by tests. Model quality measured, not perfect | Capture, extraction, entity resolution, memory building, provenance, retries, replay, idempotency. Best live score: 122 of 124 golden cases with Sonnet 5.5, 120 with Haiku 5.5. Full account in `PHASE1_REPORT.md`. |
| Call log and test console | Done, verified by tests and with a scripted model. Not yet used with a real model call | Table `llm_calls`, stored evaluations, single test calls, web console served at `/`. Decisions in ADR-024 and ADR-025. |
| Assistant app backend | Done, verified by tests and a startup smoke test; migrated on the Neon database (revision 009). Sign-in and chat used from the app on a phone. Not yet exercised with a real Composio, Browserbase, or Expo push call | Supabase sign-in (JWKS), chat with a streamed tool-use loop on Claude and attached images/PDFs, a cross-process reply lease, schedule proposals and schedules from a form, a PostgreSQL-claimed scheduler, an activity feed, Composio app connections, Browserbase browser tasks, a daily prompt limit (40 by default) counted in `daily_usage`, a usage meter, assistant personalization, feedback, account deletion, Expo push notifications, chats captured as memories owned by each user (`GET /me/memories`), row level security on every table. Revisions 004 to 008. Decisions in ADR-026 to ADR-037. The mobile app in the parent folder uses it. |
| Phase 2: Retrieval and vectors | Implemented and statically checked (ruff, strict mypy); tests written, not yet run. Migrated on Neon (revision 009); the API runs with Voyage configured | Hybrid search over memories: words (full-text), names (entities, typo-tolerant), and meaning (pgvector, Voyage `voyage-4`), fused by rank, optional reranking, evidence on every result. Indexer loop and script, `POST /me/memories/search`, `POST /memories/search`, Cooper's `search_memories` tool, a 47-question retrieval evaluation. Revision 009. Decision in ADR-038. |
| Phase 3: Memory management | Done, verified by tests (2026-10-24). Revision 011 not yet on Neon | History of every change (`memory_events`), accept / retract / restore, corrections as new versions, kind and sensitivity edits, delete with older versions, merge and replace, duplicate and conflict suggestions without a model, held-back review, people rename and merge. ADR-044. |
| Phase 4: Life-state engine | Done, verified by tests (2026-10-25). Revision 012 not yet on Neon | Open items by due date (overdue, today, this week, later, no date), goals, gone-quiet items, done/drop/reopen, due dates and reminders, Cooper's list tools. ADR-045. |
| Phase 5: API/UI integration | Done in the app, except an operator sign-in for the console | Memories screen (All with search and timeline, To review, People), memory detail with evidence and history, person screen, editor, data export in Settings. |
| Phase 6: Planning/notifications | Done, verified by tests (2026-10-25); never used on a phone | Reminders posted to chat and pushed, a daily brief at the user's time with yesterday's items to check off (no model), quiet hours, a reminders switch, the user's timezone. ADR-045. |
| Phase 7: Feedback/proactive intelligence | Done, verified by tests (2026-10-25). Revision 013 not yet on Neon | Insights from memories without a model (money, people on the user's mind or gone quiet, follow-through and streaks, quiet goals, themes), each naming its evidence; feedback per insight; usefulness per kind for the operator; a weekly line in Monday's brief. ADR-046. |
| Phase 8: Integrations/scale | Memory sources done, verified by tests with fakes (2026-10-25); revision 014 not yet on Neon; never used with a real export, file, or calendar | WhatsApp import (preview, then start with a cap and cost estimate), photos and PDFs read by Claude into evidence, Google Calendar events as plans (synced every 6 h). Scale work (queues, workers) still deferred. ADR-047. |

## Verified commands and results

On 2026-10-25 (Releases 3 and 4, ADR-046 and ADR-047): `pytest tests`: 1,651 passed, 0 failed; ruff, ruff format, and strict mypy (229 files) clean. App: 158 Jest tests, `tsc --noEmit`, ESLint, Android export. Revisions 010 to 014 were applied to the Neon database on 2026-10-25 (`alembic current`: 014, head).

On 2026-10-25 (Release 2, ADR-045): `pytest tests`: 1,605 passed, 0 failed; ruff, ruff format, and strict mypy (213 files) clean. App: 151 Jest tests, `tsc --noEmit`, ESLint, Android export.

On 2026-10-24 (Release 1, ADR-044): `ruff check .`, `ruff format --check .` and strict `mypy` (205 files) clean; `pytest tests`: 1,562 passed and 2 failed in the full run. The 2 failures were then fixed and their files re-run: one golden retrieval test counted the sensitive golden memory as embedded, and one document test depended on set order. App: 141 Jest tests, `tsc --noEmit`, ESLint, and an Android export.

On 2026-10-12, on the development laptop (Windows 11, Python 3.12, portable PostgreSQL 16 for tests):

- `ruff check .`: no findings.
- `mypy` with strict settings: no findings in 118 source files.
- `pytest tests`: 886 passed and 1 skipped in the last full run. The skipped test needs `PHASE1_REPORT.md`; it passed when run alone after that file was written. 887 tests in total: unit 373, contract 16, golden 140, integration 358.
- Coverage: 99 percent (4,844 statements, 22 not covered).
- Migration from an empty database: verified by the integration suite, which builds its database with the real migrations, and by `alembic upgrade head` on the hosted application database, now at revision 003.
- Health endpoints: `GET /api/v1/health/ready` returns 200 with the database connected.
- Console: type check, lint, and 17 unit tests pass, and the build succeeds. These ran with stand-in tools, because part of `frontend/node_modules` is damaged on this laptop (see below).
- Live evaluation: 12 runs on 2026-10-11. Results are in `PHASE1_REPORT.md` and in the database.
- Docker build: not verified. The project is run without Docker here.

On 2026-10-18, on the second development machine (Windows 11, Python 3.12.1, portable PostgreSQL 16):

- `ruff check .` and `ruff format --check .`: no findings.
- `mypy` with strict settings: no findings in 157 source files.
- `pytest tests`: 1202 passed in the last full run (2026-10-24).
- Coverage: 98 percent (7,334 statements, 128 not covered).
- Migrations 004 to 006: verified by the integration suite (built with the real migrations), the schema-drift test, the downgrade test, and a test that every table has row level security and that a role other than the owner sees no rows.
- The real Supabase project's signing keys were fetched with the configured URL, and a forged token using its key id was refused.
- Startup smoke test: the API started with uvicorn and its lifespan, the scheduler loop ran, `/health/ready` answered 200, app routes answered 401 without a valid token, and shutdown was clean.
- `uv.lock`: refreshed for `pyjwt[crypto]`; it adds pyjwt, cryptography, cffi, and pycparser and changes nothing else.
- The copied `.venv` pointed at another machine's Python; `pyvenv.cfg` now points at `C:\Python312` (the original is kept as `pyvenv.cfg.orig`).

## Not verified, or open

- No live model call has been possible since 2026-10-11 19:30 UTC, when the Anthropic credit ran out. The call log holds no real provider call yet.
- The final prompt and judge have one complete evaluation run (Sonnet, 122 of 124). Haiku was not measured on them.
- `task_002` fails in every run because of a label dispute. Labels are the dataset owner's to change.
- All 124 golden cases are unreviewed drafts. `extract` versus `context` is reported and does not gate.
- The refusal fallback has not been seen working against a real refusal.
- `frontend/node_modules` is damaged on the development laptop. A clean `npm install` is needed before the console can be rebuilt with its normal tools. `frontend/dist` is built and works.
- The Docker image has not been rebuilt since the console was added.
- The memory-layer and console routes have no sign-in; since 2026-10-24 they answer only the computer running the API, or a request with `OPERATOR_API_KEY` (ADR-040). The assistant app's routes require a Supabase access token.
- The application database is Neon (the owner's choice). Revisions 004 and 005 were applied to it on 2026-10-18, 006 on 2026-10-19, and 007, 008, and 009 on 2026-10-24; the connecting role owns all tables, so row level security does not restrict the API.
- Assistant app: real chat turns on Claude Haiku 5.5 ran from the app on a phone on 2026-10-18. A Composio project key was set on 2026-10-24 and accepted by Composio (a read-only call); auth configs are now found or created at connect time (ADR-039). Google Calendar was connected from a phone through it, and Cooper created a calendar event (Tool Router search and execute). No Browserbase or Expo push call has been made against the real services; they are tested against mock transports only. The Composio REST paths and the Browserbase agent-run API were ported from the app's previous TypeScript code.
- Supabase admin deletion: the endpoint and key were checked with a random user id (404, which counts as already deleted). No real identity has been deleted.
- Expo push receipts are not checked.
- Sign-in for the memory-layer routes, if they are to be used from the app.
- No WhatsApp export importer.
- The project folder is not a git repository.
- Scheduling v2 on 2026-10-24 (ADR-043, revision 010): one-time, weekday, monthly, and interval schedules; editing and deleting; late and overlapping slots skipped and recorded; delivery only to connected apps. pgvector was installed in the local test PostgreSQL the same day (its headers were missing from the portable install and were added from the same EDB 16.14 archive), so the integration suite runs again: retrieval tests still excluded at the owner's request.
- Fixes on 2026-10-24 (ADR-040 to ADR-042): chat-delivered scheduled runs see connected apps, scheduled runs never browse, operator routes answer only this computer, replay skips app users' units, push follows sign-in. Backend unit and contract tests pass (621, retrieval excluded) and the app's 90 tests pass; the new integration tests (operator access, replay scope, chat-delivered run reading Gmail) are written but cannot run until pgvector is installed locally.
- Retrieval (2026-10-24): the unit, integration, API, and golden-set tests were written but not run, at the owner's request. The integration tests need pgvector in the local test PostgreSQL (`scripts/install_pgvector_windows.ps1`). Revisions 008 and 009 were applied to Neon on 2026-10-24 and the API restarted with a Voyage key; Live use the same day: 5 chat messages captured with 5 real extraction calls (3 memories; 2 abstained), 3 memories embedded by Voyage (`voyage-4`), and 2 searches by Cooper's `search_memories` tool, each finding its memory.

## Known open questions

- Review the golden dataset labels, starting with the cases listed in `PHASE1_REPORT.md`, section 13.
- Inspect the actual WhatsApp export format before building an importer and a rule for grouping messages.
- Measure retrieval with the real embedding model (`scripts/run_retrieval_eval.py --embedder voyage`) and tune the similarity floor and fusion weights on it.
- Define authentication/authorization before exposing personal data beyond a trusted local environment.
- Decide how proposed memories become active and how user corrections are represented.
- Define task/project/goal dedicated schemas when Phase 4 is designed.

## Update rule

For each substantial change, record:
- Date.
- Phase.
- What changed.
- Tests/commands actually run and results.
- What remains unverified.
- Important decision links in `DECISIONS.md`.
