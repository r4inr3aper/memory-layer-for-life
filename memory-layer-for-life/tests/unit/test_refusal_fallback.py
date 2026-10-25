"""Server-side refusal fallback: which endpoint is called, and how the answer is read."""

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.domain.errors import ExtractionRefusedError
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.extraction.anthropic_extractor import AnthropicExtractor
from app.integrations.extraction.base import ExtractionMessage, ExtractionRequest
from app.integrations.extraction.factory import build_extractor
from tests.support.extraction import extraction, memory

REQUEST = ExtractionRequest(
    messages=(
        ExtractionMessage(index=0, text="buy milk", sent_at_local=datetime(2026, 4, 19, 3, 27)),
    ),
    timezone_name="UTC",
)


def api_response(content: list[Any], *, model: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        model=model,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        ),
        _request_id="req_1",
    )


def text_block(text: str) -> Any:
    return SimpleNamespace(type="text", text=text)


def make_extractor(*, refusal_fallback: bool, response: Any) -> tuple[AnthropicExtractor, Any]:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    client.beta.messages.create = AsyncMock(return_value=response)
    extractor = AnthropicExtractor(
        client,
        model="claude-sonnet-5-5",
        effort="medium",
        max_tokens=16000,
        refusal_fallback=refusal_fallback,
    )
    return extractor, client


async def test_fallback_uses_the_beta_endpoint_with_the_default_form() -> None:
    answer = extraction(memory("Buy milk")).model_dump_json()
    extractor, client = make_extractor(
        refusal_fallback=True,
        response=api_response([text_block(answer)], model="claude-sonnet-5-5"),
    )

    await extractor.extract(REQUEST)

    client.messages.create.assert_not_awaited()
    kwargs = client.beta.messages.create.await_args.kwargs
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    # Everything else is the same request the plain endpoint gets.
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["output_config"]["effort"] == "medium"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


async def test_without_fallback_the_plain_endpoint_is_used() -> None:
    answer = extraction(memory("Buy milk")).model_dump_json()
    extractor, client = make_extractor(
        refusal_fallback=False,
        response=api_response([text_block(answer)], model="claude-sonnet-5-5"),
    )

    await extractor.extract(REQUEST)

    client.beta.messages.create.assert_not_awaited()
    kwargs = client.messages.create.await_args.kwargs
    assert "fallbacks" not in kwargs
    assert "betas" not in kwargs


async def test_an_answer_served_by_the_fallback_model_is_read_and_attributed() -> None:
    """After a decline the response carries a fallback marker, then the fallback's answer."""
    expected = extraction(memory("Buy milk"))
    marker = SimpleNamespace(type="fallback")
    extractor, _ = make_extractor(
        refusal_fallback=True,
        response=api_response(
            [marker, text_block(expected.model_dump_json())], model="claude-sonnet-5"
        ),
    )

    response = await extractor.extract(REQUEST)

    assert response.output == expected
    # The model that actually answered is what gets recorded with the extraction.
    assert response.model == "claude-sonnet-5"


async def test_a_refusal_by_the_whole_chain_is_still_a_refusal() -> None:
    extractor, _ = make_extractor(
        refusal_fallback=True,
        response=api_response([], model="claude-sonnet-5", stop_reason="refusal"),
    )

    with pytest.raises(ExtractionRefusedError):
        await extractor.extract(REQUEST)


@pytest.mark.parametrize("enabled", [True, False])
async def test_factory_passes_the_setting_through(enabled: bool) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, ANTHROPIC_API_KEY="test-key", ANTHROPIC_REFUSAL_FALLBACK=enabled
    )
    manager = AnthropicClientManager()
    manager.initialize(settings)
    try:
        extractor = build_extractor(settings, manager)

        assert extractor is not None
        assert extractor._refusal_fallback is enabled
    finally:
        await manager.close()
