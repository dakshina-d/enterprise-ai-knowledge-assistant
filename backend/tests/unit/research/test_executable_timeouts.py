import asyncio
from uuid import uuid4

import pytest
from enterprise_ai.models.identity import AuthenticatedPrincipal, UserRole
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import (
    CollectionCatalog,
    ResearchBudget,
    ResearchPlan,
    ResearchRequest,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchTaskType,
    ResearchWorkerInput,
)
from enterprise_ai.research.service import ResearchService
from enterprise_ai.research.worker import ResearchWorker
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.retrieval.hybrid.models import CompletionStatus, HybridRetrievalResult
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool


class BlockingPlanner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def create_plan(self, question: str, catalog: CollectionCatalog) -> object:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("planner must time out")


class StaticCatalogs:
    def build(self, principal: object) -> CollectionCatalog:
        return CollectionCatalog(
            build_fingerprint="a" * 64,
            document_count=0,
            departments=(),
            document_types=(),
            statuses=(),
        )


class UnusedRetriever:
    async def retrieve(self, *args: object, **kwargs: object) -> HybridRetrievalResult:
        raise AssertionError("no worker may run after planner timeout")


@pytest.mark.asyncio
async def test_real_planner_timeout_cancels_planner_before_workers() -> None:
    settings = RetrievalSettings(research_planner_timeout_seconds=0.01)
    service = ResearchService(settings, UnusedRetriever(), AuthorizationService())
    planner = BlockingPlanner()
    service.catalogs = StaticCatalogs()  # type: ignore[assignment]
    service.planner = planner  # type: ignore[assignment]
    with pytest.raises(TimeoutError):
        await service.plan("safe", assessment_principal(UserRole.ANALYST))
    assert planner.started.is_set() and planner.cancelled.is_set()


class DeadlinePlannerService(ResearchService):
    def __init__(self, settings: RetrievalSettings) -> None:
        super().__init__(settings, UnusedRetriever(), AuthorizationService())
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def plan(self, question: str, principal: AuthenticatedPrincipal) -> ResearchPlan:
        del question, principal
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        raise AssertionError("outer deadline must cancel planning")


@pytest.mark.asyncio
async def test_total_research_deadline_wins_over_component_timeout() -> None:
    service = DeadlinePlannerService(
        RetrievalSettings(
            research_max_execution_seconds=0.01,
            research_planner_timeout_seconds=10,
        )
    )
    identifier = uuid4()
    request = ResearchRequest(
        question="safe",
        principal=assessment_principal(UserRole.ANALYST),
        request_id=identifier,
        trace_id=uuid4(),
        session_id=uuid4(),
    )
    with pytest.raises(TimeoutError):
        await service.run(request)
    assert service.started.is_set() and service.cancelled.is_set()


class ControlledRetriever:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def retrieve(
        self, principal: object, query: str, **kwargs: object
    ) -> HybridRetrievalResult:
        self.started.append(query)
        if query == "timeout":
            await asyncio.Event().wait()
        return HybridRetrievalResult(evidence=(), completion_status=CompletionStatus.COMPLETE)


def _budget(retrievals: int) -> ResearchBudget:
    return ResearchBudget(
        maximum_depth=1,
        maximum_total_tasks=3,
        maximum_retrieval_calls=retrievals,
        maximum_analysis_calls=0,
        maximum_llm_calls=1,
        maximum_evidence_items=5,
        maximum_evidence_characters=100,
    )


def _input(query: str, task_id: str) -> ResearchWorkerInput:
    return ResearchWorkerInput(
        principal=assessment_principal(UserRole.ANALYST),
        task=ResearchTask(
            task_id=task_id,
            depth=0,
            task_type=ResearchTaskType.TARGETED_LOOKUP,
            research_question=query,
            search=ResearchSearchStrategy(queries=(query,)),
        ),
        request_id=uuid4(),
        trace_id=uuid4(),
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_worker_timeout_consumes_started_budget_and_blocks_extra_call() -> None:
    settings = RetrievalSettings(research_worker_timeout_seconds=0.01)
    retriever = ControlledRetriever()
    ledger = BudgetLedger(_budget(2))
    worker = ResearchWorker(
        retriever,
        ledger,
        settings.research_worker_timeout_seconds,
        PythonAnalysisTool(settings),
        AuthorizationService(),
    )
    results = await asyncio.gather(
        worker.execute(_input("success", "T1")),
        worker.execute(_input("timeout", "T2")),
        worker.execute(_input("never", "T3")),
    )
    assert sorted(retriever.started) == ["success", "timeout"]
    assert [item.error_category for item in results] == [None, "worker_timeout", "budget_exhausted"]
    usage = await ledger.usage()
    assert usage.retrieval_calls == 2 and usage.exhausted
