"""Models the application knows how to price and how to call.

Prices are list prices in US dollars per million tokens, copied from each provider's
pricing page on the date noted: Anthropic's on ``PRICES_CHECKED_ON``, Voyage AI's on
``VOYAGE_PRICES_CHECKED_ON``. They produce estimates: the invoice is the source of truth.
A model that is not listed still works, but its calls are logged without a cost.

When a price changes, edit the entry and the date. Stored costs are not recomputed: each
logged call keeps the estimate that was true when it was made.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Protocol

PRICES_CHECKED_ON: Final = date(2026, 10, 12)
PRICES_SOURCE: Final = "https://platform.claude.com/docs/en/about-claude/pricing"
VOYAGE_PRICES_CHECKED_ON: Final = date(2026, 10, 24)
VOYAGE_PRICES_SOURCE: Final = "https://docs.voyageai.com/docs/pricing"

_TOKENS_PER_PRICE_UNIT: Final = Decimal(1_000_000)
# Costs are stored to a millionth of a dollar, which resolves a single cheap call.
_COST_QUANTUM: Final = Decimal("0.000001")


class TokenCounts(Protocol):
    """The four token counts a provider bills at different rates."""

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cache_read_input_tokens(self) -> int: ...

    @property
    def cache_creation_input_tokens(self) -> int: ...


@dataclass(frozen=True, slots=True)
class TokenPrices:
    """US dollars per million tokens. ``cache_write`` is the five-minute cache."""

    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


@dataclass(frozen=True, slots=True)
class LongPromptTier:
    """Prices for a request whose whole prompt is larger than ``above_prompt_tokens``."""

    above_prompt_tokens: int
    prices: TokenPrices


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    display_name: str
    prices: TokenPrices
    # Whether the API can re-run a declined request on another model inside the same call.
    supports_refusal_fallback: bool
    # Whether the model is offered as a choice. Models that are only listed so that a call
    # they happened to serve can be priced are not.
    selectable: bool = True
    long_prompt_tier: LongPromptTier | None = None

    def prices_for(self, usage: TokenCounts) -> TokenPrices:
        """The prices one request is billed at. A prompt counts all of its input tokens."""
        tier = self.long_prompt_tier
        if tier is None:
            return self.prices
        prompt_tokens = (
            usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
        )
        return tier.prices if prompt_tokens > tier.above_prompt_tokens else self.prices


def _prices(input: str, output: str, *, cache_write: str, cache_read: str) -> TokenPrices:  # noqa: A002
    return TokenPrices(
        input=Decimal(input),
        output=Decimal(output),
        cache_write=Decimal(cache_write),
        cache_read=Decimal(cache_read),
    )


MODEL_CATALOG: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        id="claude-haiku-5-5",
        display_name="Claude Haiku 5.5",
        prices=_prices("0.10", "0.50", cache_write="0.125", cache_read="0.01"),
        supports_refusal_fallback=False,
        long_prompt_tier=LongPromptTier(
            above_prompt_tokens=100_000,
            prices=_prices("0.50", "2.50", cache_write="0.625", cache_read="0.05"),
        ),
    ),
    ModelSpec(
        id="claude-sonnet-5-5",
        display_name="Claude Sonnet 5.5",
        prices=_prices("2", "10", cache_write="2.50", cache_read="0.10"),
        supports_refusal_fallback=True,
    ),
    ModelSpec(
        id="claude-opus-5-5",
        display_name="Claude Opus 5.5",
        prices=_prices("4", "20", cache_write="5", cache_read="0.20"),
        supports_refusal_fallback=True,
    ),
    # Listed for pricing only: a declined request can be served by one of these.
    ModelSpec(
        id="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        prices=_prices("2", "10", cache_write="2.50", cache_read="0.20"),
        supports_refusal_fallback=True,
        selectable=False,
    ),
    ModelSpec(
        id="claude-opus-5",
        display_name="Claude Opus 5",
        prices=_prices("5", "25", cache_write="6.25", cache_read="0.50"),
        supports_refusal_fallback=True,
        selectable=False,
    ),
    ModelSpec(
        id="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        prices=_prices("5", "25", cache_write="6.25", cache_read="0.50"),
        supports_refusal_fallback=True,
        selectable=False,
    ),
    # Voyage AI embedding and reranking models, for memory retrieval. They bill input
    # tokens only. Listed for pricing; they are never offered for extraction.
    *(
        ModelSpec(
            id=model_id,
            display_name=display_name,
            prices=_prices(price, "0", cache_write="0", cache_read="0"),
            supports_refusal_fallback=False,
            selectable=False,
        )
        for model_id, display_name, price in (
            ("voyage-4-large", "Voyage 4 Large", "0.12"),
            ("voyage-4", "Voyage 4", "0.06"),
            ("voyage-4-lite", "Voyage 4 Lite", "0.02"),
            ("rerank-2.5", "Voyage Rerank 2.5", "0.05"),
            ("rerank-2.5-lite", "Voyage Rerank 2.5 Lite", "0.02"),
        )
    ),
)


def find_model(model_id: str | None) -> ModelSpec | None:
    """Look a model up by id.

    A dated id such as ``claude-sonnet-5-5-20260801`` matches its undated entry. When two
    entries are prefixes of the id, the longer one wins, so ``claude-sonnet-5-5`` is never
    mistaken for ``claude-sonnet-5``.
    """
    if not model_id:
        return None
    candidates = [
        spec for spec in MODEL_CATALOG if model_id == spec.id or model_id.startswith(f"{spec.id}-")
    ]
    return max(candidates, key=lambda spec: len(spec.id), default=None)


def selectable_models() -> tuple[ModelSpec, ...]:
    return tuple(spec for spec in MODEL_CATALOG if spec.selectable)


def supports_refusal_fallback(model_id: str | None) -> bool:
    """False for an unknown model: sending an unsupported parameter fails the call."""
    spec = find_model(model_id)
    return spec is not None and spec.supports_refusal_fallback


def estimate_cost_usd(
    model_id: str | None, usage: TokenCounts, *, aggregate: bool = False
) -> Decimal | None:
    """Estimated cost of a call, or ``None`` when the model's price is not known.

    ``aggregate`` says the counts are sums over many calls. A sum is priced at the
    standard prices, because the size of each single prompt is no longer known.
    """
    spec = find_model(model_id)
    if spec is None:
        return None
    prices = spec.prices if aggregate else spec.prices_for(usage)
    cost = (
        usage.input_tokens * prices.input
        + usage.output_tokens * prices.output
        + usage.cache_creation_input_tokens * prices.cache_write
        + usage.cache_read_input_tokens * prices.cache_read
    ) / _TOKENS_PER_PRICE_UNIT
    return cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP)
