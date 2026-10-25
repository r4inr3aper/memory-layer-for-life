"""The model catalog: prices, lookup, and which models have a refusal fallback."""

from decimal import Decimal

from app.domain.model_catalog import (
    MODEL_CATALOG,
    estimate_cost_usd,
    find_model,
    selectable_models,
    supports_refusal_fallback,
)
from app.integrations.extraction.base import ExtractionUsage


def test_every_entry_has_consistent_prices() -> None:
    for spec in MODEL_CATALOG:
        assert spec.prices.input > 0
        if spec.prices.output == 0:
            # Embedding and reranking models bill their input only.
            assert spec.prices.cache_write == spec.prices.cache_read == 0
            continue
        assert spec.prices.output > spec.prices.input
        # Writing to the cache costs more than a plain token; reading it costs less.
        assert spec.prices.cache_write > spec.prices.input > spec.prices.cache_read


def test_voyage_models_are_priced_per_input_token_and_never_offered() -> None:
    usage = ExtractionUsage(input_tokens=1_000_000, output_tokens=0)

    assert estimate_cost_usd("voyage-4", usage) == Decimal("0.06")
    assert estimate_cost_usd("voyage-4-lite", usage) == Decimal("0.02")
    assert estimate_cost_usd("voyage-4-large", usage) == Decimal("0.12")
    assert estimate_cost_usd("rerank-2.5-lite", usage) == Decimal("0.02")
    # "voyage-4" is a prefix of "voyage-4-lite" but must not win for it.
    assert find_model("voyage-4-lite").id == "voyage-4-lite"  # type: ignore[union-attr]
    assert find_model("voyage-4").id == "voyage-4"  # type: ignore[union-attr]
    assert not any(spec.id.startswith(("voyage", "rerank")) for spec in selectable_models())


def test_lookup_accepts_dated_ids_and_prefers_the_longest_match() -> None:
    assert find_model("claude-sonnet-5-5").id == "claude-sonnet-5-5"  # type: ignore[union-attr]
    assert find_model("claude-sonnet-5-5-20260801").id == "claude-sonnet-5-5"  # type: ignore[union-attr]
    # "claude-sonnet-5" is a prefix of "claude-sonnet-5-5" but must not win for it.
    assert find_model("claude-sonnet-5").id == "claude-sonnet-5"  # type: ignore[union-attr]
    assert find_model("claude-sonnet-5-20260401").id == "claude-sonnet-5"  # type: ignore[union-attr]
    assert find_model("claude-sonnet-55") is None
    assert find_model("some-other-model") is None
    assert find_model("") is None
    assert find_model(None) is None


def test_only_offered_models_are_selectable() -> None:
    assert [spec.id for spec in selectable_models()] == [
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]


def test_refusal_fallback_is_only_claimed_for_models_that_have_one() -> None:
    assert supports_refusal_fallback("claude-sonnet-5-5") is True
    assert supports_refusal_fallback("claude-opus-5-5-20260901") is True
    assert supports_refusal_fallback("claude-haiku-5-5") is False
    # An unknown model is never sent a parameter it might reject.
    assert supports_refusal_fallback("some-other-model") is False
    assert supports_refusal_fallback(None) is False


def test_cost_charges_each_kind_of_token_at_its_own_rate() -> None:
    usage = ExtractionUsage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_input_tokens=2_000_000,
        cache_creation_input_tokens=400_000,
    )

    # Sonnet 5.5: 1M at $2, 0.1M at $10, 2M cache reads at $0.10, 0.4M cache writes at $2.50.
    assert estimate_cost_usd("claude-sonnet-5-5", usage) == Decimal("4.200000")
    assert estimate_cost_usd("some-other-model", usage) is None
    assert estimate_cost_usd(None, usage) is None


def test_cost_is_kept_to_a_millionth_of_a_dollar() -> None:
    # A typical Haiku extraction call: a cached prompt, a short note, a short answer.
    usage = ExtractionUsage(input_tokens=149, output_tokens=726, cache_read_input_tokens=6776)

    assert estimate_cost_usd("claude-haiku-5-5", usage) == Decimal("0.000446")


def test_haiku_is_priced_higher_once_the_prompt_passes_100k_tokens() -> None:
    at_limit = ExtractionUsage(input_tokens=100_000)
    over_limit = ExtractionUsage(input_tokens=100_001)
    # Cache reads are part of the prompt, so they count toward the threshold.
    over_limit_by_cache = ExtractionUsage(input_tokens=1, cache_read_input_tokens=100_000)

    assert estimate_cost_usd("claude-haiku-5-5", at_limit) == Decimal("0.010000")
    assert estimate_cost_usd("claude-haiku-5-5", over_limit) == Decimal("0.050001")
    assert estimate_cost_usd("claude-haiku-5-5", over_limit_by_cache) == Decimal("0.005001")


def test_summed_usage_is_priced_at_the_standard_rate() -> None:
    """Totals over many calls say nothing about the size of any one prompt."""
    summed = ExtractionUsage(input_tokens=1_000_000)

    assert estimate_cost_usd("claude-haiku-5-5", summed) == Decimal("0.500000")
    assert estimate_cost_usd("claude-haiku-5-5", summed, aggregate=True) == Decimal("0.100000")
