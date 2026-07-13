import asyncio

import pytest
from enterprise_ai.research.budgets import BudgetLedger
from enterprise_ai.research.models import ResearchBudget
from enterprise_ai.retrieval.config import RetrievalSettings


def _budget(limit: int = 2) -> ResearchBudget:
    return ResearchBudget(
        maximum_depth=2,
        maximum_total_tasks=limit,
        maximum_retrieval_calls=limit,
        maximum_analysis_calls=limit,
        maximum_llm_calls=limit,
        maximum_evidence_items=limit,
        maximum_evidence_characters=limit,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource",
    (
        "tasks",
        "retrieval_calls",
        "analysis_calls",
        "llm_calls",
        "evidence_items",
        "evidence_characters",
    ),
)
async def test_each_atomic_budget_stops_at_limit(resource: str) -> None:
    ledger = BudgetLedger(_budget())
    outcomes = await asyncio.gather(*(ledger.consume(resource) for _ in range(10)))
    assert sum(outcomes) == 2
    usage = await ledger.usage()
    assert getattr(usage, resource) == 2 and usage.exhausted


@pytest.mark.parametrize(
    "field",
    (
        "research_max_initial_tasks",
        "research_max_total_tasks",
        "research_max_parallel_workers",
        "research_max_retrieval_calls",
        "research_max_llm_calls",
        "research_max_evidence_items",
        "research_max_total_evidence_characters",
        "research_max_query_characters",
        "research_max_plan_characters",
        "research_max_queries_per_task",
        "research_planner_timeout_seconds",
        "research_worker_timeout_seconds",
        "research_max_execution_seconds",
    ),
)
def test_budget_settings_reject_non_positive_values(field: str) -> None:
    with pytest.raises(ValueError):
        RetrievalSettings.model_validate({field: 0})
