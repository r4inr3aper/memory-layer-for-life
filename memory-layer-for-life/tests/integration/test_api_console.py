"""The console's HTTP surface, served in-process with scripted doubles."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.bootstrap import AppContainer, build_container
from app.core.config import PROJECT_ROOT, Settings
from app.domain.enums import LlmCallStatus
from app.integrations.anthropic_ping import ProviderCheckError
from app.services.llm_call_log import LlmCallLog
from tests.integration.conftest import _serve
from tests.support.call_log import T0, FakeProviderCheck, make_record
from tests.support.datasets import three_cases, write_dataset
from tests.support.extraction import ScriptedExtractor
from tests.support.pipeline import FakeClock
from tests.unit.test_evaluation import ScriptedJudge, expense, verdict

SessionFactory = async_sessionmaker[AsyncSession]
API = "/api/v1"


@dataclass
class ConsoleHarness:
    client: AsyncClient
    extractor: ScriptedExtractor
    container: AppContainer
    provider_check: FakeProviderCheck


@pytest_asyncio.fixture
async def console(
    settings: Settings, engine: AsyncEngine, clock: FakeClock, tmp_path: Path
) -> AsyncIterator[ConsoleHarness]:
    """The API with a synthetic dataset and scripted model doubles."""
    dataset = write_dataset(tmp_path / "golden.jsonl", three_cases())
    custom = settings.model_copy(update={"EVALUATION_DATASET_PATH": str(dataset)})
    extractor = ScriptedExtractor(expense())
    check = FakeProviderCheck()
    container = build_container(
        custom,
        extractor=extractor,
        judge=ScriptedJudge(verdict()),
        provider_check=check,
        clock=clock,
    )
    async with _serve(container) as client:
        yield ConsoleHarness(client, extractor, container, check)


# --- Console ---------------------------------------------------------------------------


async def test_the_config_describes_the_deployment_without_secrets(
    console: ConsoleHarness,
) -> None:
    response = await console.client.get(f"{API}/console/config")

    assert response.status_code == 200
    body = response.json()
    settings = console.container.settings
    assert body["provider_configured"] is True
    assert body["default_model"] == settings.ANTHROPIC_MODEL
    assert body["default_effort"] == settings.EXTRACTION_EFFORT
    assert body["default_timezone"] == settings.DEFAULT_TIMEZONE
    assert body["effort_levels"] == ["low", "medium", "high", "xhigh", "max"]
    assert [model["id"] for model in body["models"]][:3] == [
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]
    assert body["models"][1]["prices"]["input_usd_per_mtok"] == 2.0
    assert body["models"][0]["supports_refusal_fallback"] is False
    assert any(model["is_default"] for model in body["models"])
    assert body["prices_checked_on"] == "2026-10-12"
    assert body["pipeline"]["extractor_provider"] == "scripted"
    assert body["limits"]["max_unit_messages"] == settings.INGESTION_MAX_UNIT_MESSAGES
    assert (body["evaluation_running"], body["dataset_available"]) == (False, True)
    assert "ANTHROPIC_API_KEY" not in response.text
    assert "sk-ant" not in response.text


async def test_a_connection_check_reports_its_outcome(console: ConsoleHarness) -> None:
    default_model = console.container.settings.ANTHROPIC_MODEL

    ok = await console.client.post(f"{API}/console/connection-check", json={})
    assert ok.status_code == 200
    assert (ok.json()["ok"], ok.json()["model"]) == (True, default_model)
    assert console.provider_check.models == [default_model]

    console.provider_check.failure = ProviderCheckError("The Anthropic API could not be reached.")
    failed = await console.client.post(
        f"{API}/console/connection-check", json={"model": "claude-haiku-5-5"}
    )
    assert failed.status_code == 200
    assert failed.json()["ok"] is False
    assert failed.json()["error_code"] == "PROVIDER_CHECK_FAILED"
    assert failed.json()["error_message"] == "The Anthropic API could not be reached."

    unknown = await console.client.post(f"{API}/console/connection-check", json={"model": "gpt-9"})
    assert unknown.status_code == 422
    assert unknown.json()["error_code"] == "UNSUPPORTED_MODEL"


async def test_a_connection_check_without_a_provider_is_unavailable(
    api_without_extractor: AsyncClient,
) -> None:
    response = await api_without_extractor.post(f"{API}/console/connection-check", json={})

    assert response.status_code == 503
    assert response.json()["error_code"] == "PROVIDER_NOT_CONFIGURED"


async def test_pipeline_stats_count_what_the_pipeline_holds(console: ConsoleHarness) -> None:
    empty = (await console.client.get(f"{API}/console/pipeline-stats")).json()
    assert empty == {
        "raw_messages": 0,
        "entities": 0,
        "runs_by_status": {},
        "extractions_by_disposition": {},
        "memories_by_type": {},
        "memories_by_status": {},
        "mentions_by_resolution": {},
    }

    captured = await console.client.post(
        f"{API}/ingestion/units",
        json={"messages": [{"source": "api_input", "content": "500 petrol"}]},
    )
    assert captured.status_code == 202

    stats = (await console.client.get(f"{API}/console/pipeline-stats")).json()
    assert stats["raw_messages"] == 1
    assert stats["runs_by_status"] == {"succeeded": 1}
    assert stats["extractions_by_disposition"] == {"extract": 1}
    assert stats["memories_by_type"] == {"financial_note": 1}
    assert stats["memories_by_status"] == {"proposed": 1}


# --- Model calls ----------------------------------------------------------------------


async def test_model_calls_are_listed_summarized_and_inspected(
    console: ConsoleHarness, session_factory: SessionFactory
) -> None:
    log = LlmCallLog(session_factory)
    await log.record(make_record(started_at=T0))
    await log.record(make_record(started_at=T0 + timedelta(hours=1), status=LlmCallStatus.FAILED))

    listing = (await console.client.get(f"{API}/llm-calls")).json()
    assert listing["total"] == 2
    newest = listing["items"][0]
    assert (newest["status"], newest["error_code"]) == ("failed", "EXTRACTION_TRANSIENT_FAILURE")
    assert newest["estimated_cost_usd"] == 0.0015
    assert newest["requested_model"] == "claude-haiku-5-5"

    failed_only = (await console.client.get(f"{API}/llm-calls", params={"status": "failed"})).json()
    assert failed_only["total"] == 1

    usage = (await console.client.get(f"{API}/llm-calls/usage")).json()
    assert (usage["totals"]["calls"], usage["totals"]["failed_calls"]) == (2, 1)
    assert usage["totals"]["estimated_cost_usd"] == 0.003
    assert usage["by_model"] == [
        {
            "key": "claude-haiku-5-5",
            "calls": 2,
            "failed_calls": 1,
            "input_tokens": 20000,
            "output_tokens": 2000,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "estimated_cost_usd": 0.003,
            "unpriced_calls": 0,
            "average_duration_ms": 100.0,
        }
    ]
    assert [entry["key"] for entry in usage["by_origin"]] == ["other"]
    assert usage["errors"] == [
        {
            "error_code": "EXTRACTION_TRANSIENT_FAILURE",
            "calls": 1,
            "last_seen_at": (T0 + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
    ]
    assert usage["timezone"] == console.container.settings.DEFAULT_TIMEZONE
    assert usage["earlier_evaluations"] == {"runs": 0, "estimated_cost_usd": 0.0}
    assert usage["latency"]["p50_ms"] == 100.0

    detail = await console.client.get(f"{API}/llm-calls/{newest['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == newest["id"]
    assert (await console.client.get(f"{API}/llm-calls/{uuid.uuid4()}")).status_code == 404
    assert (
        await console.client.get(f"{API}/llm-calls", params={"status": "weird"})
    ).status_code == 422


# --- Playground -----------------------------------------------------------------------


async def test_a_test_extraction_is_made_listed_and_reopened(console: ConsoleHarness) -> None:
    response = await console.client.post(
        f"{API}/playground/extractions",
        json={
            "messages": [{"text": "500 petrol", "sent_at": "2026-10-12T03:30:00Z"}],
            "effort": "low",
            "timezone": "Asia/Kolkata",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["output"]["disposition"] == "extract"
    assert body["messages"][0]["text"] == "500 petrol"
    assert (body["effort"], body["timezone_name"]) == ("low", "Asia/Kolkata")
    assert body["call"] is None
    (request,) = console.extractor.requests
    assert request.messages[0].sent_at_local.isoformat() == "2026-10-12T09:00:00"

    listing = (await console.client.get(f"{API}/playground/extractions")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["preview"] == "500 petrol"
    assert listing["items"][0]["message_count"] == 1

    reopened = await console.client.get(f"{API}/playground/extractions/{body['id']}")
    assert reopened.status_code == 200
    assert reopened.json()["output"] == body["output"]
    assert (
        await console.client.get(f"{API}/playground/extractions/{uuid.uuid4()}")
    ).status_code == 404


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        pytest.param({"messages": []}, "VALIDATION_ERROR", id="no messages"),
        pytest.param(
            {"messages": [{"text": "x"}], "timezone": "Mars/Olympus_Mons"},
            "VALIDATION_ERROR",
            id="unknown timezone",
        ),
        pytest.param(
            {"messages": [{"text": "x"}], "effort": "extreme"}, "VALIDATION_ERROR", id="bad effort"
        ),
        pytest.param(
            {"messages": [{"text": "x"}], "model": "gpt-9"}, "UNSUPPORTED_MODEL", id="bad model"
        ),
        pytest.param({"messages": [{"text": "x"}], "extra": 1}, "VALIDATION_ERROR", id="extra"),
    ],
)
async def test_bad_test_requests_are_refused(
    console: ConsoleHarness, payload: dict[str, object], error_code: str
) -> None:
    response = await console.client.post(f"{API}/playground/extractions", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == error_code
    assert console.extractor.call_count == 0


async def test_a_test_extraction_without_a_provider_is_unavailable(
    api_without_extractor: AsyncClient,
) -> None:
    response = await api_without_extractor.post(
        f"{API}/playground/extractions", json={"messages": [{"text": "buy milk"}]}
    )

    assert response.status_code == 503


async def test_the_extraction_contract_is_published(console: ConsoleHarness) -> None:
    response = await console.client.get(f"{API}/playground/contract")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["pipeline_version"] == "1.0.0"
    assert "disposition" in body["output_schema"]["properties"]
    assert "disposition" in body["provider_schema"]["properties"]


# --- Evaluations ----------------------------------------------------------------------


async def test_an_evaluation_is_started_watched_and_inspected(console: ConsoleHarness) -> None:
    dataset = (await console.client.get(f"{API}/evaluations/dataset")).json()
    assert dataset["available"] is True
    assert dataset["case_count"] == 3
    assert dataset["cases"][0]["case_id"] == "pass_1"

    started = await console.client.post(
        f"{API}/evaluations", json={"case_ids": ["pass_1", "abstain_1"], "concurrency": 1}
    )
    assert started.status_code == 202
    body = started.json()
    assert body["status"] in {"running", "completed"}
    assert (body["cases_total"], body["trigger"]) == (2, "console")
    run_id = body["id"]

    await console.container.evaluation_service.wait()

    run = (await console.client.get(f"{API}/evaluations/{run_id}")).json()
    assert run["status"] == "completed"
    assert (run["cases_passed"], run["cases_failed"], run["cases_not_evaluated"]) == (1, 1, 0)
    assert (run["cases_done"], run["pass_rate"]) == (2, 0.5)
    assert run["extractor_model"] == "test-model"
    assert run["check_totals"]["abstention"] == {"evaluated": 2, "passed": 1}

    listing = (await console.client.get(f"{API}/evaluations")).json()
    assert listing["total"] == 1
    assert (await console.client.get(f"{API}/evaluations", params={"status": "running"})).json()[
        "total"
    ] == 0
    assert (
        await console.client.get(f"{API}/evaluations", params={"status": "bogus"})
    ).status_code == 422

    cases = (await console.client.get(f"{API}/evaluations/{run_id}/cases")).json()
    assert [(case["case_id"], case["outcome"]) for case in cases["items"]] == [
        ("pass_1", "passed"),
        ("abstain_1", "failed"),
    ]
    failed = (
        await console.client.get(f"{API}/evaluations/{run_id}/cases", params={"outcome": "failed"})
    ).json()
    assert failed["total"] == 1
    assert failed["items"][0]["failed_checks"] == ["abstention"]

    detail = (await console.client.get(f"{API}/evaluations/{run_id}/cases/abstain_1")).json()
    assert detail["document"]["messages"] == ["14 15"]
    assert detail["document"]["checks"][1]["name"] == "abstention"
    assert (await console.client.get(f"{API}/evaluations/{run_id}/cases/nope")).status_code == 404

    failing = (await console.client.get(f"{API}/evaluations/failing-cases")).json()
    assert failing == [{"case_id": "abstain_1", "failed": 1, "evaluated": 1}]

    cancel = await console.client.post(f"{API}/evaluations/{run_id}/cancel")
    assert cancel.status_code == 409
    assert cancel.json()["error_code"] == "EVALUATION_NOT_RUNNING"
    assert (await console.client.get(f"{API}/evaluations/{uuid.uuid4()}")).status_code == 404
    assert (
        await console.client.post(f"{API}/evaluations/{uuid.uuid4()}/cancel")
    ).status_code == 404
    assert (await console.client.get(f"{API}/console/config")).json()["evaluation_running"] is False


async def test_bad_evaluation_requests_are_refused(console: ConsoleHarness) -> None:
    unknown_case = await console.client.post(f"{API}/evaluations", json={"case_ids": ["nope"]})
    assert unknown_case.status_code == 422
    assert unknown_case.json()["error_code"] == "INVALID_EVALUATION_SELECTION"

    repeated = await console.client.post(
        f"{API}/evaluations", json={"case_ids": ["pass_1", "pass_1"]}
    )
    assert repeated.status_code == 422

    unknown_model = await console.client.post(
        f"{API}/evaluations", json={"extractor_model": "gpt-9"}
    )
    assert unknown_model.status_code == 422
    assert unknown_model.json()["error_code"] == "UNSUPPORTED_MODEL"

    assert console.extractor.call_count == 0
    assert (await console.client.get(f"{API}/evaluations")).json()["total"] == 0


async def test_an_evaluation_without_a_provider_is_unavailable(
    api_without_extractor: AsyncClient,
) -> None:
    response = await api_without_extractor.post(f"{API}/evaluations", json={})

    assert response.status_code == 503
    assert response.json()["error_code"] == "PROVIDER_NOT_CONFIGURED"


# --- Reports and the rest -------------------------------------------------------------


async def test_an_unknown_report_is_not_found(console: ConsoleHarness) -> None:
    response = await console.client.get(f"{API}/reports/nope")

    assert response.status_code == 404


async def test_the_phase_1_report_is_served(console: ConsoleHarness) -> None:
    if not (PROJECT_ROOT / "PHASE1_REPORT.md").is_file():
        pytest.skip("PHASE1_REPORT.md is not in this checkout")

    response = await console.client.get(f"{API}/reports/phase-1")

    assert response.status_code == 200
    assert response.json()["title"] == "Phase 1 report"
    assert response.json()["markdown"].startswith("#")


async def test_every_response_carries_a_request_id(console: ConsoleHarness) -> None:
    fresh = await console.client.get(f"{API}/health/live")
    echoed = await console.client.get(f"{API}/health/live", headers={"x-request-id": "ui-1"})

    assert len(fresh.headers["x-request-id"]) == 32
    assert echoed.headers["x-request-id"] == "ui-1"
