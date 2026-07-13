"""Bounded authorized targeted-retrieval worker."""

import asyncio
from time import monotonic

from enterprise_ai.graph.dependencies import KnowledgeRetriever
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import (
    CoverageStatus,
    ResearchChildTaskProposal,
    ResearchTaskStatus,
    ResearchTaskType,
    ResearchWorkerInput,
    ResearchWorkerResult,
)
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.exceptions import AnalysisError
from enterprise_ai.tools.python_analysis.models import AnalysisResult
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool, plan_analysis


class ResearchWorker:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        budget: BudgetLedger,
        timeout: float,
        analysis: PythonAnalysisTool,
        authorization: AuthorizationService,
    ) -> None:
        self.retriever = retriever
        self.budget = budget
        self.timeout = timeout
        self.analysis = analysis
        self.authorization = authorization

    async def execute(self, item: ResearchWorkerInput) -> ResearchWorkerResult:
        started = monotonic()
        evidence: list[HybridEvidence] = []
        modes: set[str] = set()
        executed: list[str] = []
        analysis_result: AnalysisResult | None = None
        try:
            for query in item.task.search.queries:
                if not await self.budget.consume("retrieval_calls"):
                    return self._result(
                        item, started, evidence, executed, modes, "budget_exhausted"
                    )
                result = await asyncio.wait_for(
                    self.retriever.retrieve(
                        item.principal,
                        query,
                        top_k=item.task.search.top_k,
                        filters=item.task.search.filters,
                        request_id=str(item.request_id),
                        trace_id=str(item.trace_id),
                    ),
                    timeout=self.timeout,
                )
                executed.append(query)
                evidence.extend(result.evidence)
                for found in result.evidence:
                    modes.update(found.retrieval_modes)
            analysis_calls = 0
            if item.task.analysis_may_be_useful:
                try:
                    self.analysis.require_authorized(item.principal)
                    if await self.budget.consume("analysis_calls"):
                        analysis_request = plan_analysis(item.task.research_question)
                        analysis_result = await self.analysis.execute(
                            item.principal,
                            analysis_request,
                            request_id=item.request_id,
                            trace_id=item.trace_id,
                        )
                        analysis_calls = 1
                except AnalysisError:
                    analysis_result = None
            return self._result(
                item, started, evidence, executed, modes, None, analysis_result, analysis_calls
            )
        except TimeoutError:
            return self._result(item, started, evidence, executed, modes, "worker_timeout")
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._result(item, started, evidence, executed, modes, "retrieval_failure")

    @staticmethod
    def _result(
        item: ResearchWorkerInput,
        started: float,
        evidence: list[HybridEvidence],
        executed: list[str],
        modes: set[str],
        error: str | None,
        analysis_result: AnalysisResult | None = None,
        analysis_calls: int = 0,
    ) -> ResearchWorkerResult:
        typed_evidence = tuple(evidence)
        proposals: tuple[ResearchChildTaskProposal, ...] = ()
        if not typed_evidence and item.task.depth < 2 and error is None:
            proposals = (
                ResearchChildTaskProposal(
                    parent_task_id=item.task.task_id,
                    task_type=ResearchTaskType.GAP_INVESTIGATION,
                    research_question=f"Narrow evidence gap for {item.task.research_question}",
                    queries=(item.task.research_question,),
                    reason="No authorized evidence was retrieved.",
                ),
            )
        return ResearchWorkerResult(
            task_id=item.task.task_id,
            parent_task_id=item.task.parent_task_id,
            depth=item.task.depth,
            status=(
                ResearchTaskStatus.FAILED
                if error
                else ResearchTaskStatus.COMPLETED
                if typed_evidence
                else ResearchTaskStatus.PARTIAL
            ),
            queries_executed=tuple(executed),
            retrieval_modes=tuple(sorted(modes)),
            evidence=typed_evidence,
            coverage_status=(
                CoverageStatus.FAILED
                if error
                else CoverageStatus.SUFFICIENT
                if typed_evidence
                else CoverageStatus.INSUFFICIENT
            ),
            gaps=(() if typed_evidence else ("No authorized matching evidence",)),
            child_task_proposals=proposals,
            error_category=error,
            duration_seconds=max(0, monotonic() - started),
            retrieval_calls=len(executed),
            analysis_result=analysis_result,
            analysis_calls=analysis_calls,
        )
