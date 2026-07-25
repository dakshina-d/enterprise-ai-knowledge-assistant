"""Graph-level acceptance coverage for LLM dependency failure behavior."""

import json
import logging
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.llm.exceptions import LLMDependencyUnavailableError
from enterprise_ai.llm.models import FallbackReason, LLMGenerationRequest, LLMGenerationResult
from enterprise_ai.llm.response_service import GroundedResponseService
from enterprise_ai.memory.dependencies import create_memory_service
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventType
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import AccessLevel, UserRole
from enterprise_ai.models.retrieval import DocumentType
from enterprise_ai.observability.tracing import FakeTraceRecorder, SafeTracer
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.hybrid.models import (
    CompletionStatus,
    HybridEvidence,
    HybridRetrievalResult,
)


class StaticRetriever:
    def __init__(self, settings: RetrievalSettings) -> None:
        manifest = json.loads(settings.ingestion_manifest_path.read_text(encoding="utf-8"))
        self.build_fingerprint = str(manifest["build_fingerprint"])

    async def retrieve(self, *args: object, **kwargs: object) -> HybridRetrievalResult:
        identifier = UUID("00000000-0000-4000-8000-000000000123")
        evidence = DenseEvidence(
            record_id=str(identifier),
            dense_score=0.9,
            chunk_id=identifier,
            evidence_id=identifier,
            document_id=identifier,
            title="Safe policy",
            source="sample",
            source_file="data/sample_documents/policies/safe.md",
            section="Policy",
            section_path=("Policy",),
            source_line_start=1,
            source_line_end=2,
            version="1",
            updated_date=date(2026, 1, 1),
            access_level=AccessLevel.INTERNAL,
            allowed_roles=frozenset({UserRole.VIEWER}),
            document_type=DocumentType.POLICY,
            department="people",
            status="active",
            text="The approved leave policy requires manager review before submission.",
            chunk_content_hash="a" * 64,
            build_fingerprint=self.build_fingerprint,
        )
        return HybridRetrievalResult(
            evidence=(
                HybridEvidence(
                    evidence=evidence,
                    raw_dense_score=0.9,
                    normalized_dense_score=1,
                    hybrid_score=1,
                    dense_rank=1,
                    final_rank=1,
                    retrieval_modes=frozenset({"dense"}),
                ),
            ),
            completion_status=CompletionStatus.COMPLETE,
        )


def request(message: str) -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.VIEWER),
        user_message=message,
    )


class UnavailableProvider:
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResult:
        del request
        raise LLMDependencyUnavailableError(
            "provider-private-marker Bearer provider-secret internal/provider/path"
        )

    async def close(self) -> None:
        return None


def failure_runtime(
    tmp_path: Path,
    *,
    allow_fallback: bool,
    recorder: FakeTraceRecorder,
) -> GraphRuntime:
    manifest_path = tmp_path / "ingestion_manifest.json"
    manifest_path.write_text(json.dumps({"build_fingerprint": "a" * 64}), encoding="utf-8")
    settings = RetrievalSettings(
        ingestion_manifest_path=manifest_path,
        llm_allow_deterministic_fallback=allow_fallback,
    )
    tracer = SafeTracer(recorder)
    memory = create_memory_service(settings)
    responses = GroundedResponseService(UnavailableProvider(), settings, tracer)
    graph = build_graph(
        settings,
        StaticRetriever(settings),
        checkpointer=create_checkpointer(),
        memory=memory,
        responses=responses,
        tracer=tracer,
    )
    return GraphRuntime(
        graph,
        settings,
        memory=memory,
        responses=responses,
        tracer=tracer,
    )


@pytest.mark.asyncio
async def test_llm_unavailable_uses_safe_fallback_and_stores_completed_turn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = FakeTraceRecorder()
    runtime = failure_runtime(tmp_path, allow_fallback=True, recorder=recorder)
    graph_input = request(message="find leave policy log-private-query-marker")

    with caplog.at_level(logging.INFO, logger="enterprise_ai.graph.runtime"):
        items = [item async for item in runtime.astream(graph_input)]

    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    terminal = [
        item
        for item in events
        if item.event_type in {AgentEventType.RESPONSE_COMPLETED, AgentEventType.RESPONSE_FAILED}
    ]
    assert output.completion_status is ProcessingStatus.COMPLETED
    assert output.selected_route is Route.SIMPLE_RETRIEVAL
    assert output.deterministic_fallback_used
    assert output.fallback_reason is FallbackReason.PROVIDER_UNAVAILABLE
    assert output.response_provider == "deterministic"
    assert output.citations
    assert "manager review" in output.response_text
    assert "Authorized evidence was found:" not in output.response_text
    assert output.memory_update_status == "stored"
    assert [item.event_type for item in terminal] == [AgentEventType.RESPONSE_COMPLETED]
    warning = next(
        item for item in events if item.event_type is AgentEventType.RESPONSE_FALLBACK_USED
    )
    assert warning.payload.error_code == FallbackReason.PROVIDER_UNAVAILABLE.value
    assert len([item for item in items if item.output is not None]) == 1
    root = next(record for record in recorder.records if record.parent_id is None)
    assert root.status == "completed"
    assert root.metadata["completion_status"] == "completed"
    assert root.metadata["fallback_reason"] == FallbackReason.PROVIDER_UNAVAILABLE.value
    fallback = next(
        record
        for record in recorder.records
        if record.name == "enterprise_ai.deterministic_fallback"
    )
    assert fallback.metadata["fallback_strategy"] == "extractive_grounded"
    assert fallback.metadata["selected_passage_count"] == 1
    assert fallback.metadata["supported_concept_count"] == 1
    serialized = repr((caplog.records, recorder.records, items))
    assert "provider-private-marker" not in serialized
    assert "provider-secret" not in serialized


@pytest.mark.asyncio
async def test_llm_unavailable_without_fallback_fails_safely_and_skips_memory(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = FakeTraceRecorder()
    runtime = failure_runtime(tmp_path, allow_fallback=False, recorder=recorder)
    graph_input = request(message="find leave policy log-private-query-marker")

    with caplog.at_level(logging.INFO, logger="enterprise_ai.graph.runtime"):
        items = [item async for item in runtime.astream(graph_input)]

    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    terminal = [
        item
        for item in events
        if item.event_type in {AgentEventType.RESPONSE_COMPLETED, AgentEventType.RESPONSE_FAILED}
    ]
    assert output.completion_status is ProcessingStatus.FAILED
    assert output.selected_route is Route.FAILURE
    assert output.response_text == "The request failed safely."
    assert output.evidence == ()
    assert output.citations == ()
    assert output.memory_update_status == "loaded"
    assert await runtime.inspect_memory(graph_input) is None
    assert [item.event_type for item in terminal] == [AgentEventType.RESPONSE_FAILED]
    assert len([item for item in items if item.output is not None]) == 1
    root = next(record for record in recorder.records if record.parent_id is None)
    assert root.status == "completed"
    assert root.metadata["completion_status"] == "failed"
    serialized = repr((caplog.records, recorder.records, items))
    assert "provider-private-marker" not in serialized
    assert "provider-secret" not in serialized
    assert "log-private-query-marker" not in repr(caplog.records)
