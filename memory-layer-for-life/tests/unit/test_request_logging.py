"""Request logging: one line per request, a request id on the response, no content."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import request_logging
from app.core.request_logging import REQUEST_ID_HEADER, RequestLoggingMiddleware


@pytest.fixture(autouse=True)
def fresh_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the middleware a logger that no earlier test has bound.

    A test that runs the application's lifespan configures structlog to cache loggers. A
    cached logger keeps the processors it was bound with, so ``capture_logs`` in a later
    test would see nothing from it. A new logger makes these tests independent of order.
    """
    monkeypatch.setattr(request_logging, "logger", structlog.get_logger("request-logging-test"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    application = FastAPI()
    application.add_middleware(RequestLoggingMiddleware, api_prefix="/api/v1")

    @application.get("/api/v1/thing")
    async def thing(secret: str = "") -> dict[str, str]:
        return {"ok": secret}

    @application.get("/api/v1/context")
    async def context() -> dict[str, Any]:
        # What a handler, or anything it logs, sees in the logging context.
        return dict(structlog.contextvars.get_contextvars())

    @application.get("/api/v1/crash")
    async def crash() -> None:
        raise RuntimeError("boom")

    @application.get("/assets/app.js")
    async def asset() -> dict[str, bool]:
        return {"asset": True}

    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def entries(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in logs if entry["event"] == "http_request"]


async def test_each_api_request_is_logged_without_its_query_string(client: AsyncClient) -> None:
    with structlog.testing.capture_logs() as logs:
        response = await client.get("/api/v1/thing?secret=buy+milk")

    assert response.status_code == 200
    (entry,) = entries(logs)
    assert entry["log_level"] == "info"
    assert (entry["method"], entry["path"], entry["status"]) == ("GET", "/api/v1/thing", 200)
    assert entry["duration_ms"] >= 0
    assert "milk" not in str(entry)


async def test_a_fresh_request_id_is_returned_and_logged(client: AsyncClient) -> None:
    with structlog.testing.capture_logs() as logs:
        response = await client.get("/api/v1/thing")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert len(request_id) == 32
    (entry,) = entries(logs)
    assert entry["request_id"] == request_id


async def test_the_request_id_is_bound_to_the_logging_context_of_the_request(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/context", headers={REQUEST_ID_HEADER: "trace-7"})

    assert response.json() == {"request_id": "trace-7"}
    # The context is cleared once the request is over.
    assert "request_id" not in structlog.contextvars.get_contextvars()


async def test_a_safe_client_request_id_is_kept(client: AsyncClient) -> None:
    response = await client.get("/api/v1/thing", headers={REQUEST_ID_HEADER: "ui-42.a_b"})

    assert response.headers[REQUEST_ID_HEADER] == "ui-42.a_b"


async def test_an_unsafe_client_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/v1/thing", headers={REQUEST_ID_HEADER: "bad id\n"})

    assert response.headers[REQUEST_ID_HEADER] != "bad id\n"
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


async def test_a_crash_is_logged_as_a_500(client: AsyncClient) -> None:
    with structlog.testing.capture_logs() as logs:
        response = await client.get("/api/v1/crash")

    assert response.status_code == 500
    (entry,) = entries(logs)
    assert entry["status"] == 500


async def test_requests_for_ui_files_are_logged_quietly(client: AsyncClient) -> None:
    with structlog.testing.capture_logs() as logs:
        await client.get("/assets/app.js")

    (entry,) = entries(logs)
    assert entry["log_level"] == "debug"
