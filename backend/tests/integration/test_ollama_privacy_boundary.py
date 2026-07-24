"""Ollama reasoning content cannot cross graph, SSE, tracing, logging, or memory."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
from enterprise_ai.api.schemas import ChatStreamEnvelope
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.dependencies import OfflineSparseAdapter
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphOutput
from enterprise_ai.llm.ollama_provider import OllamaChatProvider
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.main import create_app
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.observability.tracing import FakeTraceRecorder, SafeTracer
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.sparse.retriever import SparseRetrievalService
from fastapi.testclient import TestClient

from backend.tests.integration.chat_api_support import authorization_header, chat_settings

_REASONING_SENTINEL = "SYNTHETIC_PRIVATE_REASONING_SENTINEL"


def test_reasoning_is_rejected_before_every_public_or_persistent_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "answer_summary": "Unsafe draft must not be projected.",
                            "claims": [],
                        }
                    ),
                    "thinking": _REASONING_SENTINEL,
                },
            },
        )

    settings = RetrievalSettings(llm_provider="ollama")
    recorder = FakeTraceRecorder()
    tracer = SafeTracer(recorder)
    provider = OllamaChatProvider(settings, transport=httpx.MockTransport(handler))
    responses = GroundedResponseService(provider, settings, tracer)
    memory = create_memory_service(settings)
    graph = build_graph(
        settings,
        OfflineSparseAdapter(SparseRetrievalService(settings)),
        checkpointer=create_checkpointer(),
        memory=memory,
        responses=responses,
        tracer=tracer,
    )
    runtime = GraphRuntime(graph, settings, memory, responses, tracer)

    with TestClient(
        create_app(chat_settings(), runtime_factory=lambda _settings: runtime)
    ) as client:
        header = authorization_header(client, "demo-viewer")
        principal = client.app.state.token_service.decode_principal(
            header["Authorization"].removeprefix("Bearer ")
        )
        response = client.post(
            "/api/v1/chat",
            headers=header,
            json={
                "message": (
                    "What does the active Payment Queue Backlog Recovery Runbook require "
                    "for controlled backlog drain and idempotency verification?"
                )
            },
        )

    assert response.status_code == 200
    assert _REASONING_SENTINEL not in response.text
    assert "<think" not in response.text.casefold()
    output = GraphOutput.model_validate(response.json())
    assert output.response_provider == "deterministic"
    assert output.citations
    envelope = ChatStreamEnvelope(
        event_id=uuid4(),
        sequence=0,
        request_id=output.request_id,
        trace_id=output.trace_id,
        session_id=output.session_id,
        event_type="response.completed",
        response=output,
    )
    assert _REASONING_SENTINEL not in envelope.model_dump_json()
    inspection = asyncio.run(memory.inspect(UUID(str(output.session_id)), principal))
    assert inspection is not None
    assert _REASONING_SENTINEL not in inspection.model_dump_json()
    assert _REASONING_SENTINEL not in repr([record.metadata for record in recorder.records])
    assert _REASONING_SENTINEL not in caplog.text
    assert provider.closed
