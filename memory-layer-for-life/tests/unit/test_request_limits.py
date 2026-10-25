"""Request bodies over the limit are refused with 413 in the API's error format, whether
their size is declared up front or only discovered while reading."""

from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.request_limits import REQUEST_TOO_LARGE, BodySizeLimitMiddleware

LIMIT = 1024


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=LIMIT)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    return app


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://test")


async def test_a_body_within_the_limit_is_served() -> None:
    async with client() as http:
        response = await http.post("/echo", content=b"x" * LIMIT)

    assert response.status_code == 200
    assert response.json() == {"bytes": LIMIT}


async def test_a_declared_oversized_body_is_refused_unread() -> None:
    async with client() as http:
        response = await http.post("/echo", content=b"x" * (LIMIT + 1))

    assert response.status_code == 413
    assert response.json()["error_code"] == REQUEST_TOO_LARGE
    assert "Send fewer or smaller files" in response.json()["message"]


async def test_an_undeclared_oversized_body_is_refused_while_reading() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * 512

    async with client() as http:
        response = await http.post("/echo", content=chunks())

    assert response.status_code == 413
    assert response.json()["error_code"] == REQUEST_TOO_LARGE


async def test_requests_without_a_body_pass() -> None:
    app = make_app()

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/ping")

    assert response.status_code == 200
