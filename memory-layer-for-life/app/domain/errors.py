"""Domain errors.

These carry no HTTP knowledge. The API layer maps them to responses, and the pipeline
uses ``ExtractionError.retryable`` to decide between a bounded retry and a terminal
state. Messages must stay free of message content and provider payloads, because they
are persisted on processing runs and written to logs.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for rule violations and pipeline failures."""

    code: ClassVar[str] = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class RecordNotFoundError(DomainError):
    """A record addressed by id does not exist."""

    code = "NOT_FOUND"

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} not found: {identifier}")


class InvalidProcessingUnitError(DomainError):
    """A processing unit is empty or lists the same message twice."""

    code = "INVALID_PROCESSING_UNIT"


class SourceContentConflictError(DomainError):
    """A source identity was redelivered with different content.

    Raw messages are immutable evidence, so the stored content is never overwritten.
    """

    code = "SOURCE_CONTENT_CONFLICT"


class IllegalRunTransitionError(DomainError):
    """A processing run was asked to move between two states that are not connected."""

    code = "ILLEGAL_RUN_TRANSITION"


class ExtractionError(DomainError):
    """Base class for failures of the extraction stage."""

    code = "EXTRACTION_FAILED"
    retryable: ClassVar[bool] = False


class TransientExtractionError(ExtractionError):
    """Timeouts, rate limits, overload, and connection failures. Safe to retry later."""

    code = "EXTRACTION_TRANSIENT_FAILURE"
    retryable = True


class PermanentExtractionError(ExtractionError):
    """Failures a retry cannot fix, such as rejected credentials or a rejected request."""

    code = "EXTRACTION_PERMANENT_FAILURE"


class ExtractionBillingError(PermanentExtractionError):
    """The provider account cannot pay for the call.

    Nothing can be processed until the account owner acts. The failed runs keep their
    input and can be replayed afterwards.
    """

    code = "EXTRACTION_PROVIDER_BILLING"


class ExtractionRefusedError(PermanentExtractionError):
    """The provider declined to process the content."""

    code = "EXTRACTION_REFUSED"


class ExtractionTruncatedError(PermanentExtractionError):
    """The provider stopped before completing the structured output."""

    code = "EXTRACTION_TRUNCATED"


class InvalidExtractionOutputError(ExtractionError):
    """The provider answered, but the output failed contract or grounding validation.

    Model output is untrusted input. Invalid output is never persisted as an extraction
    result; the run is sent to review instead.
    """

    code = "EXTRACTION_OUTPUT_INVALID"

    def __init__(self, message: str, *, raw_output: str | None = None) -> None:
        super().__init__(message)
        # What the model returned. It can quote the source messages, so it is kept apart
        # from ``message``: it is shown to the person testing, never logged or stored on
        # a processing run.
        self.raw_output = raw_output


class ProviderNotConfiguredError(DomainError):
    """A model call was requested but no provider API key is configured."""

    code = "PROVIDER_NOT_CONFIGURED"

    def __init__(self) -> None:
        super().__init__("No model provider is configured. Set ANTHROPIC_API_KEY to enable it.")


class UnsupportedModelError(DomainError):
    """A model was requested that the application does not offer."""

    code = "UNSUPPORTED_MODEL"

    def __init__(self, model: str) -> None:
        super().__init__(f"Model '{model}' is not offered. Choose one of the listed models.")


class EvaluationDatasetUnavailableError(DomainError):
    """The golden dataset is missing or cannot be read on this machine."""

    code = "EVALUATION_DATASET_UNAVAILABLE"


class InvalidEvaluationSelectionError(DomainError):
    """An evaluation was asked to run cases that the dataset does not contain."""

    code = "INVALID_EVALUATION_SELECTION"


class EvaluationInProgressError(DomainError):
    """An evaluation is already running in this process. One runs at a time."""

    code = "EVALUATION_IN_PROGRESS"

    def __init__(self) -> None:
        super().__init__("An evaluation is already running. Wait for it or cancel it first.")


class EvaluationNotRunningError(DomainError):
    """A run was asked to stop, but this process is not running it."""

    code = "EVALUATION_NOT_RUNNING"

    def __init__(self) -> None:
        super().__init__("This evaluation is not running in this process.")


# --- Assistant app ------------------------------------------------------------------


class AuthenticationRequiredError(DomainError):
    """The request carries no valid access token for a signed-in user."""

    code = "AUTHENTICATION_REQUIRED"


class AccessNotAllowedError(DomainError):
    """A signed-in user who is not on this deployment's access list."""

    code = "ACCESS_NOT_ALLOWED"

    def __init__(self) -> None:
        super().__init__(
            "This Muse is private, and your account is not on its access list. Ask its "
            "owner to add your email address."
        )


class OperatorAccessDeniedError(DomainError):
    """An operator route was called from another computer without the operator key."""

    code = "OPERATOR_ACCESS_DENIED"

    def __init__(self) -> None:
        super().__init__(
            "This part of the API only answers the computer it runs on. Open the console at "
            "http://localhost, or send the operator key in the X-Operator-Key header."
        )


class AuthenticationNotConfiguredError(DomainError):
    """The API cannot verify users because Supabase is not configured."""

    code = "AUTHENTICATION_NOT_CONFIGURED"

    def __init__(self) -> None:
        super().__init__("User sign-in is not configured. Set SUPABASE_URL to enable it.")


class IntegrationNotConfiguredError(DomainError):
    """An external service is needed but its key is not configured."""

    code = "INTEGRATION_NOT_CONFIGURED"

    def __init__(self, service: str, setting: str) -> None:
        self.service = service
        super().__init__(f"{service} is not configured. Set {setting} to enable it.")


class IntegrationError(DomainError):
    """An external service failed or answered with something unusable.

    Messages are written by the application. The service's own error text can echo the
    request, so it is never copied into a message that is stored or shown.
    """

    code = "INTEGRATION_FAILED"

    def __init__(self, service: str, message: str) -> None:
        self.service = service
        super().__init__(f"{service}: {message}")


class ChatTurnInProgressError(DomainError):
    """A thread already has an assistant turn running. One runs at a time per thread."""

    code = "CHAT_TURN_IN_PROGRESS"

    def __init__(self) -> None:
        super().__init__("The assistant is still answering in this thread. Wait for it to finish.")


class ProtectedThreadError(DomainError):
    """The main thread cannot be deleted."""

    code = "PROTECTED_THREAD"

    def __init__(self) -> None:
        super().__init__("The main thread cannot be deleted.")


class InvalidChatMessageError(DomainError):
    """A chat message is empty or too long."""

    code = "INVALID_CHAT_MESSAGE"


class ScheduleProposalError(DomainError):
    """A message has no pending schedule proposal to confirm or dismiss."""

    code = "SCHEDULE_PROPOSAL_UNAVAILABLE"


class JobApplicationDraftError(DomainError):
    """A message has no sendable job application draft card."""

    code = "JOB_APPLICATION_DRAFT_UNAVAILABLE"


class InvalidScheduleError(DomainError):
    """A schedule rule, timezone, or status change is not valid."""

    code = "INVALID_SCHEDULE"


class ScheduleRunInProgressError(DomainError):
    """The schedule already has a run in progress. One runs at a time per schedule."""

    code = "SCHEDULE_RUN_IN_PROGRESS"

    def __init__(self) -> None:
        super().__init__("This schedule is already running. Wait for the run to finish.")


class AssistantModelError(DomainError):
    """The model behind the assistant failed or gave an unusable answer.

    ``retryable`` says whether the same request can succeed later without anyone acting.
    """

    code = "ASSISTANT_MODEL_FAILED"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AssistantBillingError(AssistantModelError):
    """The provider account cannot pay for the call."""

    code = "ASSISTANT_PROVIDER_BILLING"


class AssistantRefusedError(AssistantModelError):
    """The model declined to answer."""

    code = "ASSISTANT_REFUSED"


class AssistantTruncatedError(AssistantModelError):
    """The answer hit a size limit before it was complete."""

    code = "ASSISTANT_TRUNCATED"


class ScheduleDeliveryError(DomainError):
    """A scheduled run could not deliver its result where the schedule says."""

    code = "SCHEDULE_DELIVERY_FAILED"


class ScheduleRunInterruptedError(DomainError):
    """The process running a scheduled task stopped before the run finished."""

    code = "SCHEDULE_RUN_INTERRUPTED"

    def __init__(self) -> None:
        super().__init__("The run was interrupted before it finished.")


class ScheduleSlotMissedError(DomainError):
    """A slot came due while nothing was dispatching schedules, and was too late to run
    once dispatching resumed. Recorded on the skipped run."""

    code = "SCHEDULE_SLOT_MISSED"

    def __init__(self) -> None:
        super().__init__(
            "Skipped: the assistant's server wasn't running at the scheduled time, and it was "
            "too late to run when it came back."
        )


class ScheduleSlotBusyError(DomainError):
    """A slot came due while an earlier run of the same task was still going."""

    code = "SCHEDULE_SLOT_BUSY"

    def __init__(self) -> None:
        super().__init__("Skipped: an earlier run of this schedule was still going.")


class QuotaExceededError(DomainError):
    """The user has used today's prompts."""

    code = "QUOTA_EXCEEDED"


class InvalidRetrievalQueryError(DomainError):
    """A memory search is empty, too long, or has contradictory filters."""

    code = "INVALID_RETRIEVAL_QUERY"


class InvalidMemoryChangeError(DomainError):
    """A change to a memory or a person is not valid: empty text, nothing changed, or a
    memory merged with itself."""

    code = "INVALID_MEMORY_CHANGE"


class MemoryStateError(DomainError):
    """A memory is not in a state that allows the change, such as editing a version that
    a newer one has replaced."""

    code = "MEMORY_STATE_CONFLICT"


class InvalidImportError(DomainError):
    """An imported file is not something the app can read, or was imported already."""

    code = "INVALID_IMPORT"


class FileReadError(DomainError):
    """A file could not be read into text (the model failed or refused)."""

    code = "FILE_READ_FAILED"


class InvalidAttachmentError(DomainError):
    """An attached file is of an unsupported type, too large, or not valid base64."""

    code = "INVALID_ATTACHMENT"
