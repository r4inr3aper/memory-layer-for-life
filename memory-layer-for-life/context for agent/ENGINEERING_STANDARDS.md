# Engineering Standards

## General approach

Work like a staff engineer: understand constraints, model the domain, make trade-offs explicit, implement incrementally, and verify outcomes. Prefer boring, dependable technology and readable code over speculative abstractions.

## Python and FastAPI

- Prefer supported Python 3.12+.
- Type public functions and domain boundaries.
- Use Pydantic v2 for external and LLM-generated contracts.
- Use `ConfigDict(extra=\"forbid\")` for controlled structured payloads unless extension is intentional.
- Use explicit response models.
- Keep routers thin and services focused.
- Do not mix API schemas and SQLAlchemy ORM models.
- Do not use `Any` to avoid designing types.
- Avoid broad exception swallowing.

## Database and transactions

- PostgreSQL is canonical state.
- SQLAlchemy 2.0 typed async patterns.
- Alembic is the schema evolution mechanism.
- Use UUIDs, timezone-aware timestamps, UTC persistence, named constraints, and justified indexes.
- Never use `metadata.create_all()` as the production migration strategy.
- Never automatically reset/drop a database.
- Repositories should not commit invisibly. Transaction ownership belongs to a clearly defined unit of work/service.
- Use transactions for logically related writes.
- Choose FK deletion behavior deliberately; preserve historical evidence.
- Use database unique constraints and checks for invariants that must survive concurrent requests.
- PostgreSQL-specific behavior must be tested against PostgreSQL.

## Client and resource lifecycle

- One async SQLAlchemy engine and one session factory per process.
- Fresh `AsyncSession` per request/job/unit of work.
- Never share a live session concurrently.
- One `AsyncOpenAI` client per process, initialized/closed with application lifespan.
- No network calls at import time or startup.
- No new provider client per request.
- Basic liveness/readiness should not call OpenAI.
- Configure timeouts and avoid accidental nested retry multiplication.

## Pydantic and LLM safety

- Treat model output as untrusted external input.
- Validate schema, enums, bounds, temporal fields, and relationships before persistence.
- Version output contracts and extraction implementation.
- Store provider/model version metadata.
- Preserve original source and evidence.
- Represent ambiguity, low confidence, and contradictions explicitly.
- Do not invent deadlines, identity, completion, or facts.
- Avoid storing hidden reasoning or unnecessary provider payloads.
- Do not log full personal messages by default.

## Idempotency, replay, and history

- Source identity differs from processing identity.
- Idempotency enforced at persistence boundary.
- Retries are safe after partial failures.
- Versioned outputs are auditable.
- Replay does not create a new source message.
- New interpretations do not silently overwrite old ones.
- Provenance should survive corrections, supersession, and reprocessing.
- Derived indexes/projections should be rebuildable.

## Testing

- Unit tests for pure logic and schema validation.
- PostgreSQL integration tests for constraints, transactions, JSONB, migrations, and concurrency.
- Contract tests for API request/response shapes.
- Mock OpenAI calls in ordinary CI tests.
- Separate deterministic regression tests from live-model evaluations.
- Add tests with the change; test failure paths as well as happy paths.
- Use a dedicated test database, never the user's real data DB.
- Run tests and report exact outcomes; don't claim unrun tests passed.

## Security and privacy

- Keep secrets in environment/configuration, never committed.
- `.env.example` contains placeholders only.
- Sanitize public errors and operational logs.
- Treat personal messages as sensitive.
- Apply authentication/authorization before exposing data outside a trusted local environment.
- Validate URLs and file inputs if integrations are added.
- External actions require explicit authorization.

## API and developer experience

- Version API routes.
- Use consistent error formats and status codes.
- Paginate collection endpoints.
- Validate filters and sort fields.
- Document setup, migrations, test commands, and architecture.
- Keep local development reproducible with Docker Compose.
- Make startup/shutdown behavior explicit.

## Change workflow

For each substantial change:
1. Inspect current state.
2. Define scope and acceptance criteria.
3. Identify data/API compatibility implications.
4. Implement smallest coherent increment.
5. Add tests.
6. Run formatter/linter/type checks/migrations/tests/build as applicable.
7. Review diffs and constraints.
8. Update docs and `docs/STATUS.md`.
9. Report what was implemented, verified, and deferred.

## Definition of done

Implemented code, migration safety, tests, operational clarity, and documentation—not just a plausible diff.
