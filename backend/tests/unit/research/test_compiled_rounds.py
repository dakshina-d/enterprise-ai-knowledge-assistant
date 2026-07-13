import asyncio
from uuid import uuid4

import pytest
from enterprise_ai.models.identity import AuthenticatedPrincipal, UserRole
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import (
    CollectionCatalog,
    CoverageStatus,
    ResearchChildTaskProposal,
    ResearchPlan,
    ResearchRequest,
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


class UnusedRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("injected workers must own controlled execution")


def _plan(task_count: int = 1) -> ResearchPlan:
    tasks = tuple(
        ResearchTask(
            task_id=f"T{index:02d}",
            depth=0,
            task_type=ResearchTaskType.INCIDENT_LOOKUP,
            research_question=f"Initial dimension {index}",
            search=ResearchSearchStrategy(queries=(f"initial dimension {index}",)),
        )
        for index in range(1, task_count + 1)
    )
    return ResearchPlan(
        plan_id="RP-controlled",
        original_question="controlled",
        normalized_objective="controlled",
        research_scope="authorized",
        authorized_collection_summary=CollectionCatalog(
            build_fingerprint="a" * 64,
            document_count=0,
            departments=(),
            document_types=(),
            statuses=(),
        ),
        tasks=tasks,
    )


class ControlledService(ResearchService):
    def __init__(self, settings: RetrievalSettings, plan: ResearchPlan, worker: object) -> None:
        super().__init__(
            settings,
            UnusedRetriever(),  # type: ignore[arg-type]
            AuthorizationService(),
            worker_factory=lambda _budget: worker,  # type: ignore[arg-type,return-value]
        )
        self.controlled_plan = plan

    async def plan(self, question: str, principal: AuthenticatedPrincipal) -> ResearchPlan:
        del question, principal
        return self.controlled_plan


class ProposingWorker:
    def __init__(self, ledger: BudgetLedger | None = None) -> None:
        self.started: list[tuple[str, int]] = []
        self.ledger = ledger

    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        self.started.append((item.task.task_id, item.task.depth))
        proposal: tuple[ResearchChildTaskProposal, ...] = ()
        if item.task.depth == 0:
            proposal = (
                ResearchChildTaskProposal(
                    parent_task_id=item.task.task_id,
                    task_type=ResearchTaskType.GAP_INVESTIGATION,
                    research_question="Investigate HorizonPay incident recovery actions",
                    queries=("investigate horizonpay incident recovery actions",),
                    reason="missing comparison side",
                ),
            )
        return ResearchWorkerResult(
            task_id=item.task.task_id,
            parent_task_id=item.task.parent_task_id,
            depth=item.task.depth,
            status=ResearchTaskStatus.PARTIAL,
            queries_executed=item.task.search.queries,
            retrieval_modes=("fake",),
            evidence=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            gaps=("missing comparison side",),
            child_task_proposals=proposal,
            retrieval_calls=1,
        )


class FailedWorker(ProposingWorker):
    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        if item.task.task_id == "T02":
            self.started.append((item.task.task_id, item.task.depth))
            return ResearchWorkerResult(
                task_id=item.task.task_id,
                parent_task_id=None,
                depth=item.task.depth,
                status=ResearchTaskStatus.FAILED,
                queries_executed=(),
                retrieval_modes=(),
                evidence=(),
                coverage_status=CoverageStatus.FAILED,
                gaps=("timed out dimension",),
                error_category="worker_timeout",
            )
        return await super().execute(item)


class BlockingWorker:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("blocked worker must be cancelled")


def _request() -> ResearchRequest:
    return ResearchRequest(
        question="controlled",
        principal=assessment_principal(UserRole.ANALYST),
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_compiled_graph_dispatches_child_in_later_round() -> None:
    worker = ProposingWorker()
    result = await ControlledService(RetrievalSettings(research_max_depth=1), _plan(), worker).run(
        _request()
    )
    assert worker.started == [("T01", 0), ("T01.C01", 1)]
    assert tuple(item.task_id for item in result.worker_results) == ("T01", "T01.C01")
    assert result.budget_usage.tasks == 2


@pytest.mark.asyncio
async def test_maximum_depth_stops_additional_children() -> None:
    worker = ProposingWorker()
    result = await ControlledService(RetrievalSettings(research_max_depth=0), _plan(), worker).run(
        _request()
    )
    assert worker.started == [("T01", 0)]
    assert result.coverage.status is CoverageStatus.INSUFFICIENT


@pytest.mark.asyncio
async def test_parallel_equivalent_children_are_dispatched_once() -> None:
    worker = ProposingWorker()
    result = await ControlledService(RetrievalSettings(research_max_depth=1), _plan(2), worker).run(
        _request()
    )
    children = [item for item in worker.started if item[1] == 1]
    assert children == [("T01.C01", 1)]
    assert result.budget_usage.tasks == 3


@pytest.mark.asyncio
async def test_typed_timeout_continues_or_fails_by_partial_policy() -> None:
    partial_worker = FailedWorker()
    partial = await ControlledService(
        RetrievalSettings(research_max_depth=0, research_allow_partial_results=True),
        _plan(3),
        partial_worker,
    ).run(_request())
    assert [item.status for item in partial.worker_results].count(ResearchTaskStatus.FAILED) == 1
    assert partial.coverage.status is CoverageStatus.INSUFFICIENT
    strict_worker = FailedWorker()
    strict = await ControlledService(
        RetrievalSettings(research_max_depth=0, research_allow_partial_results=False),
        _plan(3),
        strict_worker,
    ).run(_request())
    assert strict.coverage.status is CoverageStatus.FAILED


@pytest.mark.asyncio
async def test_outer_cancellation_stops_blocked_graph_workers() -> None:
    worker = BlockingWorker()
    service = ControlledService(RetrievalSettings(), _plan(), worker)
    operation = asyncio.create_task(service.run(_request()))
    await worker.started.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert worker.cancelled.is_set()
