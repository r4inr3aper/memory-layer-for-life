# Retrieval, Embeddings, and Vector Search

## Goal

Let the system retrieve relevant past context using exact terms, structured filters, relationships, and semantic similarity. Vector search is one retrieval mechanism, not the source of truth.

## What is built (2026-10-24)

The guidance below still holds; this is how it was applied. The decision and its reasons are ADR-038.

- **Engine:** `app/services/retrieval/engine.py`. Three legs, each filtered by owner, status, kind, time, expiry, and supersession inside its own SQL (`app/repositories/retrieval_repository.py`):
  - **Words:** full-text search over the generated `memories.search_document`, English stems and exact words.
  - **Names:** linked entities, by phrase or close spelling, using pg_trgm.
  - **Meaning:** cosine over pgvector, an exact scan.

  Rankings are fused by reciprocal rank fusion (`app/domain/retrieval.py`), optionally reranked, then loaded with sources and entities. Every result says which legs found it, at what rank and score.
- **Embeddings:** `memory_embeddings`, one row per memory and embedding space (`provider/model/dimensions`), with the SHA-256 and version of the document embedded (`app/services/retrieval/documents.py`). An embedding older than its memory is ignored until refreshed. Vectors of different spaces are never compared.
- **Indexing:** `app/services/retrieval/indexer.py`.
  - The API runs a pass every 15 seconds. Each pass covers memories that are new or changed, groups them into one provider call per owner, and skips any whose document hash still matches.
  - `scripts/index_memories.py --mode changed|verify|rebuild`, `--prune-other-spaces`, `--status`.
- **Provider:** Voyage AI (`app/integrations/embeddings/voyage.py`): `voyage-4` at 1024 dimensions, optional `rerank-2.5`. Every call is logged in `llm_calls` with its cost.
  - Without a key, search uses words and names only.
  - When the provider fails, search continues and reports `degraded`.
- **Access:**
  - `POST /me/memories/search` searches the user's store.
  - `POST /memories/search` searches the operator's store.
  - Cooper has a `search_memories` tool.
- **Evaluation:** `retrieval_queries.jsonl` holds 47 questions over the golden dataset in five categories: keyword, entity, paraphrase, mixed, and negative. `scripts/run_retrieval_eval.py` scores them with recall, precision and hit at 1/3/5/10, MRR, and nDCG.
- **Not built yet:**
  - raw-message chunks;
  - relation traversal;
  - contradictions in ranking;
  - an approximate (HNSW) index.

## Initial recommendation

Use PostgreSQL plus pgvector first. Keep canonical memories, sources, entities, statuses, and timestamps in relational tables. Embeddings are derived indexes that can be regenerated.

Do not introduce a separate vector database until measured workload, latency, scale, isolation, or operational needs justify it.

## What to embed

Likely retrieval sources:
1. Structured memory text — concise normalized knowledge, decisions, preferences, project context.
2. Raw message/document chunks — original details, discussion context, and information omitted by extraction.

These serve different purposes. A long document should usually be chunked. Keep a source link, chunk order/location, and original artifact metadata.

## Embedding records

A `memory_embeddings` table can include:
- UUID primary key.
- FK to `memories`.
- Vector column with dimension matching the configured model.
- Exact embedding model/version/config identifier.
- Hash of the exact text embedded.
- Created timestamp.

For raw document retrieval, create a `document_chunks` table and reference chunks explicitly. Avoid generic polymorphic source IDs without an integrity plan.

Uniqueness should account for memory ID + model/version + content hash or an equivalent explicit embedding identity. Do not assume one embedding per memory forever.

## Query flow

1. Validate and normalize the user query.
2. Generate query embedding using the compatible embedding model.
3. Retrieve vector candidates with appropriate filters.
4. Optionally retrieve exact keyword matches and relational candidates.
5. Combine/rerank candidates if justified.
6. Fetch authoritative memory/source/entity records from PostgreSQL.
7. Apply status, temporal, and access filters.
8. Return snippets with provenance and explainable source links.
9. Only then pass grounded context to an LLM for answer synthesis.

Vector similarity does not establish truth. Retrieval must respect memory status, source provenance, contradictions, time, and permissions.

## Hybrid retrieval

Combine:
- Exact/keyword search for names, URLs, IDs, rare terms, and exact phrases.
- Vector search for conceptual similarity and paraphrases.
- SQL filters for time, status, memory type, entity, project, and source.
- Relationship traversal for connected memories.

Evaluate retrieval with realistic queries and expected relevant records. Measure recall@k, ranking quality, latency, and irrelevant results. Add approximate indexes such as HNSW when justified by volume and benchmarks.

## Model changes and re-embedding

Record model/version and text hash. If text changes or the embedding model changes, identify stale vectors and regenerate them safely. Avoid mixing incompatible dimensions/models in the same index/query path. Keep canonical content independent of provider-specific embedding representation.
