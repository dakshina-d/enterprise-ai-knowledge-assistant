"""Offline graph integration tests through the real MCP protocol path."""

import asyncio
from uuid import uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.mcp_tools.client import MCPEnterpriseClient
from enterprise_ai.mcp_tools.service import MCPEnterpriseService
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEventType
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import UserRole
from enterprise_ai.observability.tracing import FakeTraceRecorder, SafeTracer
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal


class UnusedRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("MCP requests must not use document retrieval")


def graph_input(role: UserRole, message: str) -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(role),
        user_message=message,
    )


def runtime(
    tracer: SafeTracer | None = None,
    mcp_service: MCPEnterpriseService | None = None,
) -> GraphRuntime:
    settings = RetrievalSettings()
    effective_tracer = tracer or SafeTracer()
    graph = build_graph(
        settings,
        UnusedRetriever(),  # type: ignore[arg-type]
        checkpointer=create_checkpointer(),
        tracer=effective_tracer,
        mcp_service=mcp_service,
    )
    return GraphRuntime(graph, settings, tracer=effective_tracer)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "tool"),
    [
        ("Who owns the payment-gateway service?", "get_service_profile"),
        ("What is the p95 latency for mobile-banking-api?", "get_operational_metrics"),
        ("Show planned changes for card-settlement.", "get_change_windows"),
    ],
)
async def test_graph_routes_typed_mcp_requests_without_document_citations(
    query: str, tool: str
) -> None:
    output = await runtime().ainvoke(graph_input(UserRole.ANALYST, query))

    assert output.completion_status is ProcessingStatus.COMPLETED
    assert output.selected_route is Route.MCP_TOOL
    assert output.mcp_result is not None
    assert output.mcp_result.tool_name == tool
    assert output.mcp_provenance is not None
    assert output.mcp_provenance.source_type == "mcp_tool"
    assert "Fictional enterprise MCP data" in output.response_text
    assert not output.evidence
    assert not output.citations


@pytest.mark.asyncio
async def test_viewer_denial_reveals_no_data_and_starts_no_mcp_span() -> None:
    recorder = FakeTraceRecorder()
    output = await runtime(SafeTracer(recorder)).ainvoke(
        graph_input(UserRole.VIEWER, "Who owns the payment-gateway service?")
    )

    assert output.completion_status is ProcessingStatus.DENIED
    assert output.selected_route is Route.DENY
    assert output.mcp_result is None
    assert "payment-gateway" not in output.response_text
    assert not any(item.name.startswith("enterprise_ai.mcp") for item in recorder.records)


@pytest.mark.asyncio
async def test_stream_events_are_safe_ordered_and_have_one_terminal_output() -> None:
    recorder = FakeTraceRecorder()
    query = "What is the p95 latency for mobile-banking-api? raw-query-marker"
    items = [
        item
        async for item in runtime(SafeTracer(recorder)).astream(
            graph_input(UserRole.ANALYST, query)
        )
    ]
    events = [item.event for item in items if item.event is not None]
    event_types = [item.event_type for item in events]

    assert [item.sequence_number for item in events] == list(range(len(events)))
    assert (
        event_types.index(AgentEventType.MCP_STARTED)
        < event_types.index(AgentEventType.MCP_TOOL_SELECTED)
        < event_types.index(AgentEventType.MCP_COMPLETED)
    )
    assert (
        sum(
            kind in {AgentEventType.RESPONSE_COMPLETED, AgentEventType.RESPONSE_FAILED}
            for kind in event_types
        )
        == 1
    )
    assert sum(item.output is not None for item in items) == 1
    serialized_events = repr(events)
    assert "raw-query-marker" not in serialized_events
    assert "Payments Platform" not in serialized_events
    serialized_traces = repr(recorder.records)
    assert "raw-query-marker" not in serialized_traces
    assert "p95_latency_ms" not in serialized_traces
    assert {item.name for item in recorder.records} >= {
        "enterprise_ai.mcp",
        "enterprise_ai.mcp.call",
    }


@pytest.mark.asyncio
async def test_concurrent_allowed_and_denied_graphs_do_not_leak() -> None:
    allowed, denied = await asyncio.gather(
        runtime().ainvoke(graph_input(UserRole.ANALYST, "Who owns the payment-gateway service?")),
        runtime().ainvoke(graph_input(UserRole.VIEWER, "Who owns the identity-access service?")),
    )

    assert allowed.mcp_provenance is not None
    assert allowed.mcp_provenance.record_identifier == "payment-gateway"
    assert denied.completion_status is ProcessingStatus.DENIED
    assert denied.mcp_provenance is None
    assert "identity-access" not in denied.response_text


class UnavailableClient(MCPEnterpriseClient):
    async def get_service_profile(self, arguments: object) -> object:
        raise RuntimeError("sensitive protocol detail")


@pytest.mark.asyncio
async def test_mcp_failure_is_safe_and_does_not_create_false_success() -> None:
    service = MCPEnterpriseService(
        client_factory=lambda: UnavailableClient.__new__(UnavailableClient)
    )
    items = [
        item
        async for item in runtime(mcp_service=service).astream(
            graph_input(UserRole.ANALYST, "Who owns the payment-gateway service?")
        )
    ]
    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    kinds = [item.event_type for item in events]

    assert output.completion_status is ProcessingStatus.FAILED
    assert output.selected_route is Route.FAILURE
    assert output.mcp_result is None
    assert "sensitive protocol detail" not in output.response_text
    assert (
        kinds.index(AgentEventType.MCP_STARTED)
        < kinds.index(AgentEventType.MCP_TOOL_SELECTED)
        < kinds.index(AgentEventType.MCP_FAILED)
    )
    assert any(
        item.node == "handle_failure" and item.event_type is AgentEventType.NODE_STARTED
        for item in events
    )
    assert any(
        item.node == "handle_failure" and item.event_type is AgentEventType.NODE_COMPLETED
        for item in events
    )
    assert kinds[-1] is AgentEventType.RESPONSE_FAILED
    assert [item.sequence_number for item in events] == list(range(len(events)))
    assert sum(kind is AgentEventType.RESPONSE_FAILED for kind in kinds) == 1
    assert sum(item.output is not None for item in items) == 1
    assert "sensitive protocol detail" not in repr(items)
