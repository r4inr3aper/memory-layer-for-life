"""Checks a person can run from the console to see whether model calls would work."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import LlmOperation
from app.domain.errors import DomainError, ProviderNotConfiguredError, UnsupportedModelError
from app.models.llm_call import LlmCall
from app.repositories.llm_call_repository import LlmCallFilter, LlmCallRepository
from app.services.playground import allowed_models


class ProviderCheck(Protocol):
    async def run(self, model: str) -> None:
        """Make one tiny call. Raises ``DomainError`` when it does not work."""
        ...


@dataclass(frozen=True, slots=True)
class ConnectionCheckResult:
    """Outcome of a connection check. ``call`` is the logged call, when it was logged."""

    ok: bool
    model: str
    error_code: str | None = None
    error_message: str | None = None
    call: LlmCall | None = None


class DiagnosticsService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        check: ProviderCheck,
        *,
        default_model: str,
    ) -> None:
        self._session_factory = session_factory
        self._check = check
        self._default_model = default_model

    async def check_connection(self, model: str | None = None) -> ConnectionCheckResult:
        """Call the provider once and report whether it worked.

        A failed call is a result. Only a check that cannot be attempted raises:
        ``ProviderNotConfiguredError`` or ``UnsupportedModelError``.
        """
        chosen_model = model or self._default_model
        if chosen_model not in allowed_models(self._default_model):
            raise UnsupportedModelError(chosen_model)

        error: DomainError | None = None
        try:
            await self._check.run(chosen_model)
        except ProviderNotConfiguredError:
            raise
        except DomainError as failure:
            error = failure

        async with self._session_factory() as session:
            calls, _ = await LlmCallRepository(session).list_calls(
                LlmCallFilter(operation=LlmOperation.CONNECTION_CHECK, model=chosen_model),
                limit=1,
                offset=0,
            )
        return ConnectionCheckResult(
            ok=error is None,
            model=chosen_model,
            error_code=error.code if error is not None else None,
            error_message=error.message if error is not None else None,
            call=calls[0] if calls else None,
        )
