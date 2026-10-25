"""Health endpoints and application lifecycle."""

from httpx import ASGITransport, AsyncClient

from app.bootstrap import AppContainer
from app.main import create_app
from tests.integration.conftest import ApiHarness


async def test_liveness_needs_no_dependency(api: ApiHarness) -> None:
    response = await api.client.get("/api/v1/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["app_name"] == "second-brain"
    assert body["environment"] == "testing"


async def test_readiness_reports_the_database(api: ApiHarness) -> None:
    response = await api.client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected", "details": None}


async def test_health_checks_never_call_the_provider(api: ApiHarness) -> None:
    await api.client.get("/api/v1/health/live")
    await api.client.get("/api/v1/health/ready")

    assert api.extractor.call_count == 0


async def test_unknown_route_is_not_found(api: ApiHarness) -> None:
    response = await api.client.get("/api/v1/nonexistent")

    assert response.status_code == 404


async def test_lifespan_builds_and_releases_the_shared_components(engine: object) -> None:
    """Startup wires the application without any network call. Shutdown releases it."""
    application = create_app()

    async with application.router.lifespan_context(application):
        container = application.state.container
        assert isinstance(container, AppContainer)
        # The test environment has no provider key, so nothing can be processed.
        assert container.pipeline_runner.can_process is False
        assert container.anthropic_manager.is_configured is False
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/health/ready")).status_code == 200

    # A disposed engine holds no open connections.
    assert container.engine.pool.checkedout() == 0
