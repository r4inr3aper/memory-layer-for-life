from typing import Any

import pytest
from fastapi.exceptions import RequestValidationError

from app.core.exceptions import (
    AppException,
    ConflictError,
    ErrorResponse,
    ExternalServiceError,
    NotFoundError,
    describe_request_errors,
    domain_status_code,
)
from app.domain.errors import (
    DomainError,
    ExtractionBillingError,
    ExtractionError,
    ExtractionRefusedError,
    ExtractionTruncatedError,
    IllegalRunTransitionError,
    InvalidExtractionOutputError,
    InvalidProcessingUnitError,
    PermanentExtractionError,
    RecordNotFoundError,
    SourceContentConflictError,
    TransientExtractionError,
)


def test_app_exception_base() -> None:
    exc = AppException(message="Test error", error_code="TEST", status_code=400)

    assert exc.message == "Test error"
    assert exc.error_code == "TEST"
    assert exc.status_code == 400
    assert str(exc) == "Test error"


def test_not_found_error() -> None:
    exc = NotFoundError(resource="User", identifier="123")

    assert exc.message == "User not found: 123"
    assert exc.error_code == "NOT_FOUND"
    assert exc.status_code == 404


def test_conflict_error() -> None:
    exc = ConflictError(message="Conflict occurred")

    assert exc.message == "Conflict occurred"
    assert exc.error_code == "CONFLICT"
    assert exc.status_code == 409


def test_external_service_error() -> None:
    exc = ExternalServiceError(service="Anthropic", message="Timeout")

    assert exc.message == "Anthropic error: Timeout"
    assert exc.error_code == "EXTERNAL_SERVICE_ERROR"
    assert exc.status_code == 502


def test_error_response_schema() -> None:
    response = ErrorResponse(error_code="TEST", message="Test message", detail="Detailed error")

    assert response.model_dump() == {
        "error_code": "TEST",
        "message": "Test message",
        "detail": "Detailed error",
    }


# --- Domain errors --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (RecordNotFoundError("Memory", "abc"), 404),
        (SourceContentConflictError("different content"), 409),
        (IllegalRunTransitionError("not allowed"), 409),
        (InvalidProcessingUnitError("empty"), 422),
        (DomainError("something else"), 400),
        (PermanentExtractionError("provider"), 400),
    ],
)
def test_domain_errors_map_to_http_statuses(error: DomainError, status: int) -> None:
    assert domain_status_code(error) == status


def test_domain_errors_carry_a_stable_code_and_message() -> None:
    error = RecordNotFoundError("Processing run", "42")

    assert error.code == "NOT_FOUND"
    assert error.message == "Processing run not found: 42"
    assert str(error) == error.message


def test_domain_error_codes_are_unique() -> None:
    types = [
        DomainError,
        RecordNotFoundError,
        InvalidProcessingUnitError,
        SourceContentConflictError,
        IllegalRunTransitionError,
        ExtractionError,
        TransientExtractionError,
        PermanentExtractionError,
        ExtractionBillingError,
        ExtractionRefusedError,
        ExtractionTruncatedError,
        InvalidExtractionOutputError,
    ]

    assert len({error_type.code for error_type in types}) == len(types)


def test_only_transient_extraction_errors_are_retryable() -> None:
    assert TransientExtractionError("x").retryable is True
    for error_type in (
        ExtractionError,
        PermanentExtractionError,
        ExtractionBillingError,
        ExtractionRefusedError,
        ExtractionTruncatedError,
        InvalidExtractionOutputError,
    ):
        assert error_type("x").retryable is False


def test_request_errors_are_described_without_the_submitted_values() -> None:
    errors: list[dict[str, Any]] = [
        {
            "type": "enum",
            "loc": ("body", "messages", 0, "source"),
            "msg": "Input should be 'whatsapp_import', 'manual_capture' or 'api_input'",
            "input": "my private text",
        },
        {"type": "missing", "loc": ("body", "messages", 0, "content"), "msg": "Field required"},
    ]

    description = describe_request_errors(RequestValidationError(errors))

    assert "body.messages.0.source: Input should be" in description
    assert "body.messages.0.content: Field required" in description
    assert "my private text" not in description
