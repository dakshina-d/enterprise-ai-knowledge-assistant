"""Configuration tests for optional LangSmith tracing."""

import pytest
from enterprise_ai.observability.tracing import SafeTracer, create_tracer
from enterprise_ai.retrieval.config import RetrievalSettings
from pydantic import ValidationError


def test_tracing_is_disabled_without_credentials() -> None:
    settings = RetrievalSettings()

    assert not settings.langsmith_tracing
    assert not create_tracer(settings).enabled


def test_enabled_tracing_requires_api_key_without_disclosing_it() -> None:
    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY") as captured:
        RetrievalSettings(langsmith_tracing=True)

    assert "secret-value" not in str(captured.value)


def test_disabled_tracer_is_a_noop() -> None:
    assert isinstance(create_tracer(RetrievalSettings()), SafeTracer)


def test_api_key_is_masked_in_configuration_dumps() -> None:
    settings = RetrievalSettings(langsmith_api_key="secret-value")

    assert "secret-value" not in repr(settings.model_dump())
