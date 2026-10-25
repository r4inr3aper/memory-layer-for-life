# Memory Ingestion Pipeline

## Goal

Implement a robust, replayable, idempotent pipeline:

**Raw Message → Normalize → Extract → Resolve Entities → Construct Memories → Persist Provenance → Update Derived State**

This phase follows the backend foundation. Do not treat the pipeline as a single prompt that writes arbitrary JSON into a table.

## Stage 0: persist source

- Validate source envelope.
- Assign stable source identity where available.
- Persist original content and source metadata before expensive processing.
- Enforce source uniqueness using `(source, source_message_id)` when an external ID exists.
- Do not globally deduplicate identical message text.
- Preserve source timestamps and ingestion time separately.

## Stage 1: normalize

- Produce a normalized working representation without modifying raw evidence.
- Make normalization deterministic and versioned where output affects downstream identity.
- Preserve source-specific metadata and exact original text.
- Do not remove meaningful punctuation, dates, or context without a reason.

## Stage 2: extract

Use a provider-independent extraction interface and strict versioned Pydantic contracts. The extractor may identify:
- Facts and preferences.
- Ideas and decisions.
- Intentions, tasks, explicit commitments, open loops.
- Goals/projects.
- People, organizations, technologies, places, concepts.
- Events, dates, deadlines, temporal context.
- Relations and supporting evidence.

A message can yield zero, one, or multiple items. Some messages need review or are irrelevant.

Requirements:
- Validate all output before persistence.
- Handle invalid JSON/schema, timeouts, rate limits, provider errors, and empty output.
- Store extractor/schema/model version.
- Never assume LLM confidence equals factual certainty.
- Do not invent dates, identity, completion, commitments, or causal links.
- Preserve exact evidence spans when available and reliable.

## Stage 3: resolve entities

- Normalize mentions and compare with canonical entities.
- Reuse an entity only when identity evidence is sufficient.
- Create entities when appropriate.
- Mark unresolved/ambiguous mentions explicitly.
- Preserve original mention text and resolution decision.
- Keep resolution logic separate and testable.
- Make merge/correction auditable.
- Similar names alone do not prove identity.

## Stage 4: construct memories

- Build typed memory candidates from validated extraction and resolved entity references.
- Keep proposed vs active status explicit.
- Attach source provenance and evidence.
- Preserve uncertainty and temporal meaning.
- Handle conflicts explicitly; don't overwrite older evidence.
- Distinguish raw message, extraction output, canonical memory, task, and derived current state.

## Stage 5: persist

- Use explicit transaction boundaries.
- Use foreign keys, unique constraints, and safe upserts.
- Avoid hidden commits in low-level repositories.
- Record stage/run status and sanitized errors.
- Preserve successfully completed work where safe.
- Ensure failed stages never destroy raw messages.

## Idempotency

Idempotency is a database-level property, not just an in-memory guard.

Define separate identities:
- Source identity: identifies the original incoming message.
- Processing identity: identifies processing that source under a particular pipeline/extractor/schema configuration.
- Output identity: identifies the versioned result and its derived records.

Repeated delivery of the same source must not create duplicate source records. Repeated processing of the same logical version must not duplicate memories or relationships. A new extraction version may produce a new historical result, but activation/reconciliation of its output must be explicit.

Use unique constraints, transactions, stable idempotency keys, and concurrency-safe conflict handling. Document key construction and its assumptions. Avoid hashes that unintentionally collapse distinct source messages.

## Replay and versioning

Support:
- Reprocess one message.
- Reprocess a batch.
- Inspect prior runs and failures.
- Retry transient failures with bounded backoff.
- Reuse valid completed stages when compatible.
- Reprocess with a new pipeline/schema/model version.
- Compare versioned outputs where practical.
- Audit which sources/runs produced each memory.

Replay is not a new capture. Do not overwrite the raw source or silently destroy prior outputs. Explicitly define whether a new result becomes proposed, active, superseding, or requires review.

## State and recovery

Track run/stage status using controlled states. Define legal transitions and behavior for:
- queued → running → succeeded.
- running → failed.
- failed → retry/queued.
- successful extraction but failed entity resolution/persistence.
- needs_review for ambiguity or validation concerns.

Use bounded retries for transient failures only. Do not indefinitely retry permanent schema/validation errors. Keep enough diagnostics to debug without logging sensitive content.

## Evaluation

Use the existing WhatsApp-derived golden dataset if present. Inspect its actual format before implementing readers. Separate:
- deterministic schema/idempotency/replay tests.
- fixture-based extraction checks.
- live model-quality evaluations.

Test duplicate ingestion, repeat processing, changed versions, partial failures, concurrency, ambiguous entities, conflicting facts, and provenance. Do not assume existing golden labels are correct without review.
