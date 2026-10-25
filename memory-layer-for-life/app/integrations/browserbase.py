"""Browserbase's REST API: hosted browser agent runs and their live view.


A browser task is handed to a Browserbase agent run, which drives a cloud browser until
the task is done and returns a structured result. While it runs, the session's live view
can be shown to the user, who can also take over, for example to sign in.
"""


from dataclasses import dataclass
from typing import Any, Final


import httpx
import structlog


from app.domain.errors import IntegrationError


logger = structlog.get_logger(__name__)


SERVICE_NAME: Final = "Browserbase"
TERMINAL_RUN_STATUSES: Final = frozenset({"COMPLETED", "FAILED", "STOPPED", "TIMED_OUT", "PAUSED"})
# Asked of every run, so the result can be read without guessing its shape.
_RESULT_SCHEMA: Final = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "The answer to the task, in plain words."},
        "sourceUrl": {"type": "string", "description": "The page the answer came from."},
        "loginRequired": {
            "type": "boolean",
            "description": "True only if signing in blocked the task.",
        },
    },
}




@dataclass(frozen=True, slots=True)
class BrowserRun:
    run_id: str
    status: str
    session_id: str | None
    summary: str | None
    source_url: str | None
    login_required: bool
    error: str | None


    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES




class BrowserbaseClient:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str, base_url: str) -> None:
        self._http = http
        self._api_key = api_key
        self._base_url = base_url


    async def start_run(self, task: str) -> BrowserRun:
        document = await self._request(
            "POST", "/v1/agents/runs", json={"task": task, "resultSchema": _RESULT_SCHEMA}
        )
        return parse_run(document)


    async def get_run(self, run_id: str) -> BrowserRun:
        return parse_run(await self._request("GET", f"/v1/agents/runs/{run_id}"))


    async def stop_run(self, run_id: str) -> None:
        """Ask Browserbase to stop a run, so an abandoned one does not keep a browser (and
        its bill) going. A run that already finished answers 409: nothing to stop."""
        await self._request("POST", f"/v1/agents/runs/{run_id}/stop", accept_statuses={409})


    async def live_view_url(self, session_id: str) -> str | None:
        document = await self._request("GET", f"/v1/sessions/{session_id}/debug")
        for key in ("debuggerFullscreenUrl", "debuggerUrl"):
            value = document.get(key)
            if isinstance(value, str) and value.startswith("https://"):
                return value
        return None


    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        accept_statuses: frozenset[int] | set[int] = frozenset(),
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers={"X-BB-API-Key": self._api_key, "Accept": "application/json"},
            )
        except httpx.TimeoutException as error:
            raise IntegrationError(SERVICE_NAME, "the request timed out.") from error
        except httpx.HTTPError as error:
            raise IntegrationError(SERVICE_NAME, "could not be reached.") from error


        status = response.status_code
        if status in accept_statuses:
            return {}
        if status in (401, 403):
            raise IntegrationError(SERVICE_NAME, f"rejected the API key (HTTP {status}).")
        if status >= 400:
            logger.warning("browserbase_request_failed", path=path, http_status=status)
            raise IntegrationError(SERVICE_NAME, f"rejected the request (HTTP {status}).")
        try:
            document = response.json()
        except ValueError as error:
            raise IntegrationError(
                SERVICE_NAME, "answered with something that is not JSON."
            ) from error
        if not isinstance(document, dict):
            raise IntegrationError(SERVICE_NAME, "answered with an unexpected shape.")
        return document




def parse_run(document: dict[str, Any]) -> BrowserRun:
    run_id = _text(document.get("runId")) or _text(document.get("id"))
    if run_id is None:
        raise IntegrationError(SERVICE_NAME, "returned an agent run without an id.")
    result = document.get("result")
    result = result if isinstance(result, dict) else {}
    # A failed run explains itself in ``cause`` ({code, message}).
    cause = document.get("cause")
    cause = cause if isinstance(cause, dict) else {}
    return BrowserRun(
        run_id=run_id,
        status=(_text(document.get("status")) or "RUNNING").upper(),
        session_id=_text(document.get("sessionId")),
        summary=_text(result.get("summary")) or _text(document.get("summary")),
        source_url=_text(result.get("sourceUrl")),
        login_required=result.get("loginRequired") is True,
        error=_text(cause.get("message"))
        or _text(cause.get("code"))
        or _text(document.get("error")),
    )




def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None



