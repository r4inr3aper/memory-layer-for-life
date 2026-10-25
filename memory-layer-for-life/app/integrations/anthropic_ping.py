"""A minimal call that proves the provider can be reached and the account can pay.

It is the cheapest way to answer "would a real call work right now?". It costs a few
tokens, and like every other call it goes through the observer and into the call log.
"""

from typing import Final

import anthropic

from app.domain.enums import LlmOperation
from app.domain.errors import DomainError, ProviderNotConfiguredError
from app.integrations.anthropic_calls import PROVIDER_NAME, AnthropicCallObserver
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.anthropic_errors import describe_provider_failure
from app.integrations.llm_calls import LlmCallSpec

_PROMPT: Final = "Reply with the single word: ok"
_EFFORT: Final = "low"
# Thinking is on by default and counts toward the limit, so a one-word reply still needs
# room.
_MAX_TOKENS: Final = 1024


class ProviderCheckError(DomainError):
    """The provider did not answer the connection check."""

    code = "PROVIDER_CHECK_FAILED"


class ProviderBillingError(ProviderCheckError):
    """The provider answered that the account cannot pay for calls."""

    code = "PROVIDER_BILLING"


class AnthropicConnectionCheck:
    def __init__(
        self, anthropic_manager: AnthropicClientManager, observer: AnthropicCallObserver
    ) -> None:
        self._anthropic_manager = anthropic_manager
        self._observer = observer

    async def run(self, model: str) -> None:
        """Make one tiny call to ``model``.

        Raises ``ProviderNotConfiguredError`` when there is no API key, and
        ``ProviderCheckError`` when the call fails.
        """
        client = self._anthropic_manager.client
        if client is None:
            raise ProviderNotConfiguredError

        spec = LlmCallSpec(
            provider=PROVIDER_NAME,
            operation=LlmOperation.CONNECTION_CHECK,
            requested_model=model,
            effort=_EFFORT,
            max_tokens=_MAX_TOKENS,
        )
        async with self._observer.observe(spec) as call:
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=_MAX_TOKENS,
                    messages=[{"role": "user", "content": _PROMPT}],
                    output_config={"effort": _EFFORT},
                )
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
                failure = describe_provider_failure(error, model=model)
                if failure.billing:
                    raise ProviderBillingError(failure.message) from error
                raise ProviderCheckError(failure.message) from error
            call.answered(response)
            if response.stop_reason == "refusal":
                raise ProviderCheckError("The model declined the connection check.")
