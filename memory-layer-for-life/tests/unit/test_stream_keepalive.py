"""The reply stream sends blank keep-alive lines while a reply is quiet, so proxies in
front of a hosted API do not drop the connection, and never loses or reorders events."""

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.v1.endpoints import threads


@pytest.fixture(autouse=True)
def plain_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events here are plain dicts, written as they are."""
    monkeypatch.setattr(
        threads,
        "to_stream_event",
        lambda event: SimpleNamespace(model_dump_json=lambda: json.dumps(event)),
    )


async def collect(events: AsyncIterator[Any], keepalive_seconds: float) -> list[bytes]:
    return [chunk async for chunk in threads._ndjson(events, keepalive_seconds=keepalive_seconds)]


async def test_a_quiet_reply_is_kept_alive_and_finishes() -> None:
    async def events() -> AsyncIterator[Any]:
        yield {"type": "turn_started"}
        await asyncio.sleep(0.12)  # a long tool call
        yield {"type": "final"}

    chunks = await collect(events(), keepalive_seconds=0.05)

    lines = [chunk for chunk in chunks if chunk != b"\n"]
    assert lines == [b'{"type": "turn_started"}\n', b'{"type": "final"}\n']
    assert chunks[0] == b'{"type": "turn_started"}\n'
    assert chunks.count(b"\n") >= 1


async def test_a_busy_reply_has_no_keep_alives() -> None:
    async def events() -> AsyncIterator[Any]:
        for index in range(3):
            yield {"type": "text_delta", "index": index}

    chunks = await collect(events(), keepalive_seconds=10)

    assert b"\n" not in chunks
    assert len(chunks) == 3


async def test_closing_the_response_stops_reading_the_reply() -> None:
    closed = asyncio.Event()

    async def events() -> AsyncIterator[Any]:
        try:
            yield {"type": "turn_started"}
            await asyncio.Event().wait()  # a reply that never ends
            yield {"type": "final"}
        finally:
            closed.set()

    stream = threads._ndjson(events(), keepalive_seconds=0.01)
    assert await anext(stream) == b'{"type": "turn_started"}\n'
    assert await anext(stream) == b"\n"
    await stream.aclose()
    await asyncio.wait_for(closed.wait(), timeout=1)
