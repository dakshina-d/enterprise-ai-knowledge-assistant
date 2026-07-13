"""Executable LangGraph-native research worker fan-out."""

from typing import Annotated, TypedDict

from langgraph.types import Send

from enterprise_ai.graph.reducers import append_unique
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.research.models import ResearchPlan, ResearchTask, ResearchWorkerResult


class ResearchGraphState(TypedDict, total=False):
    plan: ResearchPlan
    principal: AuthenticatedPrincipal
    request_id: object
    trace_id: object
    session_id: object
    pending_tasks: tuple[ResearchTask, ...]
    worker_results: Annotated[tuple[ResearchWorkerResult, ...], append_unique]
    processed_task_ids: tuple[str, ...]
    round_number: int
    result: object


def dispatch_workers(state: ResearchGraphState) -> list[Send] | str:
    """Create exactly one task-scoped Send for each validated pending task."""
    tasks = tuple(sorted(state.get("pending_tasks", ()), key=lambda item: item.task_id))
    if not tasks:
        return "finalize_research"
    return [
        Send(
            "research_worker",
            {
                "principal": state["principal"],
                "request_id": state["request_id"],
                "trace_id": state["trace_id"],
                "session_id": state["session_id"],
                "research_task": task,
            },
        )
        for task in tasks
    ]
