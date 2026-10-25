"""Error handlers, logging, health checks, and small defensive paths."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import logging as app_logging
from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationError, register_exception_handlers
from app.domain.enums import ExtractionDisposition
from app.domain.errors import PermanentExtractionError, SourceContentConflictError
from app.integrations.extraction.base import ExtractionMessage, ExtractionRequest
from app.repositories.message_repository import MessageRepository, NewRawMessage
from app.services.health import HealthService
from app.services.queries import _extraction_disposition
from evaluation.fixture_extractor import GoldenFixtureExtractor
from evaluation.golden import GoldenCase, GoldenExpectedMemory, load_golden_cases
from evaluation.judge import AnthropicJudge, JudgeError
from evaluation.report import build_report, render_markdown
from evaluation.runner import CaseResult, EvaluationRun
from evaluation.scoring import score_case
from tests.support.extraction import abstention, extraction
from tests.unit.test_evaluation import make_case

# --- Exception handlers ---------------------------------------------------------------


@pytest.fixture
async def failing_api() -> Any:
    application = FastAPI()
    register_exception_handlers(application)

    @application.get("/app-error")
    async def app_error() -> None:
        raise ConflictError("Already there")

    @application.get("/validation-error")
    async def validation_error() -> None:
        raise ValidationError("Not acceptable")

    @application.get("/domain-error")
    async def domain_error() -> None:
        raise SourceContentConflictError("Different content")

    @application.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail")

    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_application_errors_use_the_standard_shape(failing_api: AsyncClient) -> None:
    response = await failing_api.get("/app-error")

    assert response.status_code == 409
    assert response.json() == {"error_code": "CONFLICT", "message": "Already there", "detail": None}
    assert (await failing_api.get("/validation-error")).status_code == 422


async def test_domain_errors_use_the_standard_shape(failing_api: AsyncClient) -> None:
    response = await failing_api.get("/domain-error")

    assert response.status_code == 409
    assert response.json() == {
        "error_code": "SOURCE_CONTENT_CONFLICT",
        "message": "Different content",
        "detail": None,
    }


async def test_unexpected_errors_do_not_leak_details(failing_api: AsyncClient) -> None:
    response = await failing_api.get("/crash")

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred.",
        "detail": None,
    }
    assert "secret internal detail" not in response.text


# --- Logging --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "renderer"),
    [
        ("production", structlog.processors.JSONRenderer),
        ("development", structlog.dev.ConsoleRenderer),
    ],
)
def test_logging_renderer_follows_the_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str, renderer: type
) -> None:
    deployed = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@db.example.com/app?ssl=require",
        "SUPABASE_URL": "https://abc.supabase.co",
        "ANTHROPIC_API_KEY": "sk-ant-test",
    }
    settings = Settings(_env_file=None, ENVIRONMENT=environment, **deployed)  # type: ignore[call-arg]
    monkeypatch.setattr(app_logging, "get_settings", lambda: settings)
    try:
        app_logging.setup_logging()

        assert isinstance(structlog.get_config()["processors"][-1], renderer)
        assert app_logging.get_logger("test") is not None
    finally:
        structlog.reset_defaults()


# --- Health ---------------------------------------------------------------------------


async def test_health_service_reports_an_unreachable_database() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=ConnectionRefusedError("no route to host 10.0.0.5"))

    healthy, detail = await HealthService(session).check_database()

    assert healthy is False
    # The exception type is reported. Its message, which can name hosts, is not.
    assert detail == "connection failed: ConnectionRefusedError"


async def test_health_service_reports_a_reachable_database() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    assert await HealthService(session).check_database() == (True, "connected")


# --- Defensive paths ------------------------------------------------------------------


async def test_idempotent_insert_needs_a_source_identity() -> None:
    repository = MessageRepository(MagicMock())
    new = NewRawMessage(source="api_input", content="x", content_sha256="0" * 64)

    with pytest.raises(ValueError, match="source_message_id"):
        await repository.add_if_absent(new, now=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"output": {"disposition": "context"}}, ExtractionDisposition.CONTEXT),
        ({"output": {"disposition": "something_else"}}, None),
        ({"output": {"disposition": 7}}, None),
        ({"output": "not an object"}, None),
        ({}, None),
    ],
)
def test_disposition_is_read_tolerantly_from_stored_payloads(
    payload: dict[str, Any], expected: ExtractionDisposition | None
) -> None:
    assert _extraction_disposition(payload) is expected


async def test_fixture_extractor_refuses_unknown_input() -> None:
    extractor = GoldenFixtureExtractor([make_case()])
    unknown = ExtractionRequest(
        messages=(ExtractionMessage(index=0, text="never seen", sent_at_local=None),)
    )

    with pytest.raises(PermanentExtractionError):
        await extractor.extract(unknown)
    assert len(extractor.requests) == 1


def test_fixture_extractor_quotes_long_messages_briefly() -> None:
    case = make_case(texts=("word " * 60,))
    extractor = GoldenFixtureExtractor([case])

    (extracted,) = extractor.expected_output(case).memories

    assert len(extracted.evidence[0].quote) <= 80
    assert extracted.evidence[0].quote in case.input.messages[0].content


def test_dataset_loader_skips_blank_lines(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = make_case()
    line = json.dumps(case.model_dump(mode="json"))
    path = tmp_path / "golden.jsonl"
    path.write_text(f"\n{line}\n\n", encoding="utf-8")

    assert [loaded.case_id for loaded in load_golden_cases(path)] == ["case_1"]


def test_dataset_loader_rejects_duplicate_case_ids(tmp_path) -> None:  # type: ignore[no-untyped-def]
    line = json.dumps(make_case().model_dump(mode="json"))
    path = tmp_path / "golden.jsonl"
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate case_id"):
        load_golden_cases(path)


def test_expected_memory_rejects_a_non_object() -> None:
    with pytest.raises(ValueError, match="GoldenExpectedMemory"):
        GoldenExpectedMemory.model_validate("just text")


def test_fixture_extractor_mentions_only_names_found_in_the_messages() -> None:
    case = make_case(
        attributes={"participants": ["Harsh", "Ghost"], "counterparty": "Harsh"},
        texts=("400/2 - petrol harsh",),
    )
    extractor = GoldenFixtureExtractor([case])

    output = extractor.expected_output(case)

    # "Ghost" is in the label but not in the message, so it cannot be a mention.
    assert [item.mention_text for item in output.entity_mentions] == ["harsh"]
    assert output.memories[0].entity_mention_indexes == [0]


# --- Judge provider failures ----------------------------------------------------------

HTTP_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(error_type: type[anthropic.APIStatusError], status: int) -> Exception:
    return error_type("no", response=httpx2.Response(status, request=HTTP_REQUEST), body=None)


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        pytest.param(anthropic.APITimeoutError(request=HTTP_REQUEST), True, id="timeout"),
        pytest.param(
            anthropic.APIConnectionError(message="down", request=HTTP_REQUEST),
            True,
            id="connection",
        ),
        pytest.param(_status_error(anthropic.RateLimitError, 429), True, id="rate limit"),
        pytest.param(_status_error(anthropic.InternalServerError, 503), True, id="server error"),
        pytest.param(_status_error(anthropic.BadRequestError, 400), False, id="bad request"),
        pytest.param(_status_error(anthropic.AuthenticationError, 401), False, id="bad key"),
    ],
)
async def test_judge_classifies_provider_errors(error: Exception, retryable: bool) -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=error)
    judge = AnthropicJudge(client, model="claude-haiku-5-5")
    case = make_case()

    with pytest.raises(JudgeError) as raised:
        await judge.judge(case, case.expected.memories[0], extraction())

    assert raised.value.retryable is retryable


async def test_judge_names_an_account_that_cannot_pay() -> None:
    body = {"type": "error", "error": {"type": "billing_error", "message": "Payment required"}}
    error = anthropic.APIStatusError(
        "Payment required", response=httpx2.Response(402, request=HTTP_REQUEST), body=body
    )
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=error)
    judge = AnthropicJudge(client, model="claude-haiku-5-5")
    case = make_case()

    with pytest.raises(JudgeError, match="no credit left") as raised:
        await judge.judge(case, case.expected.memories[0], extraction())

    assert raised.value.retryable is False


# --- Report rendering of failures -----------------------------------------------------


def _run_of(*results: CaseResult) -> EvaluationRun:
    return EvaluationRun(
        results=results, extractor_model="m", extractor_version="scripted:1", judge_model="j"
    )


def _failed_result(case: GoldenCase, output: Any = None, error: str | None = None) -> CaseResult:
    return CaseResult(case, score_case(case, output, error=error), output=output, error=error)


def test_report_shows_a_case_whose_extraction_failed() -> None:
    case = make_case(case_id="broken_1")
    run = _run_of(_failed_result(case, error="EXTRACTION_REFUSED: declined"))

    markdown = render_markdown(build_report(run, generated_at=datetime(2026, 1, 1, tzinfo=UTC)))

    assert "### broken_1" in markdown
    assert "- Produced: nothing (EXTRACTION_REFUSED: declined)" in markdown
    assert "FAILED valid_output" in markdown


def test_report_shows_a_missed_abstention_and_a_wrong_abstention() -> None:
    should_abstain = make_case(case_id="abstain_1", outcome="abstain", texts=("14 15",))
    should_extract = make_case(case_id="extract_1")
    run = _run_of(
        _failed_result(should_abstain, extraction()), _failed_result(should_extract, abstention())
    )

    report = build_report(run, generated_at=datetime(2026, 1, 1, tzinfo=UTC))
    markdown = render_markdown(report)

    assert report["summary"]["failed_case_ids"] == ["abstain_1", "extract_1"]
    assert "- Expected: abstain" in markdown
    assert "- Produced disposition: abstain" in markdown
    assert "abstained although a memory was expected" in markdown
