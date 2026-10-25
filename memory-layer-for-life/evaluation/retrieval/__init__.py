"""Evaluation of memory retrieval against questions about the golden dataset.

The store is the golden dataset's own memories, built by the real pipeline with the
fixture extractor (no model). The questions (``retrieval_queries.jsonl``) name the golden
memories that answer them. Two layers, as for extraction:

1. Deterministic: words and names only, or a fake embedder. These run in the tests
   (``tests/integration/test_retrieval_golden.py``) and never call a provider.
2. Model quality: the configured embedding model and reranker, run on demand with
   ``scripts/run_retrieval_eval.py``. That calls Voyage AI and costs money.
"""
