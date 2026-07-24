"""Application-owned grounded response generation."""

from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.ollama_provider import OllamaChatProvider
from enterprise_ai.llm.openai_provider import OpenAIResponsesProvider

GROUNDED_PROMPT_VERSION = "1.0"
ANALYSIS_PROMPT_VERSION = "1.0"
DIRECT_PROMPT_VERSION = "1.0"

__all__ = ("FakeLLMProvider", "OllamaChatProvider", "OpenAIResponsesProvider")
