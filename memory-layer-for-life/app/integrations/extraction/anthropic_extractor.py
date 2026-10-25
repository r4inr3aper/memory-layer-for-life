"""Extraction through the Anthropic Messages API with structured outputs."""

from typing import Any, Final

import anthropic
from anthropic import AsyncAnthropic, transform_schema
from anthropic.types import Message
from anthropic.types.beta import BetaMessage
from pydantic import ValidationError

from app.core.config import EffortLevel
from app.domain.enums import LlmOperation
from app.domain.errors import (
    ExtractionBillingError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    InvalidExtractionOutputError,
    PermanentExtractionError,
    TransientExtractionError,
)
from app.domain.versions import ExtractorDescriptor
from app.integrations.anthropic_calls import PROVIDER_NAME, AnthropicCallObserver
from app.integrations.anthropic_errors import describe_provider_failure
from app.integrations.extraction.base import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionUsage,
)
from app.integrations.extraction.prompt import (
    EXTRACTION_PROMPT_VERSION,
    SYSTEM_PROMPT,
    render_request,
)
from app.integrations.llm_calls import UNATTRIBUTED_CALL, LlmCallSpec
from app.schemas.extraction import ExtractionOutput

# The API enforces this schema while generating. Constraints it cannot express, such as
# numeric bounds, are moved into field descriptions by the SDK and checked again when the
# response is validated against ``ExtractionOutput``.
_OUTPUT_SCHEMA: Final[dict[str, Any]] = transform_schema(ExtractionOutput)

_MAX_VALIDATION_DETAILS: Final = 5

# Server-side refusal fallback. When the model's safety classifiers decline a request,
# the API re-runs it on the fallback model Anthropic recommends for that refusal
# category, inside the same call. The header belongs to the "default" form.
_FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"


def provider_output_schema() -> dict[str, Any]:
    """The JSON schema the provider is asked to follow while generating."""
    return _OUTPUT_SCHEMA


def describe_validation_error(error: ValidationError) -> str:
    """Summarize a validation failure without echoing any model output.

    Only error locations and messages are kept. Input values are dropped, because they
    can contain personal message content.
    """
    details = [
        f"{'.'.join(str(part) for part in item['loc']) or '<root>'}: {item['msg']}"
        for item in error.errors(include_input=False, include_url=False)[:_MAX_VALIDATION_DETAILS]
    ]
    return f"{error.error_count()} validation error(s): " + "; ".join(details)


class AnthropicExtractor:
    """``Extractor`` backed by a Claude model.

    The client is owned by ``AnthropicClientManager`` and shared by the process. This
    class only shapes the request and translates the outcome. Every call it makes is
    reported through the observer.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        *,
        model: str,
        effort: EffortLevel,
        max_tokens: int,
        refusal_fallback: bool = False,
        observer: AnthropicCallObserver | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._effort: EffortLevel = effort
        self._max_tokens = max_tokens
        self._refusal_fallback = refusal_fallback
        self._observer = observer or AnthropicCallObserver()
        self._descriptor = ExtractorDescriptor(
            provider=PROVIDER_NAME, model=model, prompt_version=EXTRACTION_PROMPT_VERSION
        )

    @property
    def descriptor(self) -> ExtractorDescriptor:
        return self._descriptor

    def _call_spec(self, request: ExtractionRequest) -> LlmCallSpec:
        return LlmCallSpec(
            provider=PROVIDER_NAME,
            operation=LlmOperation.EXTRACTION,
            requested_model=self._model,
            prompt_version=EXTRACTION_PROMPT_VERSION,
            effort=self._effort,
            max_tokens=self._max_tokens,
            refusal_fallback=self._refusal_fallback,
            context=request.call_context or UNATTRIBUTED_CALL,
        )

    async def _create_message(self, request: ExtractionRequest) -> Message | BetaMessage:
        """Send the request. Both branches build the same request body.

        The system prompt is identical for every unit, so it is marked for caching.
        """
        prompt = render_request(request)
        if self._refusal_fallback:
            # The fallback parameter is a beta feature of the same Messages endpoint.
            return await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
                },
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        return await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
            },
        )

    async def _send(self, request: ExtractionRequest) -> Message | BetaMessage:
        """Call the provider and translate its failures into domain errors."""
        try:
            return await self._create_message(request)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as error:
            failure = describe_provider_failure(error, model=self._model)
            if failure.billing:
                raise ExtractionBillingError(failure.message) from error
            if failure.retryable:
                raise TransientExtractionError(failure.message) from error
            raise PermanentExtractionError(failure.message) from error

    async def extract(self, request: ExtractionRequest) -> ExtractionResponse:
        async with self._observer.observe(self._call_spec(request)) as call:
            response = await self._send(request)
            # Noted before the answer is interpreted: an unusable answer was still billed.
            call.answered(response)

            # A refusal or a truncated answer does not have to match the schema, so the
            # stop reason is checked before the content is read.
            if response.stop_reason == "refusal":
                raise ExtractionRefusedError("The model declined to process this content.")
            if response.stop_reason == "max_tokens":
                raise ExtractionTruncatedError(
                    "The model reached the output limit before finishing the extraction."
                )

            # A response can begin with thinking blocks, so text blocks are selected by type.
            text = "".join(block.text for block in response.content if block.type == "text")
            try:
                output = ExtractionOutput.model_validate_json(text)
            except ValidationError as error:
                raise InvalidExtractionOutputError(
                    describe_validation_error(error), raw_output=text
                ) from error

            usage = response.usage
            return ExtractionResponse(
                output=output,
                model=response.model,
                usage=ExtractionUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_input_tokens=usage.cache_read_input_tokens or 0,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
                ),
                request_id=response._request_id,
                stop_reason=response.stop_reason,
                raw_output=text,
            )
