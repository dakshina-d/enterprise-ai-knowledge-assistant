"""Explicitly opt-in, credential-free local Ollama integration check."""

from __future__ import annotations

import os
from time import monotonic

import pytest
from enterprise_ai.api.runtime import create_api_runtime
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.llm.grounding import build_evidence_context
from enterprise_ai.llm.models import LLMGenerationRequest, ResponseMode
from enterprise_ai.llm.ollama_provider import OllamaChatProvider
from enterprise_ai.llm.prompts import grounded_request
from enterprise_ai.main import create_app
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService
from fastapi.testclient import TestClient

from backend.tests.integration.chat_api_support import authorization_header, chat_settings

pytestmark = pytest.mark.ollama_live


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("OLLAMA_LIVE_TESTS", "").casefold() != "true",
    reason="set OLLAMA_LIVE_TESTS=true to run local Ollama integration tests",
)
async def test_qwen_structured_response_has_no_thinking() -> None:
    settings = RetrievalSettings(
        llm_provider="ollama",
        ollama_num_ctx=2_048,
        ollama_num_predict=128,
    )
    assert settings.ollama_model == "qwen3:4b-instruct"
    provider = OllamaChatProvider(settings)
    try:
        assert settings.ollama_model in await provider.model_names()
        result = await provider.generate(
            LLMGenerationRequest(
                mode=ResponseMode.GROUNDED_RETRIEVAL,
                instructions=(
                    "Return one factual claim C1 citing only E1 with confidence high. "
                    "Return no warnings, set both boolean fields false, and do not "
                    "include private reasoning."
                ),
                input_text="E1: The structured local inference probe is ready.",
                allowed_evidence_ids=("E1",),
                model=settings.ollama_model,
                maximum_output_tokens=128,
            )
        )
    finally:
        await provider.close()
    assert result.metadata.provider == "ollama"
    assert result.draft.answer_summary
    assert "<think" not in result.draft.model_dump_json().casefold()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("OLLAMA_LIVE_TESTS", "").casefold() != "true",
    reason="set OLLAMA_LIVE_TESTS=true to run local Ollama integration tests",
)
async def test_qwen_real_grounded_request_contract() -> None:
    settings = RetrievalSettings(
        llm_provider="ollama",
        ollama_num_ctx=4_096,
        ollama_num_predict=256,
        llm_max_evidence_items=1,
        llm_max_evidence_characters=2_000,
        llm_max_evidence_item_characters=2_000,
        llm_max_prompt_characters=4_000,
    )
    question = (
        "What does the active Payment Queue Backlog Recovery Runbook require "
        "for controlled backlog drain and idempotency verification?"
    )
    principal = assessment_principal(UserRole.VIEWER)
    retrieved = await OfflineSparseAdapter(SparseRetrievalService(settings)).retrieve(
        principal,
        question,
        top_k=5,
        filters=DenseQueryFilters(),
    )
    context = build_evidence_context(retrieved.evidence, settings)
    provider = OllamaChatProvider(settings)
    try:
        result = await provider.generate(grounded_request(question, context, settings))
    finally:
        await provider.close()
    assert result.metadata.provider == "ollama"
    assert result.draft.claims
    assert set(result.draft.claims[0].supporting_evidence_ids) <= {"E1"}


@pytest.mark.skipif(
    os.getenv("OLLAMA_LIVE_TESTS", "").casefold() != "true",
    reason="set OLLAMA_LIVE_TESTS=true to run local Ollama integration tests",
)
def test_authenticated_graph_scenarios_with_local_qwen() -> None:
    active = RetrievalSettings(
        llm_provider="ollama",
        ollama_num_ctx=4_096,
        ollama_num_predict=256,
        llm_max_evidence_items=1,
        llm_max_evidence_characters=2_000,
        llm_max_evidence_item_characters=2_000,
        llm_max_prompt_characters=4_000,
        graph_timeout_seconds=300,
        research_max_execution_seconds=90,
    )

    def runtime_factory(_settings: RetrievalSettings) -> GraphRuntime:
        return create_api_runtime(active)

    supported_query = (
        "What does the active Payment Queue Backlog Recovery Runbook require "
        "for controlled backlog drain and idempotency verification?"
    )
    started = monotonic()
    with TestClient(create_app(chat_settings(), runtime_factory=runtime_factory)) as client:
        viewer = authorization_header(client, "demo-viewer")
        two_turn_runs = []
        for _ in range(2):
            supported = client.post(
                "/api/v1/chat",
                headers=viewer,
                json={"message": supported_query},
            )
            follow_up = client.post(
                "/api/v1/chat",
                headers=viewer,
                json={
                    "message": "Explain that again.",
                    "session_id": supported.json()["session_id"],
                },
            )
            two_turn_runs.append((supported, follow_up))
        unsupported = client.post(
            "/api/v1/chat",
            headers=viewer,
            json={"message": "Summarize the password policy."},
        )
        analyst = authorization_header(client, "demo-analyst")
        mcp = client.post(
            "/api/v1/chat",
            headers=analyst,
            json={"message": "Who owns the payment-gateway service?"},
        )
        analysis = client.post(
            "/api/v1/chat",
            headers=analyst,
            json={"message": "Count payment incidents by root cause."},
        )
        research_started = monotonic()
        research = client.post(
            "/api/v1/chat",
            headers=analyst,
            json={
                "message": (
                    "Compare pending payment status in September and delayed "
                    "settlement in February."
                )
            },
        )
        research_seconds = monotonic() - research_started
        print(f"ollama_live_research_seconds={research_seconds:.2f}")

    assert unsupported.status_code == 200
    assert unsupported.json()["insufficient_evidence"] is True
    assert unsupported.json()["citations"] == []
    for supported, follow_up in two_turn_runs:
        assert supported.status_code == follow_up.status_code == 200
        for response in (supported, follow_up):
            output = response.json()
            assert output["evidence"][0]["title"] == "Payment Queue Backlog Recovery Runbook"
            assert output["citations"][0]["title"] == "Payment Queue Backlog Recovery Runbook"
            assert output["response_provider"] == "ollama"
            assert output["deterministic_fallback_used"] is False
            assert output["fallback_reason"] is None
        assert follow_up.json()["memory_used"] is True
    assert mcp.status_code == 200 and mcp.json()["mcp_result"] is not None
    assert analysis.status_code == 200 and analysis.json()["analysis_result"] is not None
    assert research.status_code == 200
    research_output = research.json()
    assert research_output["selected_route"] == "recursive_research"
    assert research_output["completion_status"] == "completed"
    assert research_output["response_provider"] == "ollama"
    assert research_output["deterministic_fallback_used"] is False
    assert research_output["fallback_reason"] is None
    assert {item["title"] for item in research_output["citations"]} == {
        "Pending Payment Status Accumulation",
        "Card Settlement Consumer Lag",
    }
    research_answer = research_output["response_text"].casefold()
    assert "september" in research_answer and "february" in research_answer
    assert "message_queue_backlog" in research_answer or "message queue backlog" in research_answer
    assert "throughput" in research_answer and "ingress" in research_answer
    assert "pending" in research_answer
    assert "settlement" in research_answer and (
        "lag" in research_answer or "delay" in research_answer
    )
    assert "database_lock_contention" not in research_answer
    assert "no february evidence" not in research_answer
    assert research_seconds < active.graph_timeout_seconds
    serialized = " ".join(
        response.text
        for response in (
            *(item for pair in two_turn_runs for item in pair),
            unsupported,
            mcp,
            analysis,
            research,
        )
    ).casefold()
    assert "<think" not in serialized
    assert "private reasoning" not in serialized
    assert monotonic() - started < active.graph_timeout_seconds * 2
