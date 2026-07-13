import asyncio
from uuid import uuid4

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphStreamItem
from enterprise_ai.models.events import AgentEventType
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.service import ResearchService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.security.authorization import AuthorizationService

from .test_compiled_rounds import ControlledService, ProposingWorker, _plan
from .test_executable_timeouts import (
    BlockingPlanner,
    DeadlinePlannerService,
    StaticCatalogs,
    UnusedRetriever,
)


def _request() -> GraphInput:
    return GraphInput(
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Compare all incidents across the last year",
    )


async def _stream(settings: RetrievalSettings, research: ResearchService) -> list[GraphStreamItem]:
    graph = build_graph(
        settings, UnusedRetriever(), checkpointer=create_checkpointer(), research=research
    )
    return [item async for item in GraphRuntime(graph, settings).astream(_request())]


@pytest.mark.asyncio
async def test_compiled_planner_timeout_stream_fails_once_before_dispatch() -> None:
    settings = RetrievalSettings(research_planner_timeout_seconds=0.01)
    research = ResearchService(settings, UnusedRetriever(), AuthorizationService())
    planner = BlockingPlanner()
    research.catalogs = StaticCatalogs()  # type: ignore[assignment]
    research.planner = planner  # type: ignore[assignment]
    items = await _stream(settings, research)
    events = [item.event for item in items if item.event]
    kinds = [item.event_type for item in events]
    assert AgentEventType.RESEARCH_STARTED in kinds
    assert AgentEventType.RESEARCH_PLANNING_STARTED in kinds
    assert AgentEventType.RESEARCH_PLAN_CREATED not in kinds
    assert AgentEventType.RESEARCH_WORKER_DISPATCHED not in kinds
    assert kinds.count(AgentEventType.RESEARCH_FAILED) == 1
    assert kinds.count(AgentEventType.RESPONSE_FAILED) == 1
    assert events[-1].event_type is AgentEventType.RESPONSE_FAILED
    assert len([item for item in items if item.output]) == 1
    assert planner.cancelled.is_set()


@pytest.mark.asyncio
async def test_compiled_total_deadline_stream_fails_once_and_cleans_up() -> None:
    settings = RetrievalSettings(
        research_max_execution_seconds=0.01, research_planner_timeout_seconds=10
    )
    research = DeadlinePlannerService(settings)
    items = await _stream(settings, research)
    kinds = [item.event.event_type for item in items if item.event]
    assert kinds.count(AgentEventType.RESEARCH_FAILED) == 1
    assert AgentEventType.RESEARCH_COMPLETED not in kinds
    assert AgentEventType.RESEARCH_PARTIAL not in kinds
    assert kinds.count(AgentEventType.RESPONSE_FAILED) == 1
    assert research.cancelled.is_set()


@pytest.mark.asyncio
async def test_compiled_budget_exhaustion_stream_is_partial_and_singular() -> None:
    settings = RetrievalSettings(
        research_max_depth=1,
        research_max_total_tasks=1,
        research_allow_partial_results=True,
    )
    research = ControlledService(settings, _plan(), ProposingWorker())
    items = await _stream(settings, research)
    events = [item.event for item in items if item.event]
    kinds = [item.event_type for item in events]
    assert kinds.count(AgentEventType.RESEARCH_BUDGET_EXHAUSTED) == 1
    assert kinds.count(AgentEventType.RESEARCH_PARTIAL) == 1
    assert (
        sum(
            kind in {AgentEventType.RESPONSE_COMPLETED, AgentEventType.RESPONSE_FAILED}
            for kind in kinds
        )
        == 1
    )
    assert len([item for item in items if item.output]) == 1


@pytest.mark.asyncio
async def test_stream_consumer_cancellation_propagates_without_false_terminal() -> None:
    settings = RetrievalSettings(
        research_max_execution_seconds=10, research_planner_timeout_seconds=10
    )
    research = DeadlinePlannerService(settings)
    graph = build_graph(
        settings, UnusedRetriever(), checkpointer=create_checkpointer(), research=research
    )
    runtime = GraphRuntime(graph, settings)
    seen = []

    async def consume() -> None:
        async for item in runtime.astream(_request()):
            seen.append(item)

    task = asyncio.create_task(consume())
    await research.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    kinds = [item.event.event_type for item in seen if item.event]
    assert AgentEventType.RESPONSE_COMPLETED not in kinds
    assert AgentEventType.RESPONSE_FAILED not in kinds
    assert research.cancelled.is_set()
