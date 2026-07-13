import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from enterprise_ai.graph.builder import build_graph
from enterprise_ai.graph.checkpointer import create_checkpointer
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput
from enterprise_ai.models.identity import UserRole
from enterprise_ai.research.models import (
    CollectionCatalog,
    CoverageStatus,
    ResearchPlan,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchTaskStatus,
    ResearchTaskType,
    ResearchWorkerInput,
    ResearchWorkerResult,
)
from enterprise_ai.research.service import ResearchService
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.security.authorization import AuthorizationService

from .evidence_fixtures import evidence


class UnusedRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("controlled workers own retrieval")


class OrderedWorker:
    def __init__(self, order: tuple[str, ...], build_fingerprint: str) -> None:
        self.order = order
        self.build_fingerprint = build_fingerprint
        self.started: set[str] = set()
        self.completed: list[str] = []
        self.changed = asyncio.Condition()

    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        async with self.changed:
            self.started.add(item.task.task_id)
            self.changed.notify_all()
            await self.changed.wait_for(
                lambda: (
                    len(self.started) == 3 and item.task.task_id == self.order[len(self.completed)]
                )
            )
            self.completed.append(item.task.task_id)
            self.changed.notify_all()
        item_number = int(item.task.task_id[-2:])
        controlled = evidence(
            item_number,
            document_id=UUID(int=100 + item_number),
            allowed_roles=frozenset({UserRole.ANALYST}),
            build_fingerprint=self.build_fingerprint,
            title=f"Controlled source {item_number}",
            text=f"Controlled evidence dimension {item_number}",
        )
        return ResearchWorkerResult(
            task_id=item.task.task_id,
            parent_task_id=None,
            depth=0,
            status=ResearchTaskStatus.COMPLETED,
            queries_executed=item.task.search.queries,
            retrieval_modes=("controlled",),
            evidence=(controlled,),
            coverage_status=CoverageStatus.SUFFICIENT,
            retrieval_calls=1,
        )


class ControlledService(ResearchService):
    def __init__(
        self, settings: RetrievalSettings, plan: ResearchPlan, worker: OrderedWorker
    ) -> None:
        super().__init__(
            settings,
            UnusedRetriever(),  # type: ignore[arg-type]
            AuthorizationService(),
            worker_factory=lambda _ledger: worker,
        )
        self.controlled_plan = plan

    async def plan(self, question: str, principal: object) -> ResearchPlan:
        del question, principal
        return self.controlled_plan


def _plan(fingerprint: str) -> ResearchPlan:
    tasks = tuple(
        ResearchTask(
            task_id=f"T{index:02d}",
            depth=0,
            task_type=ResearchTaskType.COMPARISON_DIMENSION,
            research_question=f"Controlled dimension {index}",
            search=ResearchSearchStrategy(queries=(f"controlled dimension {index}",)),
        )
        for index in range(1, 4)
    )
    return ResearchPlan(
        plan_id="RP-controlled-final",
        original_question="compare controlled dimensions",
        normalized_objective="compare controlled dimensions",
        research_scope="authorized",
        authorized_collection_summary=CollectionCatalog(
            build_fingerprint=fingerprint,
            document_count=3,
            departments=("payments",),
            document_types=("runbook",),
            statuses=("active",),
        ),
        tasks=tasks,
        expected_synthesis_dimensions=tuple(task.research_question for task in tasks),
    )


async def _execute(order: tuple[str, ...]) -> tuple[dict[str, object], list[str]]:
    settings = RetrievalSettings(research_max_depth=0)
    fingerprint = str(
        json.loads(settings.ingestion_manifest_path.read_text(encoding="utf-8"))[
            "build_fingerprint"
        ]
    )
    worker = OrderedWorker(order, fingerprint)
    service = ControlledService(settings, _plan(fingerprint), worker)
    graph = build_graph(
        settings,
        UnusedRetriever(),  # type: ignore[arg-type]
        checkpointer=create_checkpointer(),
        research=service,
    )
    runtime = GraphRuntime(graph, settings)
    graph_input = GraphInput(
        request_id=UUID(int=901),
        trace_id=UUID(int=902),
        session_id=UUID(int=903),
        principal=assessment_principal(UserRole.ANALYST),
        user_message="Compare controlled dimensions.",
        invocation_timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    output = await runtime.ainvoke(graph_input)
    snapshot = await runtime.inspect_state(graph_input)
    values = cast(Any, snapshot).values
    research = values["research_result"]
    normalized = {
        "plan": research.plan.model_dump(mode="json"),
        "budget_usage": research.budget_usage.model_dump(mode="json"),
        "worker_results": [
            item.model_dump(mode="json", exclude={"duration_seconds"})
            for item in research.worker_results
        ],
        "evidence_ledger": research.evidence_ledger.model_dump(mode="json"),
        "analysis_results": [item.model_dump(mode="json") for item in research.analysis_results],
        "conflicts": [item.model_dump(mode="json") for item in research.conflicts],
        "structured_conflicts": [
            item.model_dump(mode="json") for item in research.structured_conflicts
        ],
        "coverage": research.coverage.model_dump(mode="json"),
        "citations": [item.model_dump(mode="json") for item in output.citations],
        "final_output": output.model_dump(
            mode="json", exclude={"request_id", "trace_id", "session_id"}
        ),
        "memory_turn": {
            "sequence": output.turn_sequence,
            "status": output.memory_update_status,
            "response": output.response_text,
            "citations": [item.marker for item in output.citations],
        },
    }
    await runtime.aclose()
    return normalized, worker.completed


@pytest.mark.asyncio
async def test_final_result_is_independent_of_three_worker_completion_orders() -> None:
    orders = (
        ("T02", "T03", "T01"),
        ("T01", "T02", "T03"),
        ("T03", "T01", "T02"),
    )
    runs = [await _execute(order) for order in orders]

    assert [tuple(completed) for _, completed in runs] == list(orders)
    encoded = [json.dumps(result, sort_keys=True, separators=(",", ":")) for result, _ in runs]
    assert encoded[1:] == encoded[:-1]
