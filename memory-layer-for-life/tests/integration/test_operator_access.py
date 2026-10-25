"""The operator routes answer only the computer running the API, or a request with the
operator key; the app's routes and the health checks are unaffected. Replay never
touches app users' messages."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bootstrap import AppContainer, build_container
from app.core.config import Settings
from app.domain.enums import MessageSource
from app.main import create_app
from app.schemas.raw_message import RawMessageCreate
from tests.integration.conftest import ApiHarness
from tests.support.pipeline import FakeClock
from tests.support.retrieval import app_user

API = "/api/v1"
PHONE = "192.168.1.5"


@asynccontextmanager
async def client_at(container: AppContainer, host: str) -> AsyncIterator[AsyncClient]:
    """The application, reached from ``host``. The container stays open for its owner."""
    application = create_app()
    application.state.container = container
    transport = ASGITransport(app=application, client=(host, 50123))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/memories",
        "/processing/runs",
        "/console/config",
        "/console/pipeline-stats",
        "/llm-calls",
        "/evaluations",
        "/playground/extractions",
    ],
)
async def test_operator_routes_refuse_other_computers(api: ApiHarness, path: str) -> None:
    async with client_at(api.container, PHONE) as phone:
        response = await phone.get(f"{API}{path}")

    assert response.status_code == 403
    assert response.json()["error_code"] == "OPERATOR_ACCESS_DENIED"


async def test_operator_writes_are_refused_before_anything_happens(api: ApiHarness) -> None:
    async with client_at(api.container, PHONE) as phone:
        captured = await phone.post(
            f"{API}/ingestion/units",
            json={"messages": [{"source": "manual_capture", "content": "buy milk"}]},
        )
        replayed = await phone.post(f"{API}/processing/replays", json={"all_units": True})

    assert (captured.status_code, replayed.status_code) == (403, 403)
    assert api.extractor.call_count == 0


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
async def test_this_computer_needs_no_key(api: ApiHarness, host: str) -> None:
    async with client_at(api.container, host) as local:
        response = await local.get(f"{API}/memories")

    assert response.status_code == 200, response.text


async def test_health_checks_and_app_routes_are_unaffected(api: ApiHarness) -> None:
    async with client_at(api.container, PHONE) as phone:
        health = await phone.get(f"{API}/health/live")
        app_route = await phone.get(f"{API}/me")

    assert health.status_code == 200
    # The app's routes still need a signed-in user, not the operator key.
    assert app_route.status_code in {401, 503}
    assert app_route.json()["error_code"] != "OPERATOR_ACCESS_DENIED"


async def test_the_operator_key_opens_the_routes_from_elsewhere(
    settings: Settings, engine: object, clock: FakeClock
) -> None:
    container = build_container(
        settings.model_copy(update={"OPERATOR_API_KEY": "k3y"}), clock=clock
    )
    try:
        async with client_at(container, PHONE) as phone:
            keyed = await phone.get(f"{API}/memories", headers={"X-Operator-Key": "k3y"})
            wrong = await phone.get(f"{API}/memories", headers={"X-Operator-Key": "nope"})
            missing = await phone.get(f"{API}/memories")
    finally:
        await container.aclose()

    assert keyed.status_code == 200, keyed.text
    assert (wrong.status_code, missing.status_code) == (403, 403)


async def test_a_deployed_api_trusts_only_the_key(
    settings: Settings, engine: object, clock: FakeClock
) -> None:
    """Behind a platform's proxy, a forwarded "127.0.0.1" proves nothing."""
    key = "k" * 32
    container = build_container(
        settings.model_copy(update={"ENVIRONMENT": "production", "OPERATOR_API_KEY": key}),
        clock=clock,
    )
    try:
        async with client_at(container, "127.0.0.1") as local:
            unkeyed = await local.get(f"{API}/memories")
            keyed = await local.get(f"{API}/memories", headers={"X-Operator-Key": key})
    finally:
        await container.aclose()

    assert unkeyed.status_code == 403
    assert unkeyed.json()["error_code"] == "OPERATOR_ACCESS_DENIED"
    assert keyed.status_code == 200, keyed.text


async def test_replay_never_selects_an_app_user_s_messages(
    api: ApiHarness,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
) -> None:
    owner = await app_user(session_factory, clock)
    ingest = api.container.ingestion_service.ingest
    [mine] = await ingest(
        [[RawMessageCreate(source=MessageSource.MANUAL_CAPTURE, content="buy milk")]]
    )
    [theirs] = await ingest(
        [[RawMessageCreate(source=MessageSource.APP_CHAT, content="My sister lives in Pune")]],
        owner_id=owner,
    )

    everything = await api.client.post(
        f"{API}/processing/replays", json={"all_units": True, "limit": 50}
    )
    by_id = await api.client.post(
        f"{API}/processing/replays", json={"run_ids": [str(theirs.run.id)]}
    )

    assert everything.status_code == 202, everything.text
    assert [outcome["processing_run"]["id"] for outcome in everything.json()["outcomes"]] == [
        str(mine.run.id)
    ]
    assert by_id.json()["outcomes"] == []
