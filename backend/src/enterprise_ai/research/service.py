"""Application-owned LangGraph coordinator for bounded recursive research rounds."""

import asyncio
from collections.abc import Callable
from typing import Any, Protocol, cast

from langgraph.graph import END, START, StateGraph

from enterprise_ai.graph.dependencies import KnowledgeRetriever
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.observability.tracing import SafeTracer
from enterprise_ai.research.aggregation import aggregate_evidence
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.collection_catalog import CollectionCatalogService
from enterprise_ai.research.conflicts import detect_conflicts
from enterprise_ai.research.coverage import assess_coverage
from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchBudget,
    ResearchGap,
    ResearchPlan,
    ResearchProvenance,
    ResearchRequest,
    ResearchResult,
    ResearchSearchStrategy,
    ResearchTask,
    ResearchWorkerInput,
    ResearchWorkerResult,
)
from enterprise_ai.research.plan_validator import ResearchPlanValidationError, compile_plan
from enterprise_ai.research.planner import FakeResearchPlanner
from enterprise_ai.research.worker import ResearchWorker
from enterprise_ai.research.worker_graph import ResearchGraphState, dispatch_workers
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.filters import DenseQueryFilters
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool


class WorkerExecutor(Protocol):
    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult: ...


class ResearchService:
    def __init__(
        self,
        settings: RetrievalSettings,
        retriever: KnowledgeRetriever,
        authorization: AuthorizationService,
        analysis: PythonAnalysisTool | None = None,
        worker_factory: Callable[[BudgetLedger], WorkerExecutor] | None = None,
        tracer: SafeTracer | None = None,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.authorization = authorization
        self.analysis = analysis or PythonAnalysisTool(settings)
        self.catalogs = CollectionCatalogService(settings, authorization)
        self.planner = FakeResearchPlanner()
        self.worker_factory = worker_factory
        self.tracer = tracer or SafeTracer()

    async def plan(self, question: str, principal: AuthenticatedPrincipal) -> ResearchPlan:
        catalog = self.catalogs.build(principal)
        proposed = await asyncio.wait_for(
            self.planner.create_plan(question, catalog),
            timeout=self.settings.research_planner_timeout_seconds,
        )
        return compile_plan(proposed, self.settings)

    async def run(self, request: ResearchRequest) -> ResearchResult:
        async with asyncio.timeout(self.settings.research_max_execution_seconds):
            return await self._run_bounded(request)

    async def _run_bounded(self, request: ResearchRequest) -> ResearchResult:
        budget = self._budget()
        ledger = BudgetLedger(budget)
        if not await ledger.consume("llm_calls"):
            raise RuntimeError("research planning budget unavailable")
        async with self.tracer.span(
            "enterprise_ai.research.plan",
            metadata={"planner_version": "1", "user_role": request.principal.identity.role},
        ) as plan_span:
            plan = await self._plan_with_repair(request.question, request.principal, ledger)
            if plan_span is not None:
                plan_span.update_metadata({"root_task_count": len(plan.tasks)})
        semaphore = asyncio.Semaphore(self.settings.research_max_parallel_workers)
        worker: WorkerExecutor = (
            self.worker_factory(ledger)
            if self.worker_factory
            else ResearchWorker(
                self.retriever,
                ledger,
                self.settings.research_worker_timeout_seconds,
                self.analysis,
                self.authorization,
            )
        )
        graph = StateGraph(ResearchGraphState)

        async def initialize(state: ResearchGraphState) -> dict[str, object]:
            approved = []
            for task in plan.tasks:
                if await ledger.consume("tasks"):
                    approved.append(task)
            return {"plan": plan, "pending_tasks": tuple(approved), "round_number": 0}

        async def execute(state: ResearchGraphState) -> dict[str, object]:
            task = cast(ResearchTask, state["research_task"])  # type: ignore[typeddict-item]
            async with self.tracer.span(
                "enterprise_ai.research.worker",
                metadata={
                    "task_id": task.task_id,
                    "parent_task_id": task.parent_task_id,
                    "depth": task.depth,
                    "round": state.get("round_number", 0),
                },
            ) as worker_span:
                async with semaphore:
                    result = await worker.execute(
                        ResearchWorkerInput(
                            principal=state["principal"],
                            task=task,
                            request_id=cast(Any, state["request_id"]),
                            trace_id=cast(Any, state["trace_id"]),
                            session_id=cast(Any, state["session_id"]),
                        )
                    )
                if worker_span is not None:
                    worker_span.update_metadata(
                        {
                            "task_status": result.status.value,
                            "coverage_status": result.coverage_status.value,
                            "evidence_count": len(result.evidence),
                            "retrieval_calls": result.retrieval_calls,
                            "analysis_calls": result.analysis_calls,
                            "child_task_count": len(result.child_task_proposals),
                        }
                    )
            return {"worker_results": (result,)}

        async def aggregate(state: ResearchGraphState) -> dict[str, object]:
            async with self.tracer.span(
                "enterprise_ai.research.aggregate",
                metadata={"round": state.get("round_number", 0)},
            ):
                processed = set(state.get("processed_task_ids", ()))
                current = tuple(
                    sorted(
                        (
                            item
                            for item in state.get("worker_results", ())
                            if item.task_id not in processed
                        ),
                        key=lambda item: item.task_id,
                    )
                )
                known = {
                    self._equivalence(task)
                    for task in (*plan.tasks, *state.get("pending_tasks", ()))
                }
                children: list[ResearchTask] = []
                for result in current:
                    processed.add(result.task_id)
                    for index, proposal in enumerate(
                        result.child_task_proposals[
                            : self.settings.research_max_child_tasks_per_worker
                        ],
                        1,
                    ):
                        if result.depth >= self.settings.research_max_depth:
                            continue
                        child = ResearchTask(
                            task_id=f"{result.task_id}.C{index:02d}",
                            parent_task_id=result.task_id,
                            depth=result.depth + 1,
                            task_type=proposal.task_type,
                            research_question=proposal.research_question,
                            search=ResearchSearchStrategy(
                                queries=proposal.queries, filters=DenseQueryFilters()
                            ),
                            priority=25,
                            completion_criteria=("Find authorized evidence for the gap",),
                        )
                        key = self._equivalence(child)
                        if key in known or not await ledger.consume("tasks"):
                            continue
                        known.add(key)
                        children.append(child)
            return {
                "pending_tasks": tuple(sorted(children, key=lambda item: item.task_id)),
                "processed_task_ids": tuple(sorted(processed)),
                "round_number": state.get("round_number", 0) + 1,
            }

        async def finalize(state: ResearchGraphState) -> dict[str, object]:
            stable_results = tuple(
                sorted(state.get("worker_results", ()), key=lambda item: item.task_id)
            )
            async with self.tracer.span("enterprise_ai.evidence_aggregation"):
                evidence = aggregate_evidence(
                    stable_results,
                    maximum_items=budget.maximum_evidence_items,
                    maximum_characters=budget.maximum_evidence_characters,
                    expected_build_fingerprint=(
                        plan.authorized_collection_summary.build_fingerprint
                    ),
                    principal=request.principal,
                    authorization=self.authorization,
                )
            usage = await ledger.usage()
            async with self.tracer.span("enterprise_ai.conflict_analysis"):
                conflicts = detect_conflicts(evidence)
            async with self.tracer.span(
                "enterprise_ai.coverage",
                metadata={
                    "evidence_count": len(evidence.entries),
                    "budget_exhausted": usage.exhausted,
                },
            ) as coverage_span:
                coverage = assess_coverage(
                    plan,
                    stable_results,
                    len(evidence.entries),
                    conflicts,
                    budget_exhausted=usage.exhausted,
                )
                if coverage_span is not None:
                    coverage_span.update_metadata(
                        {
                            "coverage_status": coverage.status.value,
                            "conflict_count": len(conflicts),
                            "retrieval_calls": usage.retrieval_calls,
                            "analysis_calls": usage.analysis_calls,
                            "llm_calls": usage.llm_calls,
                        }
                    )
            if not self.settings.research_allow_partial_results and any(
                item.error_category for item in stable_results
            ):
                coverage = coverage.model_copy(update={"status": CoverageStatus.FAILED})
            gaps = tuple(
                ResearchGap(
                    dimension=gap,
                    reason="Required research dimension was not fully supported.",
                )
                for gap in coverage.missing_dimensions
            )
            analyses = tuple(
                sorted(
                    (item.analysis_result for item in stable_results if item.analysis_result),
                    key=lambda item: (item.operation.value, str(item.request_id)),
                )
            )
            result = ResearchResult(
                plan=plan,
                worker_results=stable_results,
                evidence_ledger=evidence,
                coverage=coverage,
                gaps=gaps,
                conflicts=conflicts,
                budget_usage=usage,
                provenance=ResearchProvenance(
                    build_fingerprint=plan.authorized_collection_summary.build_fingerprint
                ),
                warnings=(
                    ("Some research workers failed; the result is partial.",)
                    if any(item.error_category for item in stable_results)
                    else ()
                ),
                analysis_results=analyses,
            )
            return {"result": result, "pending_tasks": ()}

        graph.add_node("initialize_research", initialize)
        graph.add_node("research_worker", execute)
        graph.add_node("aggregate_worker_results", aggregate)
        graph.add_node("finalize_research", finalize)
        graph.add_edge(START, "initialize_research")
        graph.add_conditional_edges("initialize_research", dispatch_workers)
        graph.add_edge("research_worker", "aggregate_worker_results")
        graph.add_conditional_edges("aggregate_worker_results", dispatch_workers)
        graph.add_edge("finalize_research", END)
        compiled = graph.compile()
        output = await compiled.ainvoke(
            {
                "principal": request.principal,
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "session_id": request.session_id,
                "worker_results": (),
                "processed_task_ids": (),
            },
            config={"recursion_limit": max(25, self.settings.research_max_total_tasks * 4)},
        )
        return cast(ResearchResult, output["result"])

    def _budget(self) -> ResearchBudget:
        return ResearchBudget(
            maximum_depth=self.settings.research_max_depth,
            maximum_total_tasks=self.settings.research_max_total_tasks,
            maximum_retrieval_calls=self.settings.research_max_retrieval_calls,
            maximum_analysis_calls=self.settings.research_max_analysis_calls,
            maximum_llm_calls=self.settings.research_max_llm_calls,
            maximum_evidence_items=self.settings.research_max_evidence_items,
            maximum_evidence_characters=self.settings.research_max_total_evidence_characters,
        )

    async def _plan_with_repair(
        self,
        question: str,
        principal: AuthenticatedPrincipal,
        ledger: BudgetLedger,
    ) -> ResearchPlan:
        if type(self).plan is not ResearchService.plan:
            return await self.plan(question, principal)
        catalog = self.catalogs.build(principal)
        proposed = await asyncio.wait_for(
            self.planner.create_plan(question, catalog),
            timeout=self.settings.research_planner_timeout_seconds,
        )
        try:
            return compile_plan(proposed, self.settings)
        except ResearchPlanValidationError as error:
            repair = getattr(self.planner, "repair_plan", None)
            if not error.repairable or repair is None or not await ledger.consume("llm_calls"):
                raise
            repaired = await asyncio.wait_for(
                repair(question, catalog, proposed, (str(error),)),
                timeout=self.settings.research_planner_timeout_seconds,
            )
            return compile_plan(repaired, self.settings)

    @staticmethod
    def _equivalence(task: ResearchTask) -> tuple[str, tuple[str, ...]]:
        return task.task_type.value, tuple(
            " ".join(sorted(set(query.casefold().replace(".", "").split())))
            for query in task.search.queries
        )
