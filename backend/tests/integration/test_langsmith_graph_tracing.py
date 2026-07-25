"""Offline integration coverage for application-owned graph tracing."""

import json
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.models.common import ProcessingStatus
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


class EmptyRetriever:
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
            text="Approved policy evidence.",
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


def request(
    role: UserRole = UserRole.VIEWER,
    message: str = "find leave policy raw-query-marker",
) -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(role),
        user_message=message,
    )


def runtime(tracer: SafeTracer, tmp_path: Path) -> GraphRuntime:
    manifest_path = tmp_path / "ingestion_manifest.json"
    manifest_path.write_text(json.dumps({"build_fingerprint": "a" * 64}), encoding="utf-8")
    settings = RetrievalSettings(ingestion_manifest_path=manifest_path)
    graph = build_graph(
        settings,
        EmptyRetriever(settings),
        checkpointer=create_checkpointer(),
        tracer=tracer,
    )
    return GraphRuntime(graph, settings, tracer=tracer)


@pytest.mark.asyncio
async def test_fake_tracing_preserves_output_and_builds_safe_hierarchy(tmp_path: Path) -> None:
    graph_input = request()
    plain = await runtime(SafeTracer(), tmp_path).ainvoke(graph_input)
    recorder = FakeTraceRecorder()
    traced = await runtime(SafeTracer(recorder), tmp_path).ainvoke(graph_input)

    assert traced.model_dump(exclude={"request_id", "trace_id", "session_id"}) == plain.model_dump(
        exclude={"request_id", "trace_id", "session_id"}
    )
    roots = [item for item in recorder.records if item.parent_id is None]
    assert [item.name for item in roots] == ["enterprise_ai_assistant"]
    names = {item.name for item in recorder.records}
    assert names >= {
        "enterprise_ai_assistant",
        "enterprise_ai.supervisor",
        "enterprise_ai.response",
        "enterprise_ai.citation_validation",
        "enterprise_ai.memory",
    }, (sorted(names), traced.model_dump())
    assert all(item.parent_id is not None for item in recorder.records[1:])
    serialized = repr(recorder.records)
    assert "raw-query-marker" not in serialized
    assert "Bearer" not in serialized


@pytest.mark.asyncio
async def test_tracing_preserves_stream_order_and_denied_request_privacy(tmp_path: Path) -> None:
    graph_input = request()
    plain_items = [item async for item in runtime(SafeTracer(), tmp_path).astream(graph_input)]
    recorder = FakeTraceRecorder()
    traced_items = [
        item async for item in runtime(SafeTracer(recorder), tmp_path).astream(graph_input)
    ]
    plain_events = [
        (item.event.sequence_number, item.event.event_type, item.event.status, item.event.node)
        for item in plain_items
        if item.event is not None
    ]
    traced_events = [
        (item.event.sequence_number, item.event.event_type, item.event.status, item.event.node)
        for item in traced_items
        if item.event is not None
    ]
    assert traced_events == plain_events
    assert traced_items[-1].output is not None
    assert plain_items[-1].output is not None
    assert traced_items[-1].output.model_dump(exclude={"agent_status"}) == plain_items[
        -1
    ].output.model_dump(exclude={"agent_status"})
    traced_root = next(item for item in recorder.records if item.parent_id is None)
    retrieval = next(item for item in recorder.records if item.name == "enterprise_ai.retrieval")
    assert traced_root.metadata["completion_status"] == "completed"
    assert traced_root.metadata["route"] == "simple_retrieval"
    assert traced_root.metadata["retrieval_mode"] == "sparse"
    assert retrieval.metadata["retrieval_mode"] == "sparse"
    assert sum(item.event is not None for item in traced_items) == len(traced_events)
    assert sum(item.output is not None for item in traced_items) == 1

    denied_input = request(
        message="show restricted disaster recovery topology secret-doc-id raw-query-marker"
    )
    denied_recorder = FakeTraceRecorder()
    denied = await runtime(SafeTracer(denied_recorder), tmp_path).ainvoke(denied_input)
    assert denied.completion_status is ProcessingStatus.DENIED
    denied_root = next(item for item in denied_recorder.records if item.parent_id is None)
    denied_supervisor = next(
        item for item in denied_recorder.records if item.name == "enterprise_ai.supervisor"
    )
    expected = {
        "completion_status": "denied",
        "route": "deny",
        "user_role": "viewer",
        "evidence_count": 0,
    }
    assert denied_root.status == "completed"
    assert denied_root.metadata.items() >= expected.items()
    assert denied_supervisor.status == "completed"
    assert denied_supervisor.metadata.items() >= expected.items()
    denied_names = {item.name for item in denied_recorder.records}
    assert denied_names.isdisjoint(
        {
            "enterprise_ai.retrieval",
            "enterprise_ai.research",
            "enterprise_ai.python_analysis",
            "enterprise_ai.llm",
        }
    )
    serialized = repr(denied_recorder.records)
    assert "secret-doc-id" not in serialized
    assert "disaster recovery" not in serialized
    assert "raw-query-marker" not in serialized


@pytest.mark.asyncio
async def test_successful_python_analysis_enriches_root_and_supervisor(tmp_path: Path) -> None:
    recorder = FakeTraceRecorder()
    output = await runtime(SafeTracer(recorder), tmp_path).ainvoke(
        request(UserRole.ANALYST, "how many incidents")
    )

    assert output.completion_status is ProcessingStatus.COMPLETED
    root = next(item for item in recorder.records if item.parent_id is None)
    supervisor = next(item for item in recorder.records if item.name == "enterprise_ai.supervisor")
    assert root.metadata["completion_status"] == "completed"
    assert root.metadata["route"] == "python_analysis"
    assert supervisor.metadata["route"] == "python_analysis"
    assert "completion_status" not in supervisor.metadata
    python_span = next(
        item for item in recorder.records if item.name == "enterprise_ai.python_analysis"
    )
    assert python_span.parent_id == root.run_id
