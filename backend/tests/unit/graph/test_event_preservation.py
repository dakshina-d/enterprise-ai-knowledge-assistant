"""Request-local graph event preservation across guarded node failures."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.events import collect_node_events, event
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput
from enterprise_ai.graph.state import GraphState
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEvent, AgentEventStatus, AgentEventType
from enterprise_ai.models.graph import Route
from enterprise_ai.models.identity import AuthenticatedPrincipal, UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.tools.python_analysis.exceptions import AnalysisValidationError
from enterprise_ai.tools.python_analysis.models import AnalysisRequest, AnalysisResult
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool


class UnusedRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("analysis routes must not retrieve documents")


class FailingAnalysisTool(PythonAnalysisTool):
    async def execute(
        self,
        principal: AuthenticatedPrincipal,
        request: AnalysisRequest,
        *,
        request_id: UUID,
        trace_id: UUID,
    ) -> AnalysisResult:
        del principal, request, request_id, trace_id
        raise AnalysisValidationError("private-analysis-marker internal/analysis/path")


def graph_input() -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Count payment incidents by root cause.",
    )


def runtime(*, failing: bool) -> GraphRuntime:
    settings = RetrievalSettings()
    analysis = FailingAnalysisTool(settings) if failing else PythonAnalysisTool(settings)
    graph = build_graph(
        settings,
        UnusedRetriever(),  # type: ignore[arg-type]
        checkpointer=create_checkpointer(),
        analysis=analysis,
    )
    return GraphRuntime(graph, settings)


@pytest.mark.asyncio
async def test_guarded_analysis_events_survive_exception_without_duplication() -> None:
    service = runtime(failing=True)
    request = graph_input()

    items = [item async for item in service.astream(request)]
    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    snapshot = await service.inspect_state(request)
    retained = snapshot.values["activity_events"]
    kinds = [item.event_type for item in events]

    expected = (
        AgentEventType.TOOL_AUTHORIZATION_STARTED,
        AgentEventType.TOOL_AUTHORIZED,
        AgentEventType.TOOL_STARTED,
        AgentEventType.TOOL_FAILED,
    )
    positions = [kinds.index(kind) for kind in expected]
    assert positions == sorted(positions)
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
    assert [item.event_id for item in retained] == [item.event_id for item in events]
    assert len({item.event_id for item in events}) == len(events)
    assert sum(kind is AgentEventType.RESPONSE_FAILED for kind in kinds) == 1
    assert sum(item.output is not None for item in items) == 1
    assert output.completion_status is ProcessingStatus.FAILED
    assert output.selected_route is Route.FAILURE
    assert output.response_text == "The request failed safely."
    assert output.analysis_result is None
    assert output.evidence == output.citations == ()
    assert "private-analysis-marker" not in repr((events, output, snapshot.values))
    assert "internal/analysis/path" not in repr((events, output, snapshot.values))


@pytest.mark.asyncio
async def test_successful_analysis_keeps_completed_terminal_contract() -> None:
    items = [item async for item in runtime(failing=False).astream(graph_input())]
    events = [item.event for item in items if item.event is not None]
    output = next(item.output for item in items if item.output is not None)
    kinds = [item.event_type for item in events]

    assert output.completion_status is ProcessingStatus.COMPLETED
    assert output.selected_route is Route.PYTHON_ANALYSIS
    assert output.analysis_result is not None
    assert output.deterministic_analysis_rendering_used
    assert AgentEventType.TOOL_COMPLETED in kinds
    assert AgentEventType.TOOL_FAILED not in kinds
    assert kinds[-1] is AgentEventType.RESPONSE_COMPLETED
    assert [item.sequence_number for item in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_concurrent_success_and_failure_event_journals_are_isolated() -> None:
    failed_request = graph_input()
    successful_request = graph_input()

    async def collect(
        service: GraphRuntime,
        request: GraphInput,
    ) -> tuple[list[AgentEvent], GraphOutput]:
        items = [item async for item in service.astream(request)]
        events = [item.event for item in items if item.event is not None]
        output = next(item.output for item in items if item.output is not None)
        return events, output

    (failed_events, failed_output), (successful_events, successful_output) = await asyncio.gather(
        collect(runtime(failing=True), failed_request),
        collect(runtime(failing=False), successful_request),
    )

    for events, request in (
        (failed_events, failed_request),
        (successful_events, successful_request),
    ):
        assert [item.sequence_number for item in events] == list(range(len(events)))
        assert {item.request_id for item in events} == {request.request_id}
        assert {item.trace_id for item in events} == {request.trace_id}
        assert {item.session_id for item in events} == {request.session_id}
    assert failed_output.completion_status is ProcessingStatus.FAILED
    assert successful_output.completion_status is ProcessingStatus.COMPLETED
    assert {item.event_id for item in failed_events}.isdisjoint(
        {item.event_id for item in successful_events}
    )


@pytest.mark.asyncio
async def test_event_journal_resets_sequence_for_new_concurrent_invocations() -> None:
    async def create(request: GraphInput) -> tuple[AgentEvent, ...]:
        state = cast(
            GraphState,
            {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "session_id": request.session_id,
                "activity_events": (),
            },
        )
        with collect_node_events(state) as journal:
            for _ in range(3):
                event(
                    state,
                    AgentEventType.NODE_STARTED,
                    AgentEventStatus.STARTED,
                    "Safe test event.",
                )
                await asyncio.sleep(0)
        return tuple(journal.emitted)

    first_request, second_request = graph_input(), graph_input()
    first, second = await asyncio.gather(
        create(first_request),
        create(second_request),
    )

    assert [item.sequence_number for item in first] == [0, 1, 2]
    assert [item.sequence_number for item in second] == [0, 1, 2]
    assert {item.request_id for item in first} == {first_request.request_id}
    assert {item.request_id for item in second} == {second_request.request_id}
