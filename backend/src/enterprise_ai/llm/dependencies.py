"""Explicit provider construction without import-time clients."""

from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.ollama_provider import OllamaChatProvider
from enterprise_ai.llm.openai_provider import OpenAIResponsesProvider
from enterprise_ai.llm.provider import LLMProvider
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.observability.tracing import SafeTracer
from enterprise_ai.retrieval.config import RetrievalSettings


def create_llm_provider(settings: RetrievalSettings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAIResponsesProvider(settings)
    if settings.llm_provider == "ollama":
        return OllamaChatProvider(settings)
    return FakeLLMProvider()


def create_response_service(
    settings: RetrievalSettings, tracer: SafeTracer | None = None
) -> GroundedResponseService:
    return GroundedResponseService(create_llm_provider(settings), settings, tracer)
