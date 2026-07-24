"""Native Ollama chat provider with schema-constrained, reasoning-free output."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import httpx
from pydantic import ValidationError

from enterprise_ai.llm.exceptions import (
    LLMDependencyUnavailableError,
    LLMHTTPStatusError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMTimeoutError,
)
from enterprise_ai.llm.models import (
    GroundedAnswerDraft,
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderMetadata,
    LLMUsage,
)
from enterprise_ai.retrieval.config import RetrievalSettings

_REASONING_FIELDS = ("thinking", "reasoning", "reasoning_content")
_THINK_BLOCK = re.compile(r"<\s*/?\s*think\b", re.IGNORECASE)
_GRAMMAR_UNSUPPORTED_ANNOTATIONS = frozenset(
    {"default", "maxItems", "maxLength", "pattern", "title"}
)


class OllamaChatProvider:
    """Reuse one bounded native Ollama client and validate every response."""

    def __init__(
        self,
        settings: RetrievalSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.ollama_request_timeout_seconds),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            transport=transport,
            trust_env=False,
        )

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        payload = await self._request_json(
            "POST",
            "/api/chat",
            json_body={
                "model": request.model,
                "messages": [
                    {"role": "system", "content": request.instructions},
                    {"role": "user", "content": request.input_text},
                ],
                "stream": False,
                "format": ollama_json_schema(
                    require_grounded_claim=request.mode.value == "grounded_retrieval"
                ),
                "think": False,
                "options": {
                    "temperature": self._settings.ollama_temperature,
                    "num_ctx": self._settings.ollama_num_ctx,
                    "num_predict": min(
                        request.maximum_output_tokens,
                        self._settings.ollama_num_predict,
                    ),
                },
                "keep_alive": self._settings.ollama_keep_alive,
            },
        )
        if payload.get("done") is not True:
            raise LLMInvalidResponseError("Ollama response was incomplete")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise LLMInvalidResponseError("Ollama response did not contain a message")
        self._reject_reasoning(payload, message)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMInvalidResponseError("Ollama response did not contain structured content")
        if _THINK_BLOCK.search(content):
            raise LLMInvalidResponseError("Ollama response contained prohibited reasoning markup")
        try:
            decoded = json.loads(content)
            draft = GroundedAnswerDraft.model_validate(decoded)
        except ValidationError as error:
            fields = sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]})
            category = "validation_" + "_".join(fields[:5]) if fields else "validation"
            raise LLMInvalidResponseError(
                f"Ollama structured output was invalid ({category})",
                category=category,
            ) from None
        except (json.JSONDecodeError, TypeError):
            raise LLMInvalidResponseError("Ollama structured output was invalid") from None
        return LLMGenerationResult(
            draft=draft,
            metadata=LLMProviderMetadata(provider="ollama", model=request.model),
            usage=LLMUsage(
                input_tokens=_non_negative_int(payload.get("prompt_eval_count")),
                output_tokens=_non_negative_int(payload.get("eval_count")),
            ),
        )

    async def version(self) -> str:
        payload = await self._request_json("GET", "/api/version")
        version = payload.get("version")
        if not isinstance(version, str) or not 1 <= len(version) <= 100:
            raise LLMInvalidResponseError("Ollama version response was invalid")
        return version

    async def model_names(self) -> tuple[str, ...]:
        payload = await self._request_json("GET", "/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise LLMInvalidResponseError("Ollama model list was invalid")
        names: set[str] = set()
        for item in models:
            if not isinstance(item, dict):
                continue
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str) and 1 <= len(value) <= 128:
                    names.add(value)
        return tuple(sorted(names))

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def closed(self) -> bool:
        return self._client.is_closed

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=json_body)
        except httpx.TimeoutException:
            raise LLMTimeoutError("Ollama request timed out") from None
        except httpx.ConnectError:
            raise LLMDependencyUnavailableError("Ollama is unavailable") from None
        except httpx.RequestError:
            raise LLMProviderError("Ollama request failed safely") from None
        if response.status_code == 404:
            raise LLMDependencyUnavailableError(
                "Configured Ollama model or endpoint is unavailable"
            )
        if not 200 <= response.status_code < 300:
            raise LLMHTTPStatusError(
                response.status_code,
                _safe_error_category(response),
            )
        try:
            payload = response.json()
        except ValueError:
            raise LLMInvalidResponseError("Ollama returned malformed JSON") from None
        if not isinstance(payload, dict):
            raise LLMInvalidResponseError("Ollama returned an invalid response")
        return payload

    @staticmethod
    def _reject_reasoning(payload: dict[str, Any], message: dict[str, Any]) -> None:
        for container in (payload, message):
            for field in _REASONING_FIELDS:
                value = container.get(field)
                if value not in (None, "", [], {}):
                    raise LLMInvalidResponseError(
                        "Ollama response contained prohibited reasoning content"
                    )


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def ollama_json_schema(*, require_grounded_claim: bool = False) -> dict[str, Any]:
    """Derive Ollama's grammar-compatible schema from the authoritative Pydantic model."""

    def compatible(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: compatible(item)
                for key, item in value.items()
                if key not in _GRAMMAR_UNSUPPORTED_ANNOTATIONS
            }
        if isinstance(value, list):
            return [compatible(item) for item in value]
        return value

    schema = cast(dict[str, Any], compatible(GroundedAnswerDraft.model_json_schema()))
    if require_grounded_claim:
        properties = schema["properties"]
        properties["claims"]["minItems"] = 1
        required = list(schema.get("required", []))
        if "claims" not in required:
            required.append("claims")
        schema["required"] = required
        claim = schema["$defs"]["GroundedClaim"]
        claim["properties"]["supporting_evidence_ids"]["minItems"] = 1
        claim_required = list(claim.get("required", []))
        if "supporting_evidence_ids" not in claim_required:
            claim_required.append("supporting_evidence_ids")
        claim["required"] = claim_required
    return schema


def _safe_error_category(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "request_rejected"
    detail = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(detail, str):
        return "request_rejected"
    normalized = detail.casefold()
    if "thinking" in normalized or "think" in normalized:
        return "thinking_option_rejected"
    if "schema" in normalized or "format" in normalized:
        return "schema_rejected"
    if "model" in normalized:
        return "model_rejected"
    if "option" in normalized:
        return "options_rejected"
    return "request_rejected"
