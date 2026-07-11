"""Provider protocol independent of any SDK."""

from typing import Protocol

from enterprise_ai.llm.models import LLMGenerationRequest, LLMGenerationResult


class LLMProvider(Protocol):
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult: ...

    async def close(self) -> None: ...
