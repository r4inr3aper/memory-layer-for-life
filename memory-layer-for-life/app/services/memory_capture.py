"""Chats become memories.

Each message a user sends goes through the memory pipeline, owned by that user, like any
other captured unit: stored as immutable evidence, then extracted, resolved against the
user's own entities only, and turned into memories that point back at the message.

* Only the user's own words are captured, never the assistant's replies: memories are
  about the user, and a reply restating a guess must not become a "fact".
* Messages of a word or two ("hi", "thanks") are skipped; they cost an extraction call
  and hold nothing to remember.
* Capture never affects the chat. It is scheduled after the message is stored and runs in
  the background; a failure is logged and the message stays stored. A run that failed is
  retried by the API's pipeline loop (``PipelineLoop``), or ``scripts/process_pending.py``.
* Users can turn it off for themselves (``memory_capture_enabled``), the operator for
  everyone (``MEMORY_CAPTURE_ENABLED``).
"""

import uuid
from datetime import datetime
import re
from enum import StrEnum
from typing import Final

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import MessageSource
from app.domain.errors import DomainError
from app.repositories.user_repository import UserRepository
from app.schemas.raw_message import RawMessageCreate
from app.services.background import BackgroundWork
from app.services.ingestion import IngestionService
from app.services.processing.extraction import UNIT_TIMEZONE_KEY
from app.services.processing.runner import PipelineRunner

logger = structlog.get_logger(__name__)

MIN_WORDS: Final = 3


class AdmissionDecision(StrEnum):
    CAPTURE = "capture"
    TOO_SHORT = "too_short"
    NOISY_ACK = "noisy_ack"
    ASSISTANT_DIRECTIVE = "assistant_directive"


_ACK_TERMS: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "okay",
        "thanks",
        "thank",
        "cool",
        "great",
        "nice",
        "got",
        "done",
        "sure",
        "yep",
        "yup",
        "alright",
    }
)

_ASSISTANT_REFERENCES: Final[tuple[str, ...]] = (
    "you",
    "zoop",
    "cooper",
    "assistant",
)

_ASSISTANT_VERBS: Final[tuple[str, ...]] = (
    "find",
    "search",
    "summarize",
    "write",
    "draft",
    "send",
    "book",
    "order",
    "plan",
)

_SELF_CONTEXT_RE = re.compile(r"\b(i|me|my|mine|we|our|us)\b", re.IGNORECASE)


def worth_capturing(text: str) -> bool:
    """Whether a message says enough to be worth an extraction call."""
    return admission_decision(text) is AdmissionDecision.CAPTURE


def admission_decision(text: str) -> AdmissionDecision:
    """Classify whether a chat message should enter the memory pipeline.

    This gate keeps obvious noise and pure assistant directives from spending extraction
    calls and polluting the review inbox.
    """
    words = text.split()
    if len(words) < MIN_WORDS:
        return AdmissionDecision.TOO_SHORT
    if _looks_like_ack(text):
        return AdmissionDecision.NOISY_ACK
    if _looks_like_assistant_directive(text):
        return AdmissionDecision.ASSISTANT_DIRECTIVE
    return AdmissionDecision.CAPTURE


def _looks_like_ack(text: str) -> bool:
    tokens = [token.strip(".,!?;:'\"()[]{}") for token in text.lower().split()]
    compact = [token for token in tokens if token]
    if not compact:
        return True
    return all(token in _ACK_TERMS for token in compact)


def _looks_like_assistant_directive(text: str) -> bool:
    lower = " ".join(text.lower().split())
    if not lower:
        return False

    references_assistant = any(ref in lower.split() for ref in _ASSISTANT_REFERENCES)
    asks_politely = lower.startswith("please ")
    asks_directly = lower.startswith(("can you ", "could you ", "would you ", "will you "))
    if not (references_assistant or asks_politely or asks_directly):
        return False

    if _SELF_CONTEXT_RE.search(lower):
        return False

    return any(f" {verb} " in f" {lower} " for verb in _ASSISTANT_VERBS)


class MemoryCapture:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        ingestion: IngestionService,
        runner: PipelineRunner,
        background: BackgroundWork,
        enabled: bool,
    ) -> None:
        self._session_factory = session_factory
        self._ingestion = ingestion
        self._runner = runner
        self._background = background
        self._enabled = enabled

    def capture_chat_message(
        self,
        *,
        user_id: uuid.UUID,
        message_id: uuid.UUID,
        thread_id: uuid.UUID,
        text: str,
        sent_at: datetime,
        timezone_name: str,
    ) -> None:
        """Schedule the capture of a message the user sent, and return at once.

        ``timezone_name`` is the user's, stored with the evidence so that "tomorrow" in the
        message means the user's tomorrow.
        """
        decision = admission_decision(text)
        if not self._enabled or decision is not AdmissionDecision.CAPTURE:
            logger.debug(
                "memory_capture_skipped",
                message_id=str(message_id),
                reason=decision.value,
                globally_enabled=self._enabled,
            )
            return
        self._background.spawn(
            self._capture(user_id, message_id, thread_id, text, sent_at, timezone_name),
            name=f"memory-capture-{message_id}",
        )

    async def _capture(
        self,
        user_id: uuid.UUID,
        message_id: uuid.UUID,
        thread_id: uuid.UUID,
        text: str,
        sent_at: datetime,
        timezone_name: str,
    ) -> None:
        log = logger.bind(message_id=str(message_id))
        try:
            async with self._session_factory() as session:
                user = await UserRepository(session).get(user_id)
            if user is None or not user.memory_capture_enabled:
                return
            [unit] = await self._ingestion.ingest(
                [
                    [
                        RawMessageCreate(
                            source=MessageSource.APP_CHAT,
                            content=text,
                            # The chat message's id makes capture idempotent.
                            source_message_id=str(message_id),
                            source_created_at=sent_at,
                            metadata={
                                "thread_id": str(thread_id),
                                UNIT_TIMEZONE_KEY: timezone_name,
                            },
                        )
                    ]
                ],
                owner_id=user_id,
            )
            if unit.run.created and self._runner.can_process:
                await self._runner.process_runs([unit.run.id])
        except DomainError as error:
            log.warning("memory_capture_failed", error_code=error.code)
        except Exception:
            log.exception("memory_capture_crashed")
