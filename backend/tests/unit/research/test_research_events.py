import json
from pathlib import Path
from uuid import uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.models.events import AgentEvent, AgentEventType
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchTaskStatus,
    ResearchWorkerInput,
    ResearchWorkerResult,
)
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal

from .evidence_fixtures import evidence
from .test_compiled_rounds import ControlledService, FailedWorker, ProposingWorker, _plan
from .test_executable_timeouts import UnusedRetriever


class SuccessfulWorker:
    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        found = evidence(int(item.task.task_id[-1]))
        found = found.model_copy(
            update={
                "evidence": found.evidence.model_copy(
                    update={"allowed_roles": frozenset({UserRole.ANALYST})}
                )
            }
        )
        return ResearchWorkerResult(
            task_id=item.task.task_id,
            parent_task_id=item.task.parent_task_id,
            depth=item.task.depth,
            status=ResearchTaskStatus.COMPLETED,
            queries_executed=item.task.search.queries,
            retrieval_modes=("fake",),
            evidence=(found,),
            coverage_status=CoverageStatus.SUFFICIENT,
        )


def _runtime() -> tuple[GraphRuntime, GraphInput]:
    settings = RetrievalSettings(research_max_depth=1)
    research = ControlledService(settings, _plan(), ProposingWorker())
    graph = build_graph(
        settings,
        UnusedRetriever(),
        checkpointer=create_checkpointer(),
        research=research,
    )
    request = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Compare all incidents across the last year",
    )
    return GraphRuntime(graph, settings), request


@pytest.mark.asyncio
async def test_compiled_public_stream_is_correlated_monotonic_and_singular() -> None:
    runtime, request = _runtime()
    items = [item async for item in runtime.astream(request)]
    events = [item.event for item in items if item.event is not None]
    outputs = [item.output for item in items if item.output is not None]
    assert [item.sequence_number for item in events] == list(range(len(events)))
    assert len({item.event_id for item in events}) == len(events)
    assert {item.request_id for item in events} == {request.request_id}
    assert {item.trace_id for item in events} == {request.trace_id}
    assert {item.session_id for item in events} == {request.session_id}
    assert len(outputs) == 1 and items[-1].output is not None
    terminals = [
        item
        for item in events
        if item.event_type in {AgentEventType.RESPONSE_COMPLETED, AgentEventType.RESPONSE_FAILED}
    ]
    assert len(terminals) == 1 and terminals[0] is events[-1]


@pytest.mark.asyncio
async def test_insufficient_recursive_stream_has_worker_lifecycles_and_safe_payloads() -> None:
    runtime, request = _runtime()
    events = [item.event async for item in runtime.astream(request) if item.event is not None]
    kinds = [item.event_type for item in events]
    assert kinds.count(AgentEventType.RESEARCH_STARTED) == 1
    assert kinds.count(AgentEventType.RESEARCH_PARTIAL) == 1
    assert AgentEventType.RESEARCH_COMPLETED not in kinds
    assert kinds.count(AgentEventType.RESEARCH_CHILD_TASKS_CREATED) == 1
    dispatched = [
        item for item in events if item.event_type is AgentEventType.RESEARCH_WORKER_DISPATCHED
    ]
    started = [item for item in events if item.event_type is AgentEventType.RESEARCH_WORKER_STARTED]
    completed = [
        item for item in events if item.event_type is AgentEventType.RESEARCH_WORKER_COMPLETED
    ]
    assert len(dispatched) == len(started) == len(completed) == 2
    assert all(
        item.payload.task_id
        and item.payload.depth is not None
        and item.payload.round_number is not None
        for item in started
    )
    serialized = " ".join(item.model_dump_json() for item in events).casefold()
    for forbidden in (
        "compare all incidents",
        "evidence body",
        "stack trace",
        "system prompt",
        "scratchpad",
        "api_key",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_concurrent_invocations_have_isolated_sequences_and_ids() -> None:
    first_runtime, first = _runtime()
    second_runtime, second = _runtime()

    async def collect(runtime: GraphRuntime, request: GraphInput) -> list[AgentEvent]:
        return [item.event async for item in runtime.astream(request) if item.event]

    first_events, second_events = await __import__("asyncio").gather(
        collect(first_runtime, first), collect(second_runtime, second)
    )
    assert [item.sequence_number for item in first_events] == list(range(len(first_events)))
    assert [item.sequence_number for item in second_events] == list(range(len(second_events)))
    assert {item.event_id for item in first_events}.isdisjoint(
        item.event_id for item in second_events
    )


@pytest.mark.asyncio
async def test_compiled_failed_research_has_one_failed_terminal_and_output() -> None:
    settings = RetrievalSettings(research_max_depth=0, research_allow_partial_results=False)
    research = ControlledService(settings, _plan(2), FailedWorker())
    graph = build_graph(
        settings,
        UnusedRetriever(),
        checkpointer=create_checkpointer(),
        research=research,
    )
    request = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Compare all incidents across the last year",
    )
    items = [item async for item in GraphRuntime(graph, settings).astream(request)]
    events = [item.event for item in items if item.event]
    kinds = [item.event_type for item in events]
    assert kinds.count(AgentEventType.RESEARCH_WORKER_FAILED) == 1
    assert kinds.count(AgentEventType.RESEARCH_FAILED) == 1
    assert AgentEventType.RESEARCH_COMPLETED not in kinds
    assert AgentEventType.RESEARCH_PARTIAL not in kinds
    assert kinds.count(AgentEventType.RESPONSE_FAILED) == 1
    assert len([item for item in items if item.output]) == 1


@pytest.mark.asyncio
async def test_compiled_sufficient_research_has_one_success_terminal(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"build_fingerprint": "b" * 64}), encoding="utf-8")
    settings = RetrievalSettings(ingestion_manifest_path=manifest)
    plan = _plan(2)
    plan = plan.model_copy(
        update={
            "authorized_collection_summary": plan.authorized_collection_summary.model_copy(
                update={"build_fingerprint": "b" * 64}
            )
        }
    )
    graph = build_graph(
        settings,
        UnusedRetriever(),
        checkpointer=create_checkpointer(),
        research=ControlledService(settings, plan, SuccessfulWorker()),
    )
    request = GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Compare all incidents across the last year",
    )
    items = [item async for item in GraphRuntime(graph, settings).astream(request)]
    events = [item.event for item in items if item.event]
    kinds = [item.event_type for item in events]
    assert kinds.count(AgentEventType.RESEARCH_COMPLETED) == 1
    assert AgentEventType.RESEARCH_PARTIAL not in kinds
    assert AgentEventType.RESEARCH_FAILED not in kinds
    assert kinds.count(AgentEventType.RESPONSE_COMPLETED) == 1
    assert events[-1].event_type is AgentEventType.RESPONSE_COMPLETED
    assert len([item for item in items if item.output]) == 1
