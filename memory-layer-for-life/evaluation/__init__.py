"""Evaluation of the extraction pipeline against the golden dataset.

Three layers are kept apart, as the project's evaluation notes require:

1. Deterministic engineering tests live in ``tests/`` and never call a model.
2. Fixture-driven pipeline tests push every golden case through the real pipeline with
   ``evaluation.fixture_extractor``. They also never call a model.
3. The live model-quality evaluation in ``evaluation.runner`` calls the configured model
   and is run on demand with ``python -m scripts.run_golden_eval``.
"""
