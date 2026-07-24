"""Native Ollama provider schema, privacy, lifecycle, and failure tests."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from enterprise_ai.llm.dependencies import create_llm_provider
from enterprise_ai.llm.exceptions import (
    LLMDependencyUnavailableError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMTimeoutError,
)
from enterprise_ai.llm.fake_provider import FakeLLMProvider
from enterprise_ai.llm.models import LLMGenerationRequest, ResponseMode
from enterprise_ai.llm.ollama_provider import OllamaChatProvider, ollama_json_schema
from enterprise_ai.llm.openai_provider import OpenAIResponsesProvider
from enterprise_ai.retrieval.config import RetrievalSettings
from pydantic import ValidationError


def _request() -> LLMGenerationRequest:
    return LLMGenerationRequest(
        mode=ResponseMode.DIRECT,
        instructions="Safe system instructions",
        input_text="Safe user input",
        model="qwen3:4b-instruct",
        maximum_output_tokens=128,
    )


def _response(*, thinking: object = "", content: str | None = None) -> dict[str, object]:
    structured = {
        "answer_summary": "Ready.",
        "claims": [],
        "warnings": [],
        "insufficient_evidence": False,
        "clarification_needed": False,
    }
    return {
        "model": "qwen3:4b-instruct",
        "done": True,
        "message": {
            "role": "assistant",
            "content": content if content is not None else json.dumps(structured),
            "thinking": thinking,
        },
        "prompt_eval_count": 12,
        "eval_count": 8,
    }


@pytest.mark.asyncio
async def test_provider_factory_preserves_fake_ollama_and_optional_openai() -> None:
    fake = create_llm_provider(RetrievalSettings())
    ollama = create_llm_provider(RetrievalSettings(llm_provider="ollama"))
    openai = create_llm_provider(
        RetrievalSettings(llm_provider="openai", openai_api_key="test-only-key")
    )
    try:
        assert isinstance(fake, FakeLLMProvider)
        assert isinstance(ollama, OllamaChatProvider)
        assert isinstance(openai, OpenAIResponsesProvider)
    finally:
        await fake.close()
        await ollama.close()
        await openai.close()


@pytest.mark.asyncio
async def test_native_request_uses_exact_schema_and_no_thinking() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_response())

    settings = RetrievalSettings(llm_provider="ollama")
    provider = OllamaChatProvider(settings, transport=httpx.MockTransport(handler))
    try:
        result = await provider.generate(_request())
    finally:
        await provider.close()

    assert seen["model"] == "qwen3:4b-instruct"
    assert seen["stream"] is False
    assert seen["think"] is False
    assert seen["format"] == ollama_json_schema()
    assert seen["format"]["additionalProperties"] is False  # type: ignore[index]
    assert seen["options"] == {
        "temperature": 0.0,
        "num_ctx": 8192,
        "num_predict": 128,
    }
    assert isinstance(seen["options"]["temperature"], float)  # type: ignore[index]
    assert seen["keep_alive"] == "5m"
    assert result.metadata.provider == "ollama"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 8
    assert provider.closed


def test_grounded_schema_requires_claim_and_evidence_relationship() -> None:
    schema = ollama_json_schema(require_grounded_claim=True)
    assert schema["properties"]["claims"]["minItems"] == 1
    assert "claims" in schema["required"]
    claim = schema["$defs"]["GroundedClaim"]
    assert claim["properties"]["supporting_evidence_ids"]["minItems"] == 1
    assert "supporting_evidence_ids" in claim["required"]


def test_zero_temperature_parses_from_string_environment_and_rejects_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0")
    settings = RetrievalSettings(_env_file=None)
    assert settings.ollama_temperature == 0.0
    assert isinstance(settings.ollama_temperature, float)

    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.1")
    with pytest.raises(ValidationError):
        RetrievalSettings(_env_file=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _response(thinking="private chain"),
        _response(content="<think>private chain</think>{}"),
        {
            **_response(),
            "reasoning_content": "private chain",
        },
        {
            "done": True,
            "message": {
                "content": json.dumps(
                    {
                        "answer_summary": "Ready.",
                        "claims": [],
                        "warnings": [],
                        "insufficient_evidence": False,
                        "clarification_needed": False,
                    }
                ),
                "reasoning": "private chain",
            },
        },
        {"done": False, "message": {"content": "{}"}},
        {"done": True, "message": {}},
        {"done": True, "message": {"content": "not-json"}},
    ],
)
async def test_reasoning_malformed_and_incomplete_responses_are_rejected(
    response: dict[str, object],
) -> None:
    provider = OllamaChatProvider(
        RetrievalSettings(llm_provider="ollama"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )
    try:
        with pytest.raises(LLMInvalidResponseError):
            await provider.generate(_request())
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("private", request=request)),
            LLMDependencyUnavailableError,
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("private", request=request)),
            LLMTimeoutError,
        ),
        (
            lambda _request: httpx.Response(404, json={"error": "private path"}),
            LLMDependencyUnavailableError,
        ),
        (lambda _request: httpx.Response(500, text="private body"), LLMProviderError),
        (lambda _request: httpx.Response(200, text="{"), LLMInvalidResponseError),
    ],
)
async def test_provider_errors_are_typed_and_sanitized(
    handler: object, expected: type[Exception]
) -> None:
    provider = OllamaChatProvider(
        RetrievalSettings(llm_provider="ollama"),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(expected) as caught:
            await provider.generate(_request())
    finally:
        await provider.close()
    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_cancellation_propagates_and_does_not_log_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    started = asyncio.Event()

    async def handler(_request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json=_response())

    provider = OllamaChatProvider(
        RetrievalSettings(llm_provider="ollama"),
        transport=httpx.MockTransport(handler),
    )
    task = asyncio.create_task(provider.generate(_request()))
    await started.wait()
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await provider.close()
    serialized = caplog.text.casefold()
    assert "safe system instructions" not in serialized
    assert "safe user input" not in serialized
    assert "private chain" not in serialized


@pytest.mark.parametrize(
    "values",
    [
        {"ollama_base_url": "http://user:secret@127.0.0.1:11434"},
        {"ollama_base_url": "http://127.0.0.1:11434/api/chat"},
        {"ollama_base_url": "http://127.0.0.1:11434?unsafe=true"},
        {"ollama_base_url": "http://127.0.0.1:11434#fragment"},
        {"ollama_base_url": "http://example.test:11434"},
        {
            "ollama_base_url": "http://example.test:11434",
            "ollama_allow_remote": True,
        },
        {"ollama_keep_alive": "2h"},
    ],
)
def test_ollama_configuration_rejects_unsafe_endpoints_and_bounds(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RetrievalSettings(**values)


def test_docker_host_endpoint_and_explicit_https_remote_are_allowed() -> None:
    docker = RetrievalSettings(ollama_base_url="http://host.docker.internal:11434")
    remote = RetrievalSettings(
        ollama_base_url="https://ollama.example.test",
        ollama_allow_remote=True,
    )
    assert docker.ollama_base_url == "http://host.docker.internal:11434"
    assert remote.ollama_base_url == "https://ollama.example.test"
