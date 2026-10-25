# Evaluation and Golden Dataset

## Purpose

The WhatsApp-derived dataset (previously discussed as `golden.jsonl`) should become a regression baseline for extraction and memory behavior. Inspect the actual file before assuming its fields, completeness, or correctness.

A golden dataset is not automatically ground truth. Review labels, record ambiguities, and version the dataset/schema.

## Separate evaluation layers

### 1. Deterministic engineering tests
No live LLM required:
- Pydantic contract validation.
- Idempotency and uniqueness.
- Replay behavior.
- Transaction and recovery behavior.
- Entity resolution edge cases using fixed fixtures.
- Provenance integrity.
- Memory status transitions.
- Temporal parsing utilities where deterministic.

### 2. Extraction contract tests
Use fixed model responses/fixtures to ensure:
- Valid outputs persist.
- Invalid outputs are rejected safely.
- Unknown fields and invalid enums fail validation.
- Zero/multiple memories are supported.
- Evidence references are preserved.
- Intentions aren't converted to completed tasks.
- Missing deadlines aren't fabricated.

### 3. Model-quality evaluations
Run controlled model calls on reviewed examples, versioned by model, prompt, and schema. Track quality and cost separately from deterministic CI.

## Suggested metrics

- Schema-valid output rate.
- Extraction precision/recall by memory type.
- Source-grounded claim rate.
- Unsupported/invented claim rate.
- Entity-resolution precision, especially false merges.
- Duplicate memory rate after replay.
- Provenance coverage.
- Conflict handling quality.
- Retrieval recall@k and ranking quality in retrieval phase.
- Processing latency, failure rate, retries, and cost per source message.

## Golden example format

Define a versioned format only after inspecting the current data. A future example may include:
- Stable example ID.
- Source message/input.
- Expected memory candidates/types.
- Expected entity mentions/resolution where known.
- Evidence spans or source references.
- Ambiguity/uncertainty notes.
- Reviewed status and schema version.

Avoid requiring exact natural-language output matching if equivalent grounded outputs are valid. Compare normalized structured fields and human-reviewed quality criteria.

## Regression policy

- Run deterministic checks on every relevant change.
- Run model evaluations when prompts/models/schema change.
- Compare results against the previous version.
- Keep known failures and edge cases.
- Never “fix” an evaluation by weakening expected outputs without review.
- Preserve dataset provenance and avoid unnecessarily exposing personal data in logs or external services.
