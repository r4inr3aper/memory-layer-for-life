"""Shortcuts for driving the assistant app's API in integration tests."""

import json
import uuid
from typing import TYPE_CHECKING, Any

from tests.support.assistant import call, say

if TYPE_CHECKING:
    from tests.integration.conftest import AssistantHarness

API = "/api/v1"


async def stream(
    harness: "AssistantHarness",
    headers: dict[str, str],
    thread_id: str,
    content: str,
    *,
    timezone: str = "UTC",
    attachments: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Send a message and return the reply stream's events."""
    body: dict[str, object] = {"content": content, "timezone": timezone}
    if attachments is not None:
        body["attachments"] = attachments
    response = await harness.client.post(
        f"{API}/threads/{thread_id}/messages", json=body, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in response.text.splitlines() if line]


async def main_thread(harness: "AssistantHarness", headers: dict[str, str]) -> str:
    response = await harness.client.post(f"{API}/threads/main", headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


async def run_now(
    harness: "AssistantHarness", headers: dict[str, str], schedule_id: str
) -> dict[str, Any]:
    """Run a schedule now, wait for the run to finish, and return it."""
    started = await harness.client.post(f"{API}/schedules/{schedule_id}/runs", headers=headers)
    assert started.status_code == 202, started.text
    assert started.json()["status"] == "running"
    await harness.container.background.wait()
    finished = await harness.client.get(
        f"{API}/schedules/{schedule_id}/runs/{started.json()['id']}", headers=headers
    )
    run: dict[str, Any] = finished.json()
    return run


async def connect_app(
    harness: "AssistantHarness", principal_id: uuid.UUID, headers: dict[str, str], slug: str
) -> None:
    """Connect an app as the Tools screen would: Composio holds an account, and the API has
    seen it connected."""
    harness.composio.add_account(principal_id, slug)
    response = await harness.client.get(f"{API}/tools/{slug}/connection", headers=headers)
    assert response.json()["status"] == "connected", response.text


def disconnect_in_composio(harness: "AssistantHarness", slug: str) -> None:
    """The account disappears in Composio, as when the user revokes access elsewhere; the
    API still remembers the app as connected until it checks again."""
    for account_id, stored in list(harness.composio.accounts.items()):
        if stored.account.toolkit_slug == slug:
            del harness.composio.accounts[account_id]


async def confirmed_schedule(
    harness: "AssistantHarness", headers: dict[str, str], **proposal: object
) -> dict[str, Any]:
    """Have the assistant propose a schedule in the main thread, and confirm it."""
    arguments: dict[str, object] = {
        "title": "Morning news",
        "task": "Summarize the three most important AI news stories of the last day.",
        "frequency": "daily",
        "time": "08:00",
        "summary": "Every day at 8:00 I will post the AI news here.",
        **proposal,
    }
    thread_id = await main_thread(harness, headers)
    harness.model.script(call("propose_schedule", arguments), say("Confirm to start."))
    events = await stream(harness, headers, thread_id, "Do this regularly")
    message_id = events[-1]["message"]["id"]
    response = await harness.client.post(
        f"{API}/threads/{thread_id}/messages/{message_id}/proposal/confirm", headers=headers
    )
    assert response.status_code == 201, response.text
    schedule: dict[str, Any] = response.json()["schedule"]
    return schedule
