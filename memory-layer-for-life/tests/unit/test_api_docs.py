"""The interactive API documentation is served everywhere except production."""

import pytest

from app import main as app_main
from app.core.config import Settings

DEPLOYED = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db.example.com/app?ssl=require",
    "SUPABASE_URL": "https://abc.supabase.co",
    "ANTHROPIC_API_KEY": "sk-ant-test",
}
DOC_PATHS = {"/docs", "/redoc", "/openapi.json"}


def route_paths(monkeypatch: pytest.MonkeyPatch, **values: object) -> set[str]:
    settings = Settings(_env_file=None, **{**DEPLOYED, **values})  # type: ignore[arg-type]
    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    return {getattr(route, "path", "") for route in app_main.create_app().routes}


def test_production_hides_the_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not route_paths(monkeypatch, ENVIRONMENT="production") & DOC_PATHS


def test_staging_serves_the_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert route_paths(monkeypatch, ENVIRONMENT="staging") >= DOC_PATHS


def test_production_can_serve_them_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = route_paths(monkeypatch, ENVIRONMENT="production", API_DOCS_ENABLED=True)

    assert paths >= DOC_PATHS
