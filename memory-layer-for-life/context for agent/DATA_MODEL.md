# Data Model and Memory Schema

## Design goals

The schema separates:
1. Immutable source evidence.
2. Versioned extraction interpretations.
3. Entity mentions and canonical entities.
4. Structured memories and their lifecycle.
5. Provenance and relationships.
6. Later derived retrieval indexes.

Use PostgreSQL relational constraints for integrity. Use JSONB only for validated variable attributes, not as a substitute for modeling important relationships.

## Initial tables

### `raw_messages`
Stores original text/content and source metadata.
- UUID `id`.
- `source`.
- Nullable `source_message_id`.
- `content` (original, preserved).
- `content_sha256` (integrity/diagnostic hash; not globally unique).
- Nullable `source_created_at`.
- `ingested_at`.
- JSONB `metadata`.
- `created_at`.
- Unique `(source, source_message_id)`; PostgreSQL permits multiple null IDs.
- Index source/time fields used for import and diagnostics.
- Never deduplicate solely by content hash: identical text can be legitimate separate messages.

### `processing_runs`
Tracks an attempt to process one raw message.
- UUID `id`, FK `raw_message_id`.
- `pipeline_version`, `status`, positive `attempt_number`.
- Unique `idempotency_key` for one logical operation.
- `started_at`, `finished_at`, sanitized `error_code`/`error_message`, JSONB operational metadata, `created_at`.
- Index source, status, creation time.
- Define legal state transitions and retry semantics.

### `extraction_results`
Stores validated, versioned extraction output.
- UUID `id`, FK `processing_run_id`.
- `schema_version`, `extractor_version`, optional actual `model_name`.
- `status`, JSONB `payload`, `created_at`.
- Normally one result per processing run.
- Never store arbitrary unvalidated LLM output as trusted data.

### `entities`
Canonical people, projects, concepts, organizations, technologies, places, etc.
- UUID `id`, `entity_type`, `canonical_name`, `normalized_name`, optional `description`.
- `status` active/merged/archived.
- Optional self-FK `merged_into_id`.
- JSONB `attributes`, `created_at`, `updated_at`.
- Index type and normalized name.
- Do not globally unique normalized names without domain-specific identity proof.
- Prevent self-merge and make merges auditable.

### `entity_mentions`
Stores entity mentions from source/extraction, including unresolved cases.
- UUID `id`, FKs to raw message and extraction result.
- `entity_type`, original `mention_text`, `normalized_mention`.
- Optional `start_offset`/`end_offset`.
- `resolution_status`: unresolved/resolved/ambiguous/rejected.
- Optional `resolved_entity_id`, confidence 0–1, `created_at`.
- Validate offsets and consistency of resolved status/ID.
- Preserve the mention after resolution.
- Define deduplication with extraction identity and occurrence offsets where available.

### `memories`
Common representation for structured knowledge.
- UUID `id`.
- Controlled `memory_type`.
- `content`, optional `normalized_content`.
- `status`: proposed/active/superseded/retracted.
- Optional confidence 0–1.
- Optional `valid_from`, `valid_until`, `observed_at`.
- Optional self-FK `supersedes_memory_id`.
- Validated JSONB `metadata`.
- `created_at`, `updated_at`.
- Keep valid time distinct from ingestion/creation time.
- Do not silently overwrite conflicting facts.
- Avoid treating an intention as a completed task.

### `memory_sources`
Many-to-many provenance.
- UUID `id`.
- FKs `memory_id`, `raw_message_id`, `extraction_result_id`.
- Optional `evidence_text`.
- `source_role`: supporting/contradicting/contextual.
- `created_at`.
- Unique constraint to prevent duplicate associations.
- Index both directions.

### `memory_entities`
Links memories to canonical entities.
- `memory_id`, `entity_id`, validated `relationship_type`, `created_at`.
- Composite PK or unique key including relation type.
- Index both directions.

### `memory_relations`
Typed relationships between memories.
- UUID `id`.
- `source_memory_id`, `target_memory_id`, `relation_type`, optional confidence, `created_at`.
- Prevent self-relations unless specifically justified.
- Unique ordered pair + relation type.
- Index source and target.
- Keep direction explicit.

## Memory taxonomy

Plan to support:
- Episodic.
- Semantic.
- Working/contextual.
- Procedural.
- Preferences.
- Goals.
- Projects.
- Tasks.
- Commitments.
- Social/people.
- Decisions.
- Ideas.
- Financial/transactional.
- Knowledge artifacts.
- Open loops/follow-ups.

A common `memories` table is useful, but not every domain should remain a generic memory forever. Add dedicated relational domain models when behavior requires lifecycle constraints and fields:
- Tasks: status, priority, due date, completion evidence, recurrence.
- Projects/goals: status, milestones, next action, progress history.
- Financial transactions: amount, currency, merchant, transaction time, category, source.
- Notifications: scheduled/delivered/dismissed state and delivery attempts.
- Feedback/outcomes: user corrections, accepted/rejected suggestions, observed results.
- Documents/chunks: document metadata, chunk ordering, source location, artifact references.

Working memory/current life state is often a derived, time-sensitive projection, not a permanent fact. Keep derivation and expiry semantics explicit.

## Temporal modeling

Distinguish:
- `ingested_at`: when system received source.
- `source_created_at`: when source says message was created.
- `observed_at`: when a fact/event was observed.
- `valid_from` / `valid_until`: when the fact is believed to apply.
- `created_at` / `updated_at`: database record lifecycle.

Do not fabricate timestamps or deadlines. Store timezone-aware timestamps and use UTC in persistence.

## Constraints and deletion

- Use UUID PKs and named FK/unique/check constraints.
- Choose FK deletion behavior deliberately.
- Prefer restrictive behavior for source evidence and historical records.
- Avoid cascades that erase memories/runs when a raw message is removed.
- Use database constraints as defense in depth behind Pydantic validation.
- Index actual query patterns; avoid indexing every column by default.
- Use Alembic migrations; do not use `create_all()` as the production migration strategy.

## Vector data (later phase)

Prefer pgvector inside PostgreSQL initially.

Potential `memory_embeddings` fields:
- UUID `id`.
- FK `memory_id` or a clearly typed source reference.
- `embedding` with dimension matching the chosen model.
- `embedding_model` and version/config identifier.
- `content_hash` of the exact embedded text.
- `created_at`.

If embedding raw documents, add a separate `document_chunks` table and link embeddings to chunks. Avoid polymorphic `(source_type, source_id)` references without a deliberate integrity strategy, since a normal FK cannot target multiple tables.

Regenerate embeddings when source text or embedding model changes. Keep vectors as derived/rebuildable data. Add HNSW/IVFFlat indexes only when measured scale and latency justify them.
