import asyncio

import pytest
from enterprise_ai.models.identity import AuthenticatedPrincipal, ToolPermission, UserRole
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import ResearchBudget, ResearchTaskType
from enterprise_ai.research.worker import ResearchWorker
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.exceptions import AnalysisAuthorizationError, AnalysisError

from .test_executable_timeouts import ControlledRetriever, _input


class CountingAnalysis:
    def __init__(self) -> None:
        self.started = 0
        self.authorization = AuthorizationService()

    def require_authorized(self, principal: AuthenticatedPrincipal) -> None:
        if not self.authorization.has_permission(principal, ToolPermission.PYTHON_ANALYSIS):
            raise AnalysisAuthorizationError("analysis is not permitted")

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.started += 1
        raise AnalysisError("controlled analysis failure")


def _analysis_budget(limit: int) -> ResearchBudget:
    return ResearchBudget(
        maximum_depth=1,
        maximum_total_tasks=3,
        maximum_retrieval_calls=3,
        maximum_analysis_calls=limit,
        maximum_llm_calls=1,
        maximum_evidence_items=5,
        maximum_evidence_characters=100,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", (UserRole.ANALYST, UserRole.ADMINISTRATOR))
async def test_analysis_calls_start_only_with_atomic_budget(role: UserRole) -> None:
    analysis = CountingAnalysis()
    ledger = BudgetLedger(_analysis_budget(1))
    worker = ResearchWorker(
        ControlledRetriever(),
        ledger,
        1,
        analysis,
        AuthorizationService(),  # type: ignore[arg-type]
    )
    items = []
    for index in range(3):
        item = _input("root cause", f"T{index}")
        task = item.task.model_copy(
            update={
                "task_type": ResearchTaskType.ROOT_CAUSE_ANALYSIS,
                "analysis_may_be_useful": True,
            }
        )
        items.append(
            item.model_copy(
                update={
                    "task": task,
                    "principal": item.principal.model_copy(
                        update={
                            "identity": item.principal.identity.model_copy(update={"role": role})
                        }
                    ),
                }
            )
        )
    await asyncio.gather(*(worker.execute(item) for item in items))
    assert analysis.started == 1
    assert (await ledger.usage()).analysis_calls == 1


@pytest.mark.asyncio
async def test_viewer_consumes_no_analysis_budget() -> None:
    analysis = CountingAnalysis()
    ledger = BudgetLedger(_analysis_budget(1))
    worker = ResearchWorker(
        ControlledRetriever(),
        ledger,
        1,
        analysis,
        AuthorizationService(),  # type: ignore[arg-type]
    )
    item = _input("root cause", "T1")
    task = item.task.model_copy(update={"analysis_may_be_useful": True})
    viewer = item.principal.model_copy(
        update={"identity": item.principal.identity.model_copy(update={"role": UserRole.VIEWER})}
    )
    await worker.execute(item.model_copy(update={"task": task, "principal": viewer}))
    assert analysis.started == 0
    assert (await ledger.usage()).analysis_calls == 0


@pytest.mark.asyncio
async def test_comparison_worker_rejects_irrelevant_evidence_and_proposes_specific_gap() -> None:
    class IrrelevantRetriever:
        async def retrieve(self, *args: object, **kwargs: object) -> object:
            from enterprise_ai.retrieval.hybrid.models import (
                CompletionStatus,
                HybridRetrievalResult,
            )

            from .evidence_fixtures import evidence

            return HybridRetrievalResult(
                evidence=(evidence(9, title="Unrelated", text="Different subject."),),
                completion_status=CompletionStatus.COMPLETE,
            )

    ledger = BudgetLedger(_analysis_budget(0).model_copy(update={"maximum_retrieval_calls": 1}))
    worker = ResearchWorker(
        IrrelevantRetriever(),  # type: ignore[arg-type]
        ledger,
        1,
        CountingAnalysis(),
        AuthorizationService(),  # type: ignore[arg-type]
    )
    item = _input("secondary availability april", "T1")
    dimension = "secondary availability in April"
    task = item.task.model_copy(
        update={
            "task_type": ResearchTaskType.COMPARISON_DIMENSION,
            "comparison_dimension": dimension,
            "comparison_terms": ("secondary", "availability", "april"),
        }
    )
    outcome = await worker.execute(item.model_copy(update={"task": task}))
    assert not outcome.evidence
    assert outcome.comparison_dimension == dimension
    assert outcome.child_task_proposals[0].comparison_dimension == dimension
    assert outcome.child_task_proposals[0].queries == task.search.queries
