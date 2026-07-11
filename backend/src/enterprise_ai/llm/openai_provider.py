"""Official async OpenAI Responses API structured-output provider."""

import asyncio

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from enterprise_ai.llm.exceptions import LLMProviderError, LLMRefusalError
from enterprise_ai.llm.models import (
    GroundedAnswerDraft,
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderMetadata,
    LLMUsage,
)
from enterprise_ai.retrieval.config import RetrievalSettings


class OpenAIResponsesProvider:
    def __init__(self, settings: RetrievalSettings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key_value(),
            timeout=settings.openai_response_timeout_seconds,
            max_retries=0,
        )

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        response = None
        for attempt in range(self._settings.openai_response_max_retries + 1):
            try:
                response = await self._client.responses.parse(
                    model=request.model,
                    instructions=request.instructions,
                    input=request.input_text,
                    text_format=GroundedAnswerDraft,
                    max_output_tokens=request.maximum_output_tokens,
                    temperature=self._settings.openai_response_temperature,
                    store=False,
                    parallel_tool_calls=False,
                    tools=[],
                    service_tier=self._settings.openai_response_service_tier,
                )
                break
            except (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
                RateLimitError,
            ) as error:
                if attempt >= self._settings.openai_response_max_retries:
                    raise LLMProviderError("OpenAI response generation failed safely") from error
                await asyncio.sleep(
                    self._settings.openai_response_retry_base_seconds * (2**attempt)
                )
            except Exception as error:
                raise LLMProviderError("OpenAI response generation failed safely") from error
        if response is None:
            raise LLMProviderError("OpenAI response generation failed safely")
        if response.status != "completed":
            raise LLMProviderError("OpenAI response was incomplete")
        draft = response.output_parsed
        if draft is None:
            raise LLMRefusalError("OpenAI response did not contain a grounded draft")
        usage = response.usage
        return LLMGenerationResult(
            draft=draft,
            metadata=LLMProviderMetadata(provider="openai", model=response.model),
            usage=LLMUsage(
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
            ),
        )

    async def close(self) -> None:
        await self._client.close()
