"""A private deployment lists who may use it (ACCESS_ALLOWED_EMAILS); anyone else who
signs in is refused before the API keeps anything about them."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.principal import Principal
from app.models.app_user import AppUser
from tests.integration.conftest import AssistantHarnessFactory
from tests.support.app_api import API
from tests.support.assistant import new_principal


async def test_only_listed_people_get_in(
    assistant_api_with: AssistantHarnessFactory,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with assistant_api_with(ACCESS_ALLOWED_EMAILS=["ada@example.com"]) as api:
        listed = await api.client.get(f"{API}/me", headers=api.sign_in(new_principal("Ada")))
        stranger = await api.client.get(f"{API}/me", headers=api.sign_in(new_principal("Grace")))

    assert listed.status_code == 200, listed.text
    assert stranger.status_code == 403
    assert stranger.json()["error_code"] == "ACCESS_NOT_ALLOWED"
    async with session_factory() as session:
        emails = (await session.scalars(select(AppUser.email))).all()
    assert emails == ["ada@example.com"]


async def test_the_email_s_case_does_not_matter(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    shouting = Principal(id=uuid.uuid4(), email="ADA@Example.COM", display_name="Ada")
    async with assistant_api_with(ACCESS_ALLOWED_EMAILS=["ada@example.com"]) as api:
        response = await api.client.get(f"{API}/me", headers=api.sign_in(shouting))

    assert response.status_code == 200, response.text


async def test_a_sign_in_without_an_email_is_refused_by_a_list(
    assistant_api_with: AssistantHarnessFactory,
) -> None:
    phone_only = Principal(id=uuid.uuid4(), email=None, display_name=None)
    async with assistant_api_with(ACCESS_ALLOWED_EMAILS=["ada@example.com"]) as api:
        response = await api.client.get(f"{API}/me", headers=api.sign_in(phone_only))

    assert response.status_code == 403
    assert response.json()["error_code"] == "ACCESS_NOT_ALLOWED"
