"""Explicit provider construction without import-time clients."""

from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.openai_provider import OpenAIResponsesProvider
from enterprise_ai.llm.provider import LLMProvider
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.retrieval.config import RetrievalSettings


def create_llm_provider(settings: RetrievalSettings) -> LLMProvider:
    if settings.llm_provider == "openai":
        return OpenAIResponsesProvider(settings)
    return FakeLLMProvider()


def create_response_service(settings: RetrievalSettings) -> GroundedResponseService:
    return GroundedResponseService(create_llm_provider(settings), settings)
