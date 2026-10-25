"""Builds extractors and describes the configured one."""

from typing import Protocol

from app.core.config import EffortLevel, Settings
from app.domain.model_catalog import supports_refusal_fallback
from app.domain.versions import ExtractorDescriptor
from app.integrations.anthropic_calls import PROVIDER_NAME, AnthropicCallObserver
from app.integrations.anthropic_client import AnthropicClientManager
from app.integrations.extraction.anthropic_extractor import AnthropicExtractor
from app.integrations.extraction.base import Extractor
from app.integrations.extraction.prompt import EXTRACTION_PROMPT_VERSION


def configured_extractor_descriptor(settings: Settings) -> ExtractorDescriptor:
    """Describe the extractor this configuration selects.

    The description does not need a working client. Ingestion uses it to compute the
    processing identity even when no API key is configured, so captured units get the
    same identity they will be processed under later.
    """
    return ExtractorDescriptor(
        provider=PROVIDER_NAME,
        model=settings.ANTHROPIC_MODEL,
        prompt_version=EXTRACTION_PROMPT_VERSION,
    )


def build_extractor(
    settings: Settings,
    anthropic_manager: AnthropicClientManager,
    *,
    observer: AnthropicCallObserver | None = None,
    model: str | None = None,
    effort: EffortLevel | None = None,
) -> AnthropicExtractor | None:
    """Return an extractor, or ``None`` when the provider is not configured.

    ``model`` and ``effort`` default to the configured ones. The refusal fallback is only
    requested from a model that has one: sending the parameter to another model would
    fail every call.
    """
    client = anthropic_manager.client
    if client is None:
        return None
    chosen_model = model or settings.ANTHROPIC_MODEL
    return AnthropicExtractor(
        client,
        model=chosen_model,
        effort=effort or settings.EXTRACTION_EFFORT,
        max_tokens=settings.EXTRACTION_MAX_TOKENS,
        refusal_fallback=(
            settings.ANTHROPIC_REFUSAL_FALLBACK and supports_refusal_fallback(chosen_model)
        ),
        observer=observer,
    )


class ExtractorFactory(Protocol):
    """Builds an extractor for a chosen model, for testing and evaluation.

    The pipeline always uses the configured extractor, because the model is part of the
    processing identity. Test calls and evaluations may pick another one.
    """

    def build(
        self, *, model: str | None = None, effort: EffortLevel | None = None
    ) -> Extractor | None:
        """Return an extractor, or ``None`` when the provider is not configured."""
        ...


class AnthropicExtractorFactory:
    def __init__(
        self,
        settings: Settings,
        anthropic_manager: AnthropicClientManager,
        observer: AnthropicCallObserver,
    ) -> None:
        self._settings = settings
        self._anthropic_manager = anthropic_manager
        self._observer = observer

    def build(
        self, *, model: str | None = None, effort: EffortLevel | None = None
    ) -> Extractor | None:
        return build_extractor(
            self._settings,
            self._anthropic_manager,
            observer=self._observer,
            model=model,
            effort=effort,
        )


class FixedExtractorFactory:
    """Always returns the same extractor, whatever is asked for.

    Tests use it to run the real services with a scripted extractor.
    """

    def __init__(self, extractor: Extractor | None) -> None:
        self._extractor = extractor

    def build(
        self, *, model: str | None = None, effort: EffortLevel | None = None
    ) -> Extractor | None:
        return self._extractor
