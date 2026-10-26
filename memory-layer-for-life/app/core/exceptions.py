from typing import Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domain.errors import (
    AccessNotAllowedError,
    AttachmentUnavailableError,
    AuthenticationNotConfiguredError,
    AuthenticationRequiredError,
    ChatTurnInProgressError,
    DocumentStorageFullError,
    DomainError,
    EvaluationDatasetUnavailableError,
    EvaluationInProgressError,
    EvaluationNotRunningError,
    FileReadError,
    IllegalRunTransitionError,
    IntegrationError,
    IntegrationNotConfiguredError,
    InvalidAttachmentError,
    InvalidChatMessageError,
    InvalidDocumentError,
    InvalidEvaluationSelectionError,
    InvalidImportError,
    InvalidLinkError,
    InvalidMemoryChangeError,
    InvalidProcessingUnitError,
    InvalidRetrievalQueryError,
    InvalidScheduleError,
    JobApplicationDraftError,
    MemoryStateError,
    OperatorAccessDeniedError,
    ProtectedThreadError,
    ProviderNotConfiguredError,
    QuotaExceededError,
    RecordNotFoundError,
    ScheduleProposalError,
    ScheduleRunInProgressError,
    SourceContentConflictError,
    UnsupportedModelError,
)

logger = structlog.get_logger(__name__)

# --- Exception Classes ---


class AppException(Exception):  # noqa: N818 - established public name
    """Base application exception."""

    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR", status_code: int = 500):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} not found: {identifier}",
            error_code="NOT_FOUND",
            status_code=404,
        )


class ConflictError(AppException):
    def __init__(self, message: str):
        super().__init__(message=message, error_code="CONFLICT", status_code=409)


class ValidationError(AppException):
    def __init__(self, message: str):
        super().__init__(message=message, error_code="VALIDATION_ERROR", status_code=422)


class ExternalServiceError(AppException):
    def __init__(self, service: str, message: str):
        super().__init__(
            message=f"{service} error: {message}",
            error_code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
        )


# --- Error Response Schema ---


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    detail: str | None = None


# --- Domain error mapping ---

# Domain errors know nothing about HTTP. This table is the single place that decides how
# each one is reported to an API client.
_DOMAIN_STATUS_CODES: Final[dict[type[DomainError], int]] = {
    RecordNotFoundError: 404,
    SourceContentConflictError: 409,
    IllegalRunTransitionError: 409,
    InvalidProcessingUnitError: 422,
    UnsupportedModelError: 422,
    InvalidEvaluationSelectionError: 422,
    EvaluationInProgressError: 409,
    EvaluationNotRunningError: 409,
    EvaluationDatasetUnavailableError: 409,
    ProviderNotConfiguredError: 503,
    AuthenticationRequiredError: 401,
    AccessNotAllowedError: 403,
    OperatorAccessDeniedError: 403,
    AuthenticationNotConfiguredError: 503,
    IntegrationNotConfiguredError: 503,
    IntegrationError: 502,
    ChatTurnInProgressError: 409,
    ProtectedThreadError: 409,
    InvalidChatMessageError: 422,
    ScheduleProposalError: 409,
    JobApplicationDraftError: 409,
    InvalidScheduleError: 422,
    ScheduleRunInProgressError: 409,
    QuotaExceededError: 429,
    InvalidAttachmentError: 422,
    InvalidRetrievalQueryError: 422,
    InvalidMemoryChangeError: 422,
    MemoryStateError: 409,
    InvalidImportError: 422,
    InvalidDocumentError: 422,
    DocumentStorageFullError: 413,
    InvalidLinkError: 422,
    AttachmentUnavailableError: 409,
    FileReadError: 502,
}
_DEFAULT_DOMAIN_STATUS_CODE: Final = 400

_MAX_VALIDATION_DETAILS: Final = 10


def domain_status_code(error: DomainError) -> int:
    for error_type in type(error).__mro__:
        if error_type in _DOMAIN_STATUS_CODES:
            return _DOMAIN_STATUS_CODES[error_type]
    return _DEFAULT_DOMAIN_STATUS_CODE


def describe_request_errors(error: RequestValidationError) -> str:
    """List what is wrong with a request without echoing what was sent.

    Submitted values are left out on purpose: request bodies carry personal messages.
    """
    details = [
        f"{'.'.join(str(part) for part in item.get('loc', ())) or '<request>'}: "
        f"{item.get('msg', 'invalid')}"
        for item in error.errors()[:_MAX_VALIDATION_DETAILS]
    ]
    return "; ".join(details)


def _domain_error_headers(error: DomainError, status_code: int) -> dict[str, str] | None:
    if status_code == 401:
        # RFC 6750: a 401 names the scheme the client should use.
        return {"WWW-Authenticate": "Bearer"}
    return None


# --- Exception Handlers ---


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "application_error",
            error_code=exc.error_code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error_code=exc.error_code, message=exc.message).model_dump(),
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        logger.warning("domain_error", error_code=exc.code, path=request.url.path)
        status_code = domain_status_code(exc)
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(error_code=exc.code, message=exc.message).model_dump(),
            headers=_domain_error_headers(exc, status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error_code="VALIDATION_ERROR",
                message="The request is not valid.",
                detail=describe_request_errors(exc),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", exc_info=exc, path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
            ).model_dump(),
        )
