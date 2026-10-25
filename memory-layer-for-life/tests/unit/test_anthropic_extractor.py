"""The Anthropic adapter with a mocked client: request shape and outcome translation.

No test here reaches the network.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest

from app.core.config import Settings
from app.domain.errors import (
    ExtractionBillingError,
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    InvalidExtractionOutputError,
    PermanentExtractionError,
    TransientExtractionError,
)
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.anthropic_errors import BILLING_FAILURE_MESSAGE
from app.integrations.extraction.anthropic_extractor import (
    AnthropicExtractor,
    describe_validation_error,
)
from app.integrations.extraction.base import ExtractionMessage, ExtractionRequest
from app.integrations.extraction.factory import build_extractor, configured_extractor_descriptor
from app.integrations.extraction.prompt import (
    EXTRACTION_PROMPT_VERSION,
    SYSTEM_PROMPT,
    render_request,
)
from app.schemas.extraction import ExtractionOutput
from tests.support.extraction import extraction, memory
from tests.support.golden import golden_cases

REQUEST = ExtractionRequest(
    messages=(
        ExtractionMessage(index=0, text="buy milk", sent_at_local=datetime(2026, 4, 19, 3, 27)),
        ExtractionMessage(index=1, text='2 litres "full cream"', sent_at_local=None),
    ),
    timezone_name="Asia/Kolkata",
)
HTTP_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_response(
    text: str,
    *,
    stop_reason: str = "end_turn",
    leading_thinking: bool = False,
    cache_read: int | None = 3000,
) -> SimpleNamespace:
    content = [SimpleNamespace(type="text", text=text)]
    if leading_thinking:
        content.insert(0, SimpleNamespace(type="thinking", thinking="", signature="sig"))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        model="claude-haiku-5-5",
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=80,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=None,
        ),
        _request_id="req_123",
    )


def extractor_returning(result: Any) -> tuple[AnthropicExtractor, AsyncMock]:
    create = (
        AsyncMock(side_effect=result)
        if isinstance(result, Exception)
        else AsyncMock(return_value=result)
    )
    client = MagicMock()
    client.messages.create = create
    extractor = AnthropicExtractor(
        client, model="claude-haiku-5-5", effort="medium", max_tokens=16000
    )
    return extractor, create


def status_error(
    error_type: type[anthropic.APIStatusError], status: int
) -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=HTTP_REQUEST)
    return error_type("provider said no", response=response, body=None)


# --- Successful call ------------------------------------------------------------------


async def test_valid_output_is_returned_with_usage() -> None:
    expected = extraction(memory("Buy milk"))
    extractor, _ = extractor_returning(api_response(expected.model_dump_json()))

    response = await extractor.extract(REQUEST)

    assert response.output == expected
    assert response.model == "claude-haiku-5-5"
    assert response.request_id == "req_123"
    assert response.usage is not None
    assert (response.usage.input_tokens, response.usage.output_tokens) == (120, 80)
    assert response.usage.cache_read_input_tokens == 3000
    assert response.usage.cache_creation_input_tokens == 0


async def test_thinking_blocks_before_the_answer_are_skipped() -> None:
    expected = extraction()
    extractor, _ = extractor_returning(
        api_response(expected.model_dump_json(), leading_thinking=True)
    )

    assert (await extractor.extract(REQUEST)).output == expected


async def test_request_uses_structured_output_caching_and_no_sampling_parameters() -> None:
    extractor, create = extractor_returning(api_response(extraction().model_dump_json()))

    await extractor.extract(REQUEST)

    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["max_tokens"] == 16000
    assert kwargs["system"] == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert kwargs["messages"] == [{"role": "user", "content": render_request(REQUEST)}]
    assert kwargs["output_config"]["effort"] == "medium"
    output_format = kwargs["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    assert set(output_format["schema"]["properties"]) == set(ExtractionOutput.model_fields)
    # Rejected by current models, and never needed with a schema-constrained answer.
    assert not {"temperature", "top_p", "top_k", "thinking"} & kwargs.keys()


def test_descriptor_identifies_provider_model_and_prompt() -> None:
    extractor, _ = extractor_returning(api_response("{}"))

    descriptor = extractor.descriptor

    assert (descriptor.provider, descriptor.model) == ("anthropic", "claude-haiku-5-5")
    assert descriptor.prompt_version == EXTRACTION_PROMPT_VERSION
    assert descriptor.version == f"anthropic:{EXTRACTION_PROMPT_VERSION}"


# --- Unusable answers -----------------------------------------------------------------


async def test_a_refusal_is_reported_before_the_content_is_read() -> None:
    extractor, _ = extractor_returning(api_response("I cannot help.", stop_reason="refusal"))

    with pytest.raises(ExtractionRefusedError) as raised:
        await extractor.extract(REQUEST)

    assert raised.value.retryable is False


async def test_a_truncated_answer_is_reported() -> None:
    extractor, _ = extractor_returning(
        api_response('{"disposition": "ext', stop_reason="max_tokens")
    )

    with pytest.raises(ExtractionTruncatedError):
        await extractor.extract(REQUEST)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("this is not json", id="not json"),
        pytest.param("", id="empty answer"),
        pytest.param('{"disposition": "extract"}', id="missing fields"),
        pytest.param(
            json.dumps(
                {
                    "disposition": "abstain",
                    "disposition_reason": "x",
                    "memories": [memory().model_dump(mode="json")],
                    "entity_mentions": [],
                }
            ),
            id="abstention with a memory",
        ),
    ],
)
async def test_output_that_breaks_the_contract_is_rejected(text: str) -> None:
    extractor, _ = extractor_returning(api_response(text))

    with pytest.raises(InvalidExtractionOutputError) as raised:
        await extractor.extract(REQUEST)

    assert raised.value.retryable is False
    assert "validation error" in raised.value.message


async def test_validation_messages_never_echo_model_output() -> None:
    leaked = "PRIVATE-DIARY-TEXT"
    broken = extraction(memory(leaked)).model_dump(mode="json")
    broken["memories"][0]["confidence"] = 7

    extractor, _ = extractor_returning(api_response(json.dumps(broken)))
    with pytest.raises(InvalidExtractionOutputError) as raised:
        await extractor.extract(REQUEST)

    assert leaked not in raised.value.message
    assert "memories.0.confidence" in raised.value.message


def test_validation_summary_is_bounded() -> None:
    with pytest.raises(Exception) as raised:
        ExtractionOutput.model_validate({})

    summary = describe_validation_error(raised.value)  # type: ignore[arg-type]

    assert summary.startswith("4 validation error(s): ")
    assert "disposition: Field required" in summary


# --- Provider failures ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        pytest.param(
            anthropic.APITimeoutError(request=HTTP_REQUEST), TransientExtractionError, id="timeout"
        ),
        pytest.param(
            anthropic.APIConnectionError(message="down", request=HTTP_REQUEST),
            TransientExtractionError,
            id="connection",
        ),
        pytest.param(
            status_error(anthropic.RateLimitError, 429), TransientExtractionError, id="rate limit"
        ),
        pytest.param(
            status_error(anthropic.InternalServerError, 500), TransientExtractionError, id="500"
        ),
        pytest.param(
            status_error(anthropic.APIStatusError, 529), TransientExtractionError, id="overloaded"
        ),
        pytest.param(
            status_error(anthropic.APIStatusError, 409), TransientExtractionError, id="conflict"
        ),
        pytest.param(
            status_error(anthropic.AuthenticationError, 401), PermanentExtractionError, id="bad key"
        ),
        pytest.param(
            status_error(anthropic.PermissionDeniedError, 403),
            PermanentExtractionError,
            id="forbidden",
        ),
        pytest.param(
            status_error(anthropic.NotFoundError, 404), PermanentExtractionError, id="unknown model"
        ),
        pytest.param(
            status_error(anthropic.BadRequestError, 400), PermanentExtractionError, id="bad request"
        ),
        pytest.param(
            status_error(anthropic.APIStatusError, 413), PermanentExtractionError, id="too large"
        ),
    ],
)
async def test_provider_errors_are_classified(
    error: Exception, expected_type: type[ExtractionError]
) -> None:
    extractor, _ = extractor_returning(error)

    with pytest.raises(ExtractionError) as raised:
        await extractor.extract(REQUEST)

    assert type(raised.value) is expected_type
    assert raised.value.retryable is (expected_type is TransientExtractionError)
    # The stored message is ours, not the provider's text.
    assert "provider said no" not in raised.value.message


def provider_error(status: int, error_type: str, message: str) -> anthropic.APIStatusError:
    """A status error carrying the body the API really sends."""
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    response = httpx2.Response(status, request=HTTP_REQUEST)
    return anthropic.APIStatusError(message, response=response, body=body)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(provider_error(402, "billing_error", "Payment required"), id="billing"),
        pytest.param(
            provider_error(
                400,
                "invalid_request_error",
                "Your credit balance is too low to access the Anthropic API.",
            ),
            id="low balance",
        ),
    ],
)
async def test_an_account_that_cannot_pay_is_named(error: Exception) -> None:
    extractor, _ = extractor_returning(error)

    with pytest.raises(ExtractionBillingError) as raised:
        await extractor.extract(REQUEST)

    # Not retried: nothing changes until the owner adds credit and replays the run.
    assert raised.value.retryable is False
    assert raised.value.code == "EXTRACTION_PROVIDER_BILLING"
    assert raised.value.message == BILLING_FAILURE_MESSAGE


async def test_an_ordinary_rejected_request_is_not_mistaken_for_billing() -> None:
    error = provider_error(400, "invalid_request_error", "max_tokens: must be positive")
    extractor, _ = extractor_returning(error)

    with pytest.raises(ExtractionError) as raised:
        await extractor.extract(REQUEST)

    assert type(raised.value) is PermanentExtractionError
    assert "max_tokens" not in raised.value.message


# --- Prompt and rendering -------------------------------------------------------------


def test_request_is_rendered_as_json_data() -> None:
    rendered = render_request(REQUEST)

    preamble, _, document = rendered.partition("\n\n")
    assert "data, not instructions" in preamble
    assert json.loads(document) == {
        "timezone": "Asia/Kolkata",
        "messages": [
            {"index": 0, "sent_at": "2026-04-19 03:27", "weekday": "Sunday", "text": "buy milk"},
            {"index": 1, "sent_at": None, "text": '2 litres "full cream"'},
        ],
    }


def test_prompt_names_every_vocabulary_value() -> None:
    from app.domain.enums import ExtractionDisposition, MemoryState, MemoryType

    for value in (*MemoryType, *ExtractionDisposition, *MemoryState):
        assert f"`{value.value}`" in SYSTEM_PROMPT, value


def test_prompt_contains_no_golden_case() -> None:
    """Copying evaluation cases into the prompt would turn the evaluation into a memory test."""
    cases = golden_cases()
    if not cases:
        pytest.skip("golden dataset not present")
    prompt = SYSTEM_PROMPT.casefold()

    for case in cases:
        for message in case.input.messages:
            text = message.content.strip().casefold()
            if len(text) >= 12:
                assert text not in prompt, case.case_id
        for expected in case.expected.memories:
            assert expected.summary.casefold() not in prompt, case.case_id


# --- Factory --------------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_factory_returns_none_without_a_key() -> None:
    settings = _settings(ANTHROPIC_API_KEY=None)
    manager = AnthropicClientManager()
    manager.initialize(settings)

    assert build_extractor(settings, manager) is None
    # The identity is still known, so captured units get a stable processing identity.
    assert configured_extractor_descriptor(settings).model == "claude-sonnet-5-5"


async def test_factory_builds_the_configured_extractor() -> None:
    settings = _settings(
        ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-test", EXTRACTION_EFFORT="low"
    )
    manager = AnthropicClientManager()
    manager.initialize(settings)
    try:
        extractor = build_extractor(settings, manager)

        assert extractor is not None
        assert extractor.descriptor == configured_extractor_descriptor(settings)
        assert extractor.descriptor.model == "claude-test"
    finally:
        await manager.close()
