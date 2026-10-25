"""What the application says about a failed Anthropic API call.

Provider error text can quote parts of a request, so it is never copied into stored
errors or logs. A failure is described here in the application's own words, from the
kind of error and its status code.

An account that cannot pay is named explicitly. Every call fails until the owner acts,
so the stored error has to say what is wrong, and this module recognizes that case
without passing provider text on.
"""

from dataclasses import dataclass
from typing import Final

import anthropic

BILLING_FAILURE_MESSAGE: Final = (
    "The Anthropic account has no credit left or has a billing problem."
)

_BILLING_ERROR_TYPE: Final = "billing_error"
# An exhausted prepaid balance is not reported as a billing error. It arrives as a plain
# HTTP 400, and this phrase in the provider's message is the only sign of it.
_LOW_BALANCE_STATUS: Final = 400
_LOW_BALANCE_PHRASE: Final = "credit balance is too low"

# Statuses that mean "try again later" beyond the retries the SDK already made.
_TRANSIENT_STATUS_CODES: Final = frozenset({408, 409, 429})


def is_billing_failure(error: anthropic.APIStatusError) -> bool:
    """Whether the provider rejected a call because the account cannot pay for it."""
    if error.type == _BILLING_ERROR_TYPE:
        return True
    return error.status_code == _LOW_BALANCE_STATUS and _LOW_BALANCE_PHRASE in error.message.lower()


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    """A failed call, described safely.

    ``retryable`` says whether the same call can succeed later without anyone acting.
    """

    message: str
    retryable: bool
    billing: bool = False


def describe_provider_failure(
    error: anthropic.APIConnectionError | anthropic.APIStatusError, *, model: str
) -> ProviderFailure:
    """Describe a connection or status error from the SDK in the application's words."""
    if isinstance(error, anthropic.APITimeoutError):
        return ProviderFailure("The Anthropic API request timed out.", retryable=True)
    if isinstance(error, anthropic.APIConnectionError):
        return ProviderFailure("The Anthropic API could not be reached.", retryable=True)
    if isinstance(error, anthropic.RateLimitError):
        return ProviderFailure("The Anthropic API rate limit was hit.", retryable=True)
    if isinstance(error, anthropic.AuthenticationError):
        return ProviderFailure("The Anthropic API rejected the API key.", retryable=False)
    if isinstance(error, anthropic.PermissionDeniedError):
        return ProviderFailure(
            "The Anthropic API key is not permitted to make this request.", retryable=False
        )
    if isinstance(error, anthropic.NotFoundError):
        return ProviderFailure(f"The Anthropic model '{model}' is not available.", retryable=False)
    if is_billing_failure(error):
        return ProviderFailure(BILLING_FAILURE_MESSAGE, retryable=False, billing=True)
    status = error.status_code
    if status >= 500 or status in _TRANSIENT_STATUS_CODES:
        return ProviderFailure(
            f"The Anthropic API returned a temporary error (HTTP {status}).", retryable=True
        )
    return ProviderFailure(
        f"The Anthropic API rejected the request (HTTP {status}).", retryable=False
    )
